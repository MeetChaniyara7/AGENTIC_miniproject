"""Run every query in data/example_queries.json against the database.

Usage: python scripts/verify_examples.py [--db data/olist.db]
Exits non-zero if any query fails to execute. Row counts are printed so empty
results (usually a wrong filter) are visible.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import get_settings  # noqa: E402


def verify(db_path: Path, queries_path: Path) -> list[tuple[int, bool, str]]:
    queries = json.loads(queries_path.read_text(encoding="utf-8"))
    con = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)  # read-only: queries must never write
    results = []
    for q in queries:
        try:
            rows = con.execute(q["sql"]).fetchall()
            results.append((q["id"], True, f"{len(rows)} rows"))
        except sqlite3.Error as e:
            results.append((q["id"], False, str(e)))
    con.close()
    return results


if __name__ == "__main__":
    s = get_settings()
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=s.db_path)
    args = ap.parse_args()
    if not args.db.exists():
        sys.exit(f"ERROR: {args.db} not found. Run scripts/load_olist.py first.")
    out = verify(args.db, s.example_queries_path)
    for qid, ok, msg in out:
        print(f"Q{qid:<3}{'OK  ' if ok else 'FAIL'} {msg}")
    sys.exit(0 if all(ok for _, ok, _ in out) else 1)
