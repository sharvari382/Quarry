import pytest

from app.services.csv_ingest import CsvValidationError, ingest_csv, sanitize_identifier, table_name_from_filename


def _types(result):
    return {c["name"]: c["type"] for c in result.schema}


def test_parses_types_and_sanitises_headers():
    raw = b"Order Date,Region Name,Revenue ($),Units,Active\n2024-01-05,North,\"$1,200.50\",3,yes\n" \
          b"2024-02-10,South,980,2,no\n"
    r = ingest_csv(raw, "Q1 Sales.csv")
    assert _types(r) == {"order_date": "datetime", "region_name": "text", "revenue": "number",
                         "units": "integer", "active": "boolean"}
    assert r.frame["revenue"].tolist() == [1200.5, 980.0]
    originals = {c["name"]: c["original_name"] for c in r.schema}
    assert originals["revenue"] == "Revenue ($)"


@pytest.mark.parametrize("delim", [";", "\t", "|"])
def test_detects_delimiters(delim):
    raw = f"a{delim}b{delim}c\n1{delim}2{delim}3\n4{delim}5{delim}6\n".encode()
    r = ingest_csv(raw, "x.csv")
    assert r.delimiter == delim and list(r.frame.columns) == ["a", "b", "c"]


def test_windows_1252_encoding():
    raw = "city,amount\nZürich,10\nSão Paulo,20\n".encode("cp1252")
    r = ingest_csv(raw, "x.csv")
    assert r.frame["city"].tolist() == ["Zürich", "São Paulo"]


def test_utf8_bom_is_stripped():
    r = ingest_csv("﻿id,v\n1,2\n".encode(), "x.csv")
    assert list(r.frame.columns) == ["id", "v"]


def test_duplicate_and_reserved_headers():
    r = ingest_csv(b"select,Value,value,1st\n1,2,3,4\n", "x.csv")
    assert list(r.frame.columns) == ["select_", "value", "value_2", "c_1st"]


def test_leading_zero_ids_stay_text():
    r = ingest_csv(b"zip,n\n00123,1\n04567,2\n00042,3\n", "x.csv")
    assert _types(r)["zip"] == "text"
    assert r.frame["zip"].tolist() == ["00123", "04567", "00042"]


def test_malformed_rows_are_skipped_and_reported():
    raw = b"a,b\n1,2\n3,4,5,6\n7,8\n"
    r = ingest_csv(raw, "x.csv")
    assert len(r.frame) == 2
    assert r.quality["skipped_rows"] == 1


def test_quality_report_flags_missing_duplicates_constant():
    raw = b"a,b,c\n1,,x\n1,,x\n2,5,x\n"
    q = ingest_csv(raw, "x.csv").quality
    issues = " ".join(i["issue"] for i in q["issues"])
    assert "duplicated" in issues and "missing" in issues and "constant" in issues
    assert q["score"] < 100


@pytest.mark.parametrize("raw,name,msg", [
    (b"", "x.csv", "empty"),
    (b"a,b\n", "x.csv", "no data rows"),
    (b"\x00\x01\x02binary", "x.csv", "binary"),
    (b"a,b\n1,2\n", "x.xlsx", "Only .csv"),
])
def test_rejects_bad_files(raw, name, msg):
    with pytest.raises(CsvValidationError, match=msg):
        ingest_csv(raw, name)


def test_rejects_too_many_columns(monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "max_columns", 3)
    with pytest.raises(CsvValidationError, match="Too many columns"):
        ingest_csv(b"a,b,c,d\n1,2,3,4\n", "x.csv")


def test_identifier_helpers():
    assert sanitize_identifier("  Total Revenue (USD) ") == "total_revenue_usd"
    assert sanitize_identifier("%%%") == "col"
    assert table_name_from_filename("2024 Sales-Report.final.csv") == "c_2024_sales_report_final"
