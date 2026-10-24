"""Baseline for comparison: a single-prompt text-to-SQL.

Deliberately has none of the agent's machinery: the FULL schema is pasted into one prompt, there is
no retrieval, no example queries, no document context, no validation and no retry. The generated
text goes straight to the (read-only) SQLite connection. One LLM call per question.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from graph.nodes import content_text, extract_sql
from tools.sql_executor import run_sql

PROMPT = """You are an expert SQLite analyst. Here is the full database schema:

{schema}

Write one SQLite query that answers this question:
{question}

Return only the SQL query."""


def full_schema(db_path: Path) -> str:
    con = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)
    try:
        return "\n".join(r[0] + ";" for r in con.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND sql IS NOT NULL ORDER BY name"))
    finally:
        con.close()


def run_baseline(llm, question: str, schema: str, db_path: Path) -> dict:
    """One question through the baseline. Never raises: failures are recorded."""
    start = time.perf_counter()
    out = {"sql": "", "columns": [], "rows": [], "error": None, "llm_calls": 1}
    try:
        out["sql"] = extract_sql(content_text(llm.invoke(PROMPT.format(schema=schema, question=question))))
        res = run_sql(out["sql"], db_path)
        out.update(columns=res.columns, rows=[list(r) for r in res.rows], error=res.error)
    except Exception as e:  # noqa: BLE001 - provider errors are results, not crashes
        out["error"] = f"{type(e).__name__}: {e}"
    out["latency_ms"] = round((time.perf_counter() - start) * 1000, 1)
    out["exec_ok"] = out["error"] is None
    return out
