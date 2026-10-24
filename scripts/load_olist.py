"""Load the Olist CSVs from data/raw/ into data/olist.db (SQLite).

Usage: python scripts/load_olist.py [--raw-dir data/raw] [--db data/olist.db]

Design notes:
- Standard library only (csv + sqlite3); no pandas needed for ~1.5M rows.
- Column names stay exactly as in the Kaggle files (including the original
  "lenght" typos) so public Olist examples still apply.
- Timestamps are stored as TEXT 'YYYY-MM-DD HH:MM:SS', which SQLite's
  strftime/julianday/date functions read directly and which sorts correctly.
- Empty CSV cells become NULL (e.g. undelivered orders have no delivery date).
"""
from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import get_settings  # noqa: E402

# table -> (csv file, DDL columns, indexes)
TABLES = {
    "customers": (
        "olist_customers_dataset.csv",
        """customer_id TEXT PRIMARY KEY, customer_unique_id TEXT, customer_zip_code_prefix INTEGER,
           customer_city TEXT, customer_state TEXT""",
        ["customer_unique_id", "customer_zip_code_prefix", "customer_state"],
    ),
    "geolocation": (
        "olist_geolocation_dataset.csv",
        """geolocation_zip_code_prefix INTEGER, geolocation_lat REAL, geolocation_lng REAL,
           geolocation_city TEXT, geolocation_state TEXT""",
        ["geolocation_zip_code_prefix"],
    ),
    "orders": (
        "olist_orders_dataset.csv",
        """order_id TEXT PRIMARY KEY, customer_id TEXT, order_status TEXT, order_purchase_timestamp TEXT,
           order_approved_at TEXT, order_delivered_carrier_date TEXT, order_delivered_customer_date TEXT,
           order_estimated_delivery_date TEXT""",
        ["customer_id", "order_status", "order_purchase_timestamp"],
    ),
    "order_items": (
        "olist_order_items_dataset.csv",
        """order_id TEXT, order_item_id INTEGER, product_id TEXT, seller_id TEXT, shipping_limit_date TEXT,
           price REAL, freight_value REAL, PRIMARY KEY (order_id, order_item_id)""",
        ["product_id", "seller_id"],
    ),
    "order_payments": (
        "olist_order_payments_dataset.csv",
        """order_id TEXT, payment_sequential INTEGER, payment_type TEXT, payment_installments INTEGER,
           payment_value REAL, PRIMARY KEY (order_id, payment_sequential)""",
        ["payment_type"],
    ),
    # review_id is NOT unique in the source data, so no primary key here.
    "order_reviews": (
        "olist_order_reviews_dataset.csv",
        """review_id TEXT, order_id TEXT, review_score INTEGER, review_comment_title TEXT,
           review_comment_message TEXT, review_creation_date TEXT, review_answer_timestamp TEXT""",
        ["review_id", "order_id", "review_score"],
    ),
    "products": (
        "olist_products_dataset.csv",
        """product_id TEXT PRIMARY KEY, product_category_name TEXT, product_name_lenght INTEGER,
           product_description_lenght INTEGER, product_photos_qty INTEGER, product_weight_g INTEGER,
           product_length_cm INTEGER, product_height_cm INTEGER, product_width_cm INTEGER""",
        ["product_category_name"],
    ),
    "sellers": (
        "olist_sellers_dataset.csv",
        """seller_id TEXT PRIMARY KEY, seller_zip_code_prefix INTEGER, seller_city TEXT, seller_state TEXT""",
        ["seller_state"],
    ),
    "product_category_translation": (
        "product_category_name_translation.csv",
        "product_category_name TEXT PRIMARY KEY, product_category_name_english TEXT",
        [],
    ),
}


def _clean(value: str):
    return None if value == "" else value


def load_table(con: sqlite3.Connection, name: str, csv_path: Path, ddl: str, indexes: list[str]) -> int:
    con.execute(f"DROP TABLE IF EXISTS {name}")
    con.execute(f"CREATE TABLE {name} ({ddl})")
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        placeholders = ",".join("?" * len(header))
        con.executemany(
            f"INSERT OR IGNORE INTO {name} ({','.join(header)}) VALUES ({placeholders})",
            ([_clean(v) for v in row] for row in reader),
        )
    for col in indexes:
        con.execute(f"CREATE INDEX idx_{name}_{col} ON {name}({col})")
    return con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]


def load_all(raw_dir: Path, db_path: Path) -> dict[str, int]:
    missing = [csv_name for csv_name, _, _ in TABLES.values() if not (raw_dir / csv_name).exists()]
    if missing:
        raise FileNotFoundError(f"Missing CSV files in {raw_dir}: {', '.join(missing)}")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    try:
        counts = {name: load_table(con, name, raw_dir / csv_name, ddl, idx)
                  for name, (csv_name, ddl, idx) in TABLES.items()}
        con.commit()
    finally:
        con.close()
    return counts


if __name__ == "__main__":
    s = get_settings()
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", type=Path, default=s.raw_dir)
    ap.add_argument("--db", type=Path, default=s.db_path)
    args = ap.parse_args()
    try:
        result = load_all(args.raw_dir, args.db)
    except FileNotFoundError as e:
        sys.exit(f"ERROR: {e}")
    print(f"Wrote {args.db}")
    for table, n in result.items():
        print(f"  {table:<30}{n:>10,}")
