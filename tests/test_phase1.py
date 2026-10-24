import json
import sqlite3

import pytest

from config import get_settings
from scripts.load_olist import TABLES, load_all
from scripts.verify_examples import verify
from tests.olist_fixture import write_csvs


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    d = tmp_path_factory.mktemp("olist")
    write_csvs(d / "raw")
    load_all(d / "raw", d / "olist.db")
    return d / "olist.db"


def test_loader_creates_all_tables(db):
    con = sqlite3.connect(db)
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert names == set(TABLES)
    assert con.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 300


def test_empty_cells_become_null(db):
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM orders WHERE order_status != 'delivered' "
                       "AND order_delivered_customer_date IS NULL").fetchone()[0] > 0
    assert con.execute("SELECT COUNT(*) FROM orders WHERE order_delivered_customer_date = ''").fetchone()[0] == 0


def test_missing_csv_reports_filenames(tmp_path):
    with pytest.raises(FileNotFoundError, match="olist_orders_dataset.csv"):
        load_all(tmp_path, tmp_path / "x.db")


def test_all_example_queries_execute(db):
    results = verify(db, get_settings().example_queries_path)
    assert len(results) == 12
    assert all(ok for _, ok, _ in results), [r for r in results if not r[1]]


def test_schema_notes_cover_every_table_and_column(db):
    notes = json.loads(get_settings().schema_notes_path.read_text(encoding="utf-8"))["tables"]
    con = sqlite3.connect(db)
    for table in TABLES:
        cols = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        assert set(notes[table]["columns"]) == cols, table


def test_policy_docs_exist_with_length():
    docs = get_settings().docs_dir
    names = ["refund_policy", "delivery_sla", "seller_guidelines", "review_moderation",
             "data_dictionary", "metrics_glossary"]
    for n in names:
        words = len((docs / f"{n}.md").read_text(encoding="utf-8").split())
        assert 400 <= words <= 700, (n, words)
    assert "synthetic" in (docs / "README.md").read_text(encoding="utf-8").lower()


def test_unknown_provider_rejected(monkeypatch):
    import config
    monkeypatch.setenv("LLM_PROVIDER", "nope")
    with pytest.raises(ValueError):
        config.get_chat_model()
