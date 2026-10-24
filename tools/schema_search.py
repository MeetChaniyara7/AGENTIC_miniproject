"""schema_lookup tool: find the tables and example queries relevant to a question."""
from __future__ import annotations

from pathlib import Path

from rag.store import EXAMPLES_COLLECTION, SCHEMA_COLLECTION, get_client, query_collection


def search_schema(query: str, n_tables: int = 3, n_examples: int = 2,
                  persist_dir: Path | str | None = None) -> str:
    """Return a compact prompt-ready string: top tables (with column meanings) and similar example SQL.

    No score threshold here: the SQL Analyst always needs some schema, and the
    database is small enough that the top few tables are the right context.
    """
    # Rank tables by their best-scoring entry (table chunk or any column line).
    hits = query_collection(SCHEMA_COLLECTION, query, 60, persist_dir)
    best: dict[str, float] = {}
    for h in hits:
        tbl = h["metadata"]["table"]
        best[tbl] = max(best.get(tbl, 0.0), h["score"])
    top = sorted(best, key=best.get, reverse=True)[:n_tables]
    table_text = get_client(persist_dir).get_collection(SCHEMA_COLLECTION).get(ids=top)
    text_by_id = dict(zip(table_text["ids"], table_text["documents"]))
    tables = [{"text": text_by_id[t]} for t in top]
    examples = query_collection(EXAMPLES_COLLECTION, query, n_examples, persist_dir)
    parts = ["RELEVANT TABLES:"]
    parts += [t["text"] for t in tables]
    parts.append("\nSIMILAR EXAMPLE QUERIES:")
    for e in examples:
        parts.append(f"Q: {e['text']}\nSQL: {e['metadata']['sql']}")
    return "\n".join(parts)
