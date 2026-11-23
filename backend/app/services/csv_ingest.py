"""CSV validation, normalisation and data-quality profiling.

Pipeline: size check -> binary sniff -> encoding detection -> delimiter sniff
-> parse -> limits -> column name sanitising -> type inference -> quality report.
Each step raises `CsvValidationError` with a message a user can act on.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass

import numpy as np
import pandas as pd
import pyarrow as pa

from app.config import get_settings

_ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")
_DELIMS = [",", ";", "\t", "|"]
_CURRENCY_RE = re.compile(r"^\s*[-+]?[$€£₹¥]?\s*[-+]?[\d,]+(\.\d+)?\s*%?\s*$")
_RESERVED = {"select", "from", "where", "table", "group", "order", "by", "limit", "join", "on", "as", "and",
             "or", "not", "null", "user", "date", "time", "timestamp", "values", "case", "when", "end",
             # words the SQL guard blocks; a column called "load" must not make every query fail
             "attach", "detach", "copy", "export", "import", "install", "load", "pragma", "set", "reset",
             "call", "create", "insert", "update", "delete", "drop", "alter", "truncate", "vacuum",
             "checkpoint", "grant", "revoke", "use"}


class CsvValidationError(ValueError):
    pass


@dataclass
class IngestResult:
    table: pa.Table
    frame: pd.DataFrame
    schema: list[dict]
    quality: dict
    encoding: str
    delimiter: str


def sanitize_identifier(name: str, fallback: str = "col") -> str:
    """Turn an arbitrary header into a safe, readable snake_case SQL identifier."""
    s = re.sub(r"[^0-9a-zA-Z]+", "_", str(name).strip()).strip("_").lower()
    s = re.sub(r"_+", "_", s)
    if not s:
        s = fallback
    if s[0].isdigit():
        s = f"c_{s}"
    if s in _RESERVED:
        s = f"{s}_"
    return s[:60]


def table_name_from_filename(filename: str) -> str:
    stem = filename.rsplit(".", 1)[0]
    return sanitize_identifier(stem, fallback="dataset")


def _decode(raw: bytes) -> tuple[str, str]:
    if b"\x00" in raw[:8192]:
        raise CsvValidationError("This looks like a binary file, not a CSV. Export it as CSV and try again.")
    for enc in _ENCODINGS:
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    raise CsvValidationError("Could not detect the file encoding. Please save it as UTF-8.")


def _sniff_delimiter(text: str) -> str:
    sample = "\n".join(text.splitlines()[:50])
    try:
        return csv.Sniffer().sniff(sample, delimiters="".join(_DELIMS)).delimiter
    except csv.Error:
        # Fall back to whichever delimiter splits the header into the most columns.
        header = sample.splitlines()[0] if sample else ""
        return max(_DELIMS, key=header.count)


def _parse(text: str, delimiter: str) -> tuple[pd.DataFrame, int]:
    try:
        # index_col=False: rows with extra fields must be errors, not silently become an index.
        return pd.read_csv(io.StringIO(text), sep=delimiter, dtype=str, keep_default_na=True,
                           skipinitialspace=True, index_col=False), 0
    except pd.errors.ParserError:
        pass
    # Slow path: let the csv module split records (it handles quoting and embedded
    # newlines), keep rows with the header's field count and count the rest.
    reader = csv.reader(io.StringIO(text), delimiter=delimiter, skipinitialspace=True)
    header = next(reader, None)
    if not header:
        raise CsvValidationError("The file has no header row.")
    good, bad = [], 0
    for row in reader:
        if not row:
            continue
        if len(row) == len(header):
            good.append(row)
        else:
            bad += 1
    df = pd.DataFrame(good, columns=header, dtype="string").replace({"": None})
    return df.astype(object), bad


def _coerce_numeric(series: pd.Series) -> pd.Series | None:
    s = series.dropna().astype(str).str.strip()
    s = s[s != ""]
    if s.empty:
        return None
    if s.str.match(_CURRENCY_RE).mean() < 0.95:
        return None
    # Leading zeros ("00123") are identifiers, not numbers: keep as text.
    if (s.str.match(r"^0\d+$")).mean() > 0.2:
        return None
    cleaned = series.astype(str).str.replace(r"[,$€£₹¥%\s]", "", regex=True).replace({"": None, "nan": None})
    out = pd.to_numeric(cleaned, errors="coerce")
    if (out.dropna() % 1 == 0).all() and out.notna().any():
        return out.astype("Int64")
    return out.astype("float64")


def _coerce_datetime(series: pd.Series) -> pd.Series | None:
    s = series.dropna().astype(str).str.strip()
    if s.empty or not s.str.contains(r"\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}|^\d{4}-\d{2}$", regex=True).mean() > 0.9:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d-%m-%Y", "%Y-%m"):
        parsed = pd.to_datetime(series, format=fmt, errors="coerce")
        if parsed.notna().sum() >= 0.95 * series.notna().sum():
            return parsed
    parsed = pd.to_datetime(series, errors="coerce", format="mixed")
    if parsed.notna().sum() >= 0.95 * series.notna().sum():
        return parsed
    return None


def _infer_types(df: pd.DataFrame) -> pd.DataFrame:
    out = {}
    for col in df.columns:
        series = df[col]
        if series.isna().all():
            out[col] = series
            continue
        num = _coerce_numeric(series)
        if num is not None:
            out[col] = num
            continue
        dt = _coerce_datetime(series)
        if dt is not None:
            out[col] = dt
            continue
        lowered = series.dropna().astype(str).str.strip().str.lower()
        if not lowered.empty and lowered.isin({"true", "false", "yes", "no"}).all():
            truthy = {"true": True, "yes": True, "false": False, "no": False}
            out[col] = lowered.reindex(series.index).map(truthy).astype("boolean")
            continue
        out[col] = series.astype("string").str.strip()
    return pd.DataFrame(out)


def _kind(dtype) -> str:
    if pd.api.types.is_bool_dtype(dtype):
        return "boolean"
    if pd.api.types.is_integer_dtype(dtype):
        return "integer"
    if pd.api.types.is_float_dtype(dtype):
        return "number"
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return "datetime"
    return "text"


def build_schema(df: pd.DataFrame, original_names: dict[str, str]) -> list[dict]:
    schema = []
    for col in df.columns:
        s = df[col]
        kind = _kind(s.dtype)
        entry = {
            "name": col,
            "original_name": original_names.get(col, col),
            "type": kind,
            "nulls": int(s.isna().sum()),
            "distinct": int(s.nunique(dropna=True)),
        }
        non_null = s.dropna()
        if kind in ("integer", "number") and not non_null.empty:
            entry.update(min=float(non_null.min()), max=float(non_null.max()), mean=round(float(non_null.mean()), 4))
        elif kind == "datetime" and not non_null.empty:
            entry.update(min=non_null.min().isoformat(), max=non_null.max().isoformat())
        elif kind == "text":
            entry["examples"] = [str(v)[:40] for v in non_null.drop_duplicates().head(3)]
        schema.append(entry)
    return schema


def quality_report(df: pd.DataFrame, skipped_rows: int) -> dict:
    issues: list[dict] = []
    n = len(df)
    dup = int(df.duplicated().sum())
    if dup:
        issues.append({"severity": "warning", "column": None, "issue": f"{dup} fully duplicated rows"})
    if skipped_rows:
        issues.append({"severity": "warning", "column": None,
                       "issue": f"{skipped_rows} malformed rows were skipped (wrong number of fields)"})
    for col in df.columns:
        s = df[col]
        missing = int(s.isna().sum())
        if missing:
            pct = missing / n * 100
            issues.append({"severity": "warning" if pct > 20 else "info", "column": col,
                           "issue": f"{missing} missing values ({pct:.1f}%)"})
        if n > 1 and s.nunique(dropna=True) == 1:
            issues.append({"severity": "info", "column": col, "issue": "constant column (one distinct value)"})
        if _kind(s.dtype) in ("integer", "number"):
            vals = s.dropna().astype(float)
            if len(vals) >= 8:
                q1, q3 = np.percentile(vals, [25, 75])
                iqr = q3 - q1
                if iqr > 0:
                    outliers = int(((vals < q1 - 3 * iqr) | (vals > q3 + 3 * iqr)).sum())
                    if outliers:
                        issues.append({"severity": "info", "column": col,
                                       "issue": f"{outliers} extreme values (beyond 3x IQR)"})
        if _kind(s.dtype) == "text":
            stripped = s.dropna().astype(str)
            if not stripped.empty and stripped.str.match(r"^[=+\-@]").mean() > 0:
                issues.append({"severity": "info", "column": col,
                               "issue": "values start with = + - @ (escaped on export to prevent formula injection)"})
    score = max(0, 100 - sum(10 if i["severity"] == "warning" else 2 for i in issues))
    return {"score": score, "rows": n, "duplicate_rows": dup, "skipped_rows": skipped_rows, "issues": issues}


def ingest_csv(raw: bytes, filename: str) -> IngestResult:
    s = get_settings()
    if not filename.lower().endswith((".csv", ".txt", ".tsv")):
        raise CsvValidationError("Only .csv files are supported.")
    if len(raw) == 0:
        raise CsvValidationError("The file is empty.")
    if len(raw) > s.max_upload_mb * 1024 * 1024:
        raise CsvValidationError(f"File is larger than the {s.max_upload_mb} MB limit.")

    text, encoding = _decode(raw)
    delimiter = _sniff_delimiter(text)
    try:
        df, skipped = _parse(text, delimiter)
    except (pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise CsvValidationError(f"Could not parse the CSV: {exc}".split("\n")[0]) from exc

    df = df.dropna(how="all")
    if df.shape[1] < 1 or len(df) == 0:
        raise CsvValidationError("The file has a header but no data rows.")
    if df.shape[1] > s.max_columns:
        raise CsvValidationError(f"Too many columns ({df.shape[1]}). The limit is {s.max_columns}.")
    if len(df) > s.max_rows_per_file:
        raise CsvValidationError(f"Too many rows ({len(df):,}). The limit is {s.max_rows_per_file:,}.")
    unnamed = [c for c in df.columns if str(c).startswith("Unnamed:")]
    if len(unnamed) == df.shape[1]:
        raise CsvValidationError("The first row must be a header with column names.")

    # Sanitise + de-duplicate column names; remember the originals for display.
    original_names: dict[str, str] = {}
    seen: dict[str, int] = {}
    new_cols = []
    for i, col in enumerate(df.columns):
        base = sanitize_identifier(col, fallback=f"col_{i + 1}")
        name = base
        if name in seen:
            seen[base] += 1
            name = f"{base}_{seen[base]}"
        seen.setdefault(name, 1)
        original_names[name] = str(col)
        new_cols.append(name)
    df.columns = new_cols

    df = _infer_types(df).reset_index(drop=True)
    table = pa.Table.from_pandas(df, preserve_index=False)
    return IngestResult(
        table=table,
        frame=df,
        schema=build_schema(df, original_names),
        quality=quality_report(df, skipped),
        encoding=encoding,
        delimiter=delimiter,
    )
