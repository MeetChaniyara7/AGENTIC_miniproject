"""Run a (validated) SELECT against the Olist SQLite database, read-only, with a timeout.

The connection is opened with mode=ro, so even a query that slipped past the
validator cannot change data. The timeout uses SQLite's progress handler, which
is called every few thousand virtual-machine steps and can abort the query.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import NamedTuple
from urllib.parse import quote

from config import SQL_TIMEOUT_S, get_settings

MAX_ROWS = 1000  # safety net; the validator already caps LIMIT at SQL_ROW_LIMIT


class ExecutionResult(NamedTuple):
    ok: bool
    columns: list[str]
    rows: list[tuple]
    error: str | None      # None when ok; otherwise a message an LLM can act on
    duration_ms: float


def run_sql(sql: str, db_path: Path | str | None = None, timeout_s: float = SQL_TIMEOUT_S) -> ExecutionResult:
    path = Path(db_path) if db_path else get_settings().db_path
    start = time.monotonic()

    def fail(msg: str) -> ExecutionResult:
        return ExecutionResult(False, [], [], msg, round((time.monotonic() - start) * 1000, 1))

    if not path.exists():
        return fail(f"Database file not found at {path}. Build it with: python scripts/load_olist.py")

    con = sqlite3.connect(f"file:{quote(path.as_posix(), safe='/:')}?mode=ro", uri=True)
    deadline = start + timeout_s
    # Returning non-zero from the handler aborts the running statement.
    con.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
    try:
        cur = con.execute(sql)
        rows = cur.fetchmany(MAX_ROWS)
        columns = [d[0] for d in cur.description] if cur.description else []
        return ExecutionResult(True, columns, rows, None, round((time.monotonic() - start) * 1000, 1))
    except sqlite3.OperationalError as e:
        if "interrupted" in str(e).lower():
            return fail(f"Query exceeded the {timeout_s:g}-second time limit and was stopped. "
                        "Add filters (e.g. a date range), aggregate earlier, or avoid joining large tables "
                        "such as geolocation without aggregating first.")
        return fail(f"SQLite error: {e}")
    except sqlite3.Error as e:
        return fail(f"SQLite error: {e}")
    finally:
        con.close()
