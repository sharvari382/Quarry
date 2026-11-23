"""Sandboxed SQL execution over a user's datasets with DuckDB.

Each query gets a brand-new in-memory DuckDB connection that contains only the
tables the caller is allowed to see. External access (files, HTTP, extensions)
is disabled and the configuration is locked before user SQL runs. A watchdog
interrupts queries that exceed the timeout. Results are cached in Redis keyed
by the content hash of the datasets plus the normalised SQL.
"""
from __future__ import annotations

import hashlib
import json
import math
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

import duckdb
import pyarrow as pa

from app.config import get_settings
from app.models import Dataset
from app.observability import QUERY_SECONDS
from app.services.bulkhead import QUERY
from app.services.kv import get_kv
from app.services.sql_guard import validate_sql
from app.services.storage import load_table


class QueryError(Exception):
    pass


@dataclass
class QueryResult:
    sql: str
    columns: list[str]
    rows: list[list]
    row_count: int
    truncated: bool
    elapsed_ms: int
    cached: bool = False
    column_types: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "sql": self.sql, "columns": self.columns, "column_types": self.column_types, "rows": self.rows,
            "row_count": self.row_count, "truncated": self.truncated, "elapsed_ms": self.elapsed_ms,
            "cached": self.cached,
        }


def _json_value(v):
    if v is None:
        return None
    if isinstance(v, float):
        return None if math.isnan(v) or math.isinf(v) else round(v, 6)
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray)):
        return "<binary>"
    if isinstance(v, (int, str, bool)):
        return v
    return str(v)


def _connect(datasets: list[Dataset]) -> duckdb.DuckDBPyConnection:
    s = get_settings()
    con = duckdb.connect(database=":memory:", config={"threads": 2, "memory_limit": s.query_memory_limit})
    for ds in datasets:
        con.register(ds.table_name, load_table(ds.blob_key))
    con.execute("SET enable_external_access = false")
    con.execute("SET autoinstall_known_extensions = false")
    con.execute("SET autoload_known_extensions = false")
    con.execute("SET lock_configuration = true")
    return con


def connect_for_tools(datasets: list[Dataset]) -> duckdb.DuckDBPyConnection:
    """Same sandbox, for analytics tools that need a pyarrow table out of a query."""
    return _connect(datasets)


def _cache_key(datasets: list[Dataset], sql: str, limit: int) -> str:
    h = hashlib.sha256()
    for ds in sorted(datasets, key=lambda d: d.table_name):
        h.update(f"{ds.table_name}:{ds.sha256};".encode())
    h.update(" ".join(sql.split()).lower().encode())
    h.update(str(limit).encode())
    return "q:" + h.hexdigest()


def run_query(datasets: list[Dataset], sql: str, limit: int | None = None, use_cache: bool = True) -> QueryResult:
    s = get_settings()
    limit = min(limit or s.query_row_limit, s.query_row_limit)
    safe_sql = validate_sql(sql)
    kv = get_kv()
    key = _cache_key(datasets, safe_sql, limit)

    if use_cache and (hit := kv.get(key)):
        data = json.loads(hit)
        data["cached"] = True
        return QueryResult(**data)

    with QUERY.slot():
        return _execute(datasets, safe_sql, limit, key if use_cache else None)


def _execute(datasets: list[Dataset], safe_sql: str, limit: int, cache_key: str | None) -> QueryResult:
    s = get_settings()
    started = time.perf_counter()
    con = _connect(datasets)
    timer = threading.Timer(s.query_timeout_seconds, con.interrupt)
    timer.start()
    try:
        # Fetch limit+1 so we know whether the result was truncated without a COUNT(*).
        arrow: pa.Table = con.sql(f"SELECT * FROM ({safe_sql}) AS _q LIMIT {limit + 1}").to_arrow_table()
    except duckdb.InterruptException as exc:
        raise QueryError(f"Query took longer than {s.query_timeout_seconds:.0f}s and was stopped.") from exc
    except duckdb.Error as exc:
        raise QueryError(str(exc).splitlines()[0]) from exc
    finally:
        timer.cancel()
        con.close()

    elapsed = time.perf_counter() - started
    QUERY_SECONDS.observe(elapsed)
    truncated = arrow.num_rows > limit
    if truncated:
        arrow = arrow.slice(0, limit)
    columns = arrow.column_names
    pylists = [arrow.column(i).to_pylist() for i in range(arrow.num_columns)]
    rows = [[_json_value(col[r]) for col in pylists] for r in range(arrow.num_rows)]
    result = QueryResult(
        sql=safe_sql, columns=columns, rows=rows, row_count=len(rows), truncated=truncated,
        elapsed_ms=int(elapsed * 1000), column_types=[str(t) for t in arrow.schema.types],
    )
    if cache_key:
        payload = json.dumps({k: v for k, v in result.to_dict().items() if k != "cached"})
        if len(payload) < 2_000_000:
            get_kv().set(cache_key, payload.encode(), s.result_cache_ttl_seconds)
    return result
