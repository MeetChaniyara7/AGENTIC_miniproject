import json
import sqlite3

import pytest

from config import ALLOWED_TABLES, SENSITIVE_COLUMNS, SQL_ROW_LIMIT, get_settings
from scripts.load_olist import TABLES, load_all
from tests.olist_fixture import write_csvs
from tools.sql_executor import run_sql
from tools.sql_validator import find_sensitive, validate_sql


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    d = tmp_path_factory.mktemp("olist")
    write_csvs(d / "raw")
    load_all(d / "raw", d / "olist.db")
    return d / "olist.db"


# ---------- safe queries are accepted ----------
SAFE = [
    "SELECT * FROM orders",
    "SELECT order_status, COUNT(*) FROM orders GROUP BY order_status",
    "select count(*) from ORDERS",                                        # case-insensitive
    "SELECT o.order_id FROM orders o JOIN order_items i ON i.order_id = o.order_id",
    "WITH t AS (SELECT order_id FROM orders) SELECT COUNT(*) FROM t",     # CTE name is not a table
    "SELECT order_id FROM orders UNION SELECT order_id FROM order_items",
    "SELECT strftime('%Y-%m', order_purchase_timestamp) AS m, COUNT(*) FROM orders GROUP BY m",
    "SELECT * FROM (SELECT order_id FROM orders) AS sub",
    "SELECT order_id FROM orders;",                                       # one trailing semicolon is fine
    "SELECT order_id FROM orders WHERE order_status = '--not a comment'", # '--' inside a string literal
]


@pytest.mark.parametrize("sql", SAFE)
def test_safe_queries_pass(sql):
    r = validate_sql(sql)
    assert r.ok, r.error
    assert r.error is None and r.cleaned_sql and not r.requires_approval


def test_example_queries_validate_and_run_identically(db):
    """All 12 curated queries survive validation and return the same rows after sqlglot rewrites them."""
    for ex in json.loads(get_settings().example_queries_path.read_text(encoding="utf-8")):
        r = validate_sql(ex["sql"])
        assert r.ok, (ex["id"], r.error)
        assert not r.requires_approval, ex["id"]
        original, cleaned = run_sql(ex["sql"], db), run_sql(r.cleaned_sql, db)
        assert original.ok and cleaned.ok, (ex["id"], original.error, cleaned.error)
        assert cleaned.rows == original.rows[:SQL_ROW_LIMIT], ex["id"]


# ---------- writes, DDL, and other statement types are rejected ----------
NOT_SELECT = [
    ("INSERT INTO orders (order_id) VALUES ('x')", "INSERT"),
    ("UPDATE orders SET order_status = 'delivered'", "UPDATE"),
    ("DELETE FROM orders", "DELETE"),
    ("DROP TABLE orders", "DROP"),
    ("CREATE TABLE evil (a TEXT)", "CREATE"),
    ("ALTER TABLE orders ADD COLUMN x TEXT", "ALTER"),
    ("PRAGMA table_info(orders)", "PRAGMA"),
    ("ATTACH DATABASE 'other.db' AS other", "ATTACH"),
    ("VACUUM", "VACUUM"),
]


@pytest.mark.parametrize("sql,keyword", NOT_SELECT)
def test_non_select_rejected(sql, keyword):
    r = validate_sql(sql)
    assert not r.ok and not r.requires_approval and r.cleaned_sql == ""
    assert "SELECT" in r.error


# ---------- injection tricks ----------
@pytest.mark.parametrize("sql", [
    "SELECT 1 FROM orders; DROP TABLE orders",
    "SELECT 1 FROM orders; SELECT 2 FROM orders",
    "SELECT 1 FROM orders;DELETE FROM orders;",
])
def test_stacked_statements_rejected(sql):
    r = validate_sql(sql)
    assert not r.ok and "Multiple statements" in r.error


@pytest.mark.parametrize("sql", [
    "SELECT 1 FROM orders -- ; DROP TABLE orders",
    "SELECT 1 FROM orders /* hidden */",
    "SELECT /*! tricky */ 1 FROM orders",
])
def test_comments_rejected(sql):
    r = validate_sql(sql)
    assert not r.ok and "comments" in r.error


def test_load_extension_rejected():
    r = validate_sql("SELECT load_extension('evil.dll') FROM orders")
    assert not r.ok and "load_extension" in r.error


def test_table_valued_function_rejected():
    r = validate_sql("SELECT name FROM pragma_table_info('orders')")
    assert not r.ok and "Table-valued" in r.error


# ---------- table allow-list ----------
def test_unknown_table_lists_allowed_and_suggests():
    r = validate_sql("SELECT * FROM order_item")
    assert not r.ok
    assert "order_item" in r.error and "did you mean 'order_items'" in r.error
    assert all(t in r.error for t in ("orders", "customers"))


def test_sqlite_master_rejected():
    r = validate_sql("SELECT name FROM sqlite_master")
    assert not r.ok and "Unknown table" in r.error


def test_unknown_table_in_join_or_subquery_rejected():
    assert not validate_sql("SELECT * FROM orders o JOIN secrets s ON s.id = o.order_id").ok
    assert not validate_sql("SELECT * FROM orders WHERE order_id IN (SELECT id FROM admin_users)").ok


def test_schema_qualified_table_rejected():
    r = validate_sql("SELECT * FROM main.orders")
    assert not r.ok and "Schema-qualified" in r.error and "orders" in r.error


def test_query_without_table_rejected():
    assert not validate_sql("SELECT 1").ok


# ---------- LIMIT handling ----------
def test_limit_added_when_missing():
    r = validate_sql("SELECT * FROM orders")
    assert r.ok and r.cleaned_sql.upper().endswith(f"LIMIT {SQL_ROW_LIMIT}")


def test_small_limit_kept():
    assert validate_sql("SELECT * FROM orders LIMIT 5").cleaned_sql.upper().endswith("LIMIT 5")


def test_large_limit_capped():
    assert validate_sql("SELECT * FROM orders LIMIT 100000").cleaned_sql.upper().endswith(f"LIMIT {SQL_ROW_LIMIT}")


def test_limit_with_offset_keeps_offset():
    sql = validate_sql("SELECT * FROM orders LIMIT 10 OFFSET 20").cleaned_sql.upper()
    assert "LIMIT 10" in sql and "OFFSET 20" in sql


def test_union_gets_outer_limit():
    r = validate_sql("SELECT order_id FROM orders UNION SELECT order_id FROM order_items")
    assert r.cleaned_sql.upper().endswith(f"LIMIT {SQL_ROW_LIMIT}")


def test_negative_limit_rejected_because_sqlite_treats_it_as_unlimited():
    r = validate_sql("SELECT * FROM orders LIMIT -1")
    assert not r.ok and "LIMIT" in r.error


# ---------- syntax errors ----------
@pytest.mark.parametrize("sql", ["SELEC * FROM orders", "SELECT FROM", "SELECT * FROM orders WHERE (", "not sql at all"])
def test_syntax_errors_rejected_with_message(sql):
    r = validate_sql(sql)
    assert not r.ok and r.error


@pytest.mark.parametrize("sql", ["", "   ", ";", None])
def test_empty_input_rejected(sql):
    assert not validate_sql(sql).ok


def test_overlong_query_rejected():
    r = validate_sql("SELECT " + ", ".join(["1"] * 3000) + " FROM orders")
    assert not r.ok and "too long" in r.error


# ---------- sensitive columns ----------
@pytest.mark.parametrize("sql", [
    "SELECT customer_unique_id FROM customers",
    "SELECT * FROM customers",
    "SELECT c.* FROM customers c",
    "SELECT customer_zip_code_prefix, COUNT(*) FROM customers GROUP BY customer_zip_code_prefix",
    "SELECT geolocation_lat, geolocation_lng FROM geolocation",
    "SELECT * FROM customers WHERE customer_unique_id = 'abc'",
    "SELECT o.order_id, c.customer_unique_id FROM orders o JOIN customers c ON c.customer_id = o.customer_id",
    "SELECT * FROM (SELECT * FROM customers) AS x",                        # inner star reads customers directly
    "SELECT * FROM orders o JOIN customers c ON c.customer_id = o.customer_id",  # star spans the joined table
    "SELECT c.* FROM orders o JOIN customers c ON c.customer_id = o.customer_id",  # c.* is customers
])
def test_sensitive_columns_require_approval(sql):
    r = validate_sql(sql)
    assert r.ok and r.requires_approval, sql


@pytest.mark.parametrize("sql", [
    "SELECT COUNT(DISTINCT customer_unique_id) FROM customers",
    "SELECT customer_state, COUNT(DISTINCT customer_unique_id) AS buyers FROM customers GROUP BY customer_state",
    "SELECT COUNT(*) FROM customers",
    "SELECT * FROM orders",
    "SELECT o.*, c.customer_state FROM orders o JOIN customers c ON c.customer_id = o.customer_id",  # o.* is orders only
    "SELECT customer_state, customer_city FROM customers",
    # a star over a CTE only exposes what the CTE selected, even if customers is joined inside it
    "WITH t AS (SELECT o.order_id, c.customer_state FROM orders o JOIN customers c ON c.customer_id = o.customer_id) "
    "SELECT * FROM t",
])
def test_aggregates_and_non_sensitive_do_not_require_approval(sql):
    r = validate_sql(sql)
    assert r.ok and not r.requires_approval, sql


def test_find_sensitive_names_the_columns():
    assert find_sensitive("SELECT customer_unique_id, geolocation_lat FROM customers, geolocation") == \
        ["customer_unique_id", "geolocation_lat"]
    assert find_sensitive("SELECT COUNT(*) FROM customers") == []


# ---------- config stays in sync with the data ----------
def test_allow_list_matches_database_tables():
    assert ALLOWED_TABLES == set(TABLES)


def test_sensitive_columns_match_schema_notes():
    notes = json.loads(get_settings().schema_notes_path.read_text(encoding="utf-8"))
    declared = set(notes["sensitive_columns"])
    configured = {f"{t}.{c}" for t, cols in SENSITIVE_COLUMNS.items() for c in cols}
    assert declared == configured


# ---------- executor ----------
def test_executor_returns_columns_and_rows(db):
    r = run_sql("SELECT order_status, COUNT(*) AS n FROM orders GROUP BY order_status ORDER BY n DESC", db)
    assert r.ok and r.error is None
    assert r.columns == ["order_status", "n"] and r.rows[0][0] == "delivered"
    assert r.duration_ms >= 0


def test_executor_reports_sql_error_cleanly(db):
    r = run_sql("SELECT no_such_column FROM orders", db)
    assert not r.ok and r.rows == [] and "no such column" in r.error and "no_such_column" in r.error


def test_executor_database_is_read_only(db):
    r = run_sql("DELETE FROM orders", db)
    assert not r.ok and "readonly" in r.error.lower()
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 300


def test_executor_timeout_stops_runaway_query(db):
    runaway = ("WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) "
               "SELECT COUNT(*) FROM c")
    r = run_sql(runaway, db, timeout_s=0.3)
    assert not r.ok and "time limit" in r.error
    assert r.duration_ms < 5000


def test_executor_missing_database(tmp_path):
    r = run_sql("SELECT 1", tmp_path / "nope.db")
    assert not r.ok and "load_olist.py" in r.error


def test_validated_then_executed_end_to_end(db):
    v = validate_sql("SELECT customer_state, COUNT(DISTINCT customer_unique_id) AS buyers FROM customers GROUP BY customer_state")
    assert v.ok and not v.requires_approval
    r = run_sql(v.cleaned_sql, db)
    assert r.ok and sum(row[1] for row in r.rows) > 0
