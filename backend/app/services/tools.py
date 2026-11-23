"""Tool definitions exposed to the LLM and their executors.

Each executor returns a `ToolOutcome`: a compact JSON string for the model
(kept small to control token cost) and an optional rich payload for the UI.
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from typing import Any

import duckdb
import pandas as pd

from app.config import get_settings
from app.models import Dataset
from app.services import analytics
from app.services.bulkhead import QUERY
from app.services.query_engine import QueryError, connect_for_tools, run_query
from app.services.sql_guard import UnsafeSqlError, validate_sql

MODEL_ROW_PREVIEW = 40
CHART_POINT_LIMIT = 500
UI_TABLE_LIMIT = 500

CHART_TYPES = ["bar", "horizontal_bar", "line", "area", "pie", "scatter", "stacked_bar"]

TOOLS: list[dict] = [
    {
        "name": "run_sql",
        "description": "Run one read-only DuckDB SELECT query over the user's tables and get the result rows.",
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "A single SELECT or WITH query."},
                "purpose": {"type": "string", "description": "Short description of what this query answers."},
            },
            "required": ["sql", "purpose"],
        },
    },
    {
        "name": "create_chart",
        "description": "Run a SELECT query and render its result as a chart for the user.",
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "Query whose columns include x and every y column."},
                "chart_type": {"type": "string", "enum": CHART_TYPES},
                "x": {"type": "string", "description": "Column for the x axis / category / pie label."},
                "y": {"type": "array", "items": {"type": "string"}, "minItems": 1,
                      "description": "One or more numeric columns to plot."},
                "series": {"type": "string",
                           "description": "Optional column whose values become separate series (long format)."},
                "title": {"type": "string"},
                "y_label": {"type": "string"},
            },
            "required": ["sql", "chart_type", "x", "y", "title"],
        },
    },
    {
        "name": "detect_anomalies",
        "description": "Flag statistical outliers in a numeric column of a query result (robust z-score using "
                       "median and MAD, IQR fallback). Returns each flagged row with the reason.",
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "Query producing the rows to inspect."},
                "value_column": {"type": "string"},
                "label_columns": {"type": "array", "items": {"type": "string"},
                                  "description": "Columns that identify a row (id, date, region...)."},
                "group_column": {"type": "string",
                                 "description": "Judge each value against its own group (e.g. product_id for "
                                                "prices, region for monthly totals). Strongly recommended when "
                                                "values naturally differ by category."},
                "threshold": {"type": "number", "description": "Robust z cut-off, default 3.5."},
            },
            "required": ["sql", "value_column"],
        },
    },
    {
        "name": "profile_table",
        "description": "Summary statistics for every column of a table: types, nulls, distinct, ranges, top values.",
        "parameters": {"type": "object", "properties": {"table": {"type": "string"}}, "required": ["table"]},
    },
    {
        "name": "forecast",
        "description": "Project a time series forward (linear trend, plus monthly seasonality with 24+ months).",
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "Query returning a date column and a numeric column."},
                "date_column": {"type": "string"},
                "value_column": {"type": "string"},
                "periods": {"type": "integer", "minimum": 1, "maximum": 36},
                "freq": {"type": "string", "enum": ["D", "W", "MS", "QS"], "description": "Default MS (monthly)."},
            },
            "required": ["sql", "date_column", "value_column"],
        },
    },
    {
        "name": "final_answer",
        "description": "Return the final answer to the user. Call exactly once, at the end.",
        "parameters": {
            "type": "object",
            "properties": {
                "answer": {"type": "string", "description": "Markdown answer."},
                "reasoning": {"type": "array", "items": {"type": "string"}},
                "sql": {"type": "string"},
                "pandas_code": {"type": "string"},
                "follow_ups": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
            },
            "required": ["answer", "reasoning"],
        },
    },
]


@dataclass
class ToolOutcome:
    model_content: str
    is_error: bool = False
    ui: dict[str, Any] | None = None
    final: dict[str, Any] | None = None
    sql: list[str] = field(default_factory=list)


def _compact(obj: Any) -> str:
    return json.dumps(obj, default=str, separators=(",", ":"))[:12_000]


def _frame(datasets: list[Dataset], sql: str) -> pd.DataFrame:
    """Query into a DataFrame for the statistics tools (same sandbox and timeout as run_query)."""
    safe = validate_sql(sql)
    timeout = get_settings().query_timeout_seconds
    with QUERY.slot():
        return _frame_unbounded(datasets, safe, timeout)


def _frame_unbounded(datasets: list[Dataset], safe: str, timeout: float) -> pd.DataFrame:
    con = connect_for_tools(datasets)
    timer = threading.Timer(timeout, con.interrupt)
    timer.start()
    try:
        return con.sql(f"SELECT * FROM ({safe}) AS _q LIMIT 200000").df()
    except duckdb.InterruptException as exc:
        raise QueryError(f"Query took longer than {timeout:.0f}s and was stopped.") from exc
    except duckdb.Error as exc:
        raise QueryError(str(exc).splitlines()[0]) from exc
    finally:
        timer.cancel()
        con.close()


class ToolExecutor:
    def __init__(self, datasets: list[Dataset]) -> None:
        self.datasets = datasets
        self.by_table = {d.table_name: d for d in datasets}

    def execute(self, name: str, args: dict) -> ToolOutcome:
        handler = getattr(self, f"_tool_{name}", None)
        if handler is None:
            return ToolOutcome(f"Unknown tool '{name}'.", is_error=True)
        try:
            return handler(**args)
        except TypeError as exc:
            return ToolOutcome(f"Invalid arguments for {name}: {exc}", is_error=True)
        except (UnsafeSqlError, QueryError, ValueError) as exc:
            return ToolOutcome(f"Error: {exc}", is_error=True)

    # -- tools ---------------------------------------------------------------
    def _tool_run_sql(self, sql: str, purpose: str = "") -> ToolOutcome:
        res = run_query(self.datasets, sql, limit=UI_TABLE_LIMIT)
        preview = res.rows[:MODEL_ROW_PREVIEW]
        model = {"columns": res.columns, "rows": preview, "row_count": res.row_count,
                 "note": f"showing first {len(preview)} of {res.row_count}{'+' if res.truncated else ''} rows"}
        return ToolOutcome(_compact(model), sql=[res.sql],
                           ui={"type": "table", "title": purpose or "Query result", **res.to_dict()})

    def _tool_create_chart(self, sql: str, chart_type: str, x: str, y: list[str] | str, title: str,
                           series: str | None = None, y_label: str | None = None) -> ToolOutcome:
        if chart_type not in CHART_TYPES:
            raise ValueError(f"chart_type must be one of {CHART_TYPES}")
        y_cols = [y] if isinstance(y, str) else list(y)
        res = run_query(self.datasets, sql, limit=CHART_POINT_LIMIT)
        missing = [c for c in [x, *y_cols, *([series] if series else [])] if c not in res.columns]
        if missing:
            raise ValueError(f"Columns {missing} not in query result {res.columns}")
        records = [dict(zip(res.columns, r, strict=True)) for r in res.rows]

        if series:  # pivot long -> wide so the frontend gets one key per series
            wide: dict[Any, dict] = {}
            names: list[str] = []
            for r in records:
                key = r[x]
                s_name = str(r[series])
                if s_name not in names:
                    names.append(s_name)
                wide.setdefault(key, {x: key})[s_name] = r[y_cols[0]]
            records, y_cols = list(wide.values()), names[:12]

        chart = {"type": "chart", "chart_type": chart_type, "title": title, "x": x, "y": y_cols,
                 "y_label": y_label, "data": records, "sql": res.sql, "truncated": res.truncated}
        summary = {"rendered": True, "points": len(records), "series": y_cols,
                   "first_rows": records[:15]}
        return ToolOutcome(_compact(summary), ui=chart, sql=[res.sql])

    def _tool_detect_anomalies(self, sql: str, value_column: str, label_columns: list[str] | None = None,
                               threshold: float = 3.5, group_column: str | None = None) -> ToolOutcome:
        df = _frame(self.datasets, sql)
        result = analytics.detect_anomalies(df, value_column, label_columns, float(threshold or 3.5),
                                            group_column=group_column or None)
        ui = {"type": "anomalies", "value_column": value_column, "sql": sql, **result}
        return ToolOutcome(_compact({k: v for k, v in result.items()} | {"flagged": result["flagged"][:15]}),
                           ui=ui, sql=[sql])

    def _tool_profile_table(self, table: str) -> ToolOutcome:
        ds = self.by_table.get(table)
        if ds is None:
            raise ValueError(f"Unknown table '{table}'. Available: {list(self.by_table)}")
        df = _frame(self.datasets, f'SELECT * FROM "{table}"')
        profile = analytics.profile_frame(df)
        profile["quality"] = ds.quality_json
        return ToolOutcome(_compact(profile), ui={"type": "profile", "table": table, **profile})

    def _tool_forecast(self, sql: str, date_column: str, value_column: str, periods: int = 6,
                       freq: str = "MS") -> ToolOutcome:
        df = _frame(self.datasets, sql)
        result = analytics.forecast(df, date_column, value_column, periods, freq or "MS")
        data = [{"period": h["period"], "actual": h["value"]} for h in result["history"]] + \
               [{"period": f["period"], "forecast": f["value"], "low": f["low"], "high": f["high"]}
                for f in result["forecast"]]
        ui = {"type": "chart", "chart_type": "line", "title": f"Forecast of {value_column}", "x": "period",
              "y": ["actual", "forecast"], "data": data, "sql": sql, "band": ["low", "high"],
              "note": result["method"]}
        return ToolOutcome(_compact({k: v for k, v in result.items() if k != "history"} |
                                    {"last_actuals": result["history"][-6:]}), ui=ui, sql=[sql])

    def _tool_final_answer(self, answer: str, reasoning: list[str] | None = None, sql: str | None = None,
                           pandas_code: str | None = None, follow_ups: list[str] | None = None) -> ToolOutcome:
        return ToolOutcome("ok", final={
            "answer": answer.strip(), "reasoning": [r for r in (reasoning or []) if r][:8],
            "sql": (sql or "").strip() or None, "pandas_code": (pandas_code or "").strip() or None,
            "follow_ups": (follow_ups or [])[:3],
        })
