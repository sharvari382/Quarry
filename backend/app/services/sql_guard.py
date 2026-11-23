"""Validation of SQL written by the LLM (or pasted by a user) before execution.

Defence in depth, layer 1 of 3:
  1. this guard: exactly one read-only SELECT/WITH statement, no file/network/
     extension functions, parsed by DuckDB's own parser rather than regex alone;
  2. the engine: a fresh in-memory DuckDB per query with external access
     disabled and configuration locked (see query_engine.py);
  3. isolation: that connection only contains the current user's tables, so
     there is nothing else to reach even if 1 and 2 were bypassed.
"""
from __future__ import annotations

import re

import duckdb


class UnsafeSqlError(ValueError):
    pass


_FORBIDDEN_FUNCS = re.compile(
    r"\b(read_\w+|glob|sniff_csv|parquet_\w+|iceberg_\w+|delta_scan|query_table|query|"
    r"pg_\w+|sqlite_\w+|mysql_\w+|duckdb_\w+|getenv|current_setting|httpfs\w*|load_extension)\s*\(",
    re.IGNORECASE,
)
_FORBIDDEN_WORDS = re.compile(
    r"\b(attach|detach|copy|export|import|install|load|pragma|set|reset|call|create|insert|update|delete|"
    r"drop|alter|truncate|vacuum|checkpoint|grant|revoke|use)\b",
    re.IGNORECASE,
)
_STRING_OR_COMMENT = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|--[^\n]*|/\*.*?\*/", re.DOTALL)

MAX_SQL_LENGTH = 8_000


def _strip_literals(sql: str) -> str:
    """Remove string literals, quoted identifiers and comments before keyword checks,
    so `WHERE note = 'please drop this'` is not a false positive."""
    return _STRING_OR_COMMENT.sub(" ", sql)


def validate_sql(sql: str) -> str:
    if not sql or not sql.strip():
        raise UnsafeSqlError("Empty query.")
    if len(sql) > MAX_SQL_LENGTH:
        raise UnsafeSqlError("Query is too long.")
    cleaned = sql.strip().rstrip(";").strip()

    try:
        statements = duckdb.extract_statements(cleaned)
    except duckdb.Error as exc:
        raise UnsafeSqlError(f"SQL syntax error: {str(exc).splitlines()[0]}") from exc
    if len(statements) != 1:
        raise UnsafeSqlError("Only a single statement is allowed.")
    if statements[0].type != duckdb.StatementType.SELECT:
        raise UnsafeSqlError("Only read-only SELECT queries are allowed.")

    bare = _strip_literals(cleaned)
    if m := _FORBIDDEN_FUNCS.search(bare):
        raise UnsafeSqlError(f"Function '{m.group(1)}' is not allowed.")
    if m := _FORBIDDEN_WORDS.search(bare):
        raise UnsafeSqlError(f"Keyword '{m.group(1).upper()}' is not allowed in analysis queries.")
    return cleaned
