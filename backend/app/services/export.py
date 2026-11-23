"""Export a conversation as a Markdown report, and CSV export with formula-injection escaping."""
from __future__ import annotations

import csv
import io

from app.models import Conversation, Dataset

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value) -> str:
    """Prefix spreadsheet-formula-looking strings with a quote (OWASP CSV injection)."""
    s = "" if value is None else str(value)
    if s.startswith(_FORMULA_PREFIXES) and not _is_number(s):
        return "'" + s
    return s


def _is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def rows_to_csv(columns: list[str], rows: list[list]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([safe_cell(c) for c in columns])
    for r in rows:
        w.writerow([safe_cell(v) for v in r])
    return buf.getvalue()


def _md_table(columns: list[str], rows: list[list], limit: int = 20) -> str:
    def esc(v):
        return str("" if v is None else v).replace("|", "\\|").replace("\n", " ")

    out = ["| " + " | ".join(esc(c) for c in columns) + " |", "|" + "---|" * len(columns)]
    out += ["| " + " | ".join(esc(v) for v in r) + " |" for r in rows[:limit]]
    if len(rows) > limit:
        out.append(f"\n_{len(rows) - limit} more rows not shown._")
    return "\n".join(out)


def conversation_markdown(conv: Conversation, datasets: list[Dataset]) -> str:
    lines = [f"# {conv.title}", "", f"_Exported from Quarry on {conv.updated_at:%Y-%m-%d %H:%M} UTC_", ""]
    if datasets:
        lines += ["## Datasets", ""]
        lines += [f"- `{d.table_name}` from {d.original_filename} ({d.row_count:,} rows)" for d in datasets]
        lines.append("")
    for m in conv.messages:
        if m.role == "user":
            lines += [f"## Q: {m.content}", ""]
            continue
        a = m.artifacts or {}
        lines += [m.content, ""]
        for item in a.get("items", []):
            if item.get("type") == "table":
                lines += [f"**{item.get('title', 'Result')}**", "", _md_table(item["columns"], item["rows"]), ""]
            elif item.get("type") == "chart":
                lines += [f"_Chart: {item.get('title')} ({item.get('chart_type')})_", ""]
            elif item.get("type") == "anomalies":
                lines += [f"**Anomalies in `{item['value_column']}`**: {item['summary']}", ""]
                lines += [f"- {f['reason']}" for f in item.get("flagged", [])[:10]] + [""]
        if a.get("reasoning"):
            lines += ["<details><summary>How this was worked out</summary>", ""]
            lines += [f"{i}. {r}" for i, r in enumerate(a["reasoning"], 1)] + ["", "</details>", ""]
        if a.get("final_sql"):
            lines += ["```sql", a["final_sql"], "```", ""]
        if a.get("pandas_code"):
            lines += ["```python", a["pandas_code"], "```", ""]
    return "\n".join(lines)
