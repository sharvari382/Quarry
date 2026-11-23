import pytest

from app.services.sql_guard import UnsafeSqlError, validate_sql

ALLOWED = [
    "SELECT * FROM sales",
    "select region, sum(revenue) from sales group by 1 order by 2 desc limit 5;",
    "WITH m AS (SELECT date_trunc('month', order_date) m, sum(revenue) r FROM sales GROUP BY 1) SELECT * FROM m",
    "SELECT * FROM sales WHERE note = 'please DROP this; DELETE that'",  # keywords inside a string literal
    'SELECT "update" FROM t',  # quoted identifier
    "SELECT s.*, c.segment FROM sales s JOIN customers c USING (customer_id)",
]

BLOCKED = [
    ("DROP TABLE sales", "read-only"),
    ("DELETE FROM sales", "read-only"),
    ("INSERT INTO sales VALUES (1)", "read-only"),
    ("SELECT 1; SELECT 2", "single statement"),
    ("SELECT * FROM read_csv('/etc/passwd')", "read_csv"),
    ("SELECT * FROM read_parquet('s3://bucket/x')", "read_parquet"),
    ("SELECT * FROM glob('/*')", "glob"),
    ("SELECT getenv('HOME')", "getenv"),
    ("SELECT current_setting('threads')", "current_setting"),
    ("ATTACH 'other.db' AS o", "read-only"),
    ("COPY sales TO 'out.csv'", "read-only"),
    ("INSTALL httpfs", "read-only"),
    ("PRAGMA database_list", "read-only"),
    ("SELECT * FROM duckdb_settings()", "duckdb_settings"),
    ("SELECT * FROM sales /* sneaky */ ; DROP TABLE sales", "single statement"),
    ("", "Empty"),
    ("SELEC broken", "syntax"),
]


@pytest.mark.parametrize("sql", ALLOWED)
def test_allows_read_only_queries(sql):
    assert validate_sql(sql)


@pytest.mark.parametrize("sql,msg", BLOCKED)
def test_blocks_unsafe_queries(sql, msg):
    with pytest.raises(UnsafeSqlError, match=msg):
        validate_sql(sql)


def test_rejects_huge_query():
    with pytest.raises(UnsafeSqlError, match="too long"):
        validate_sql("SELECT " + "1+" * 5000 + "1")
