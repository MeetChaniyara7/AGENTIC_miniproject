"""Embed schema notes (one chunk per table, plus one per column for ranking) and example queries.

Creates two Chroma collections: "schema_notes" and "example_queries".
Run: python -m rag.ingest_schema
"""
from __future__ import annotations

import json
from pathlib import Path

from config import get_settings
from rag.store import EXAMPLES_COLLECTION, SCHEMA_COLLECTION, embed, get_client, rebuild_collection


def table_chunk(name: str, info: dict) -> str:
    lines = [f"Table {name}: {info['description']}"]
    for col, meta in info["columns"].items():
        flag = " [SENSITIVE: aggregate only]" if meta.get("sensitive") else ""
        lines.append(f"- {col}: {meta['meaning']}{flag}")
    return "\n".join(lines)


def ingest_schema(notes_path: Path | None = None, examples_path: Path | None = None,
                  persist_dir: Path | None = None) -> tuple[int, int]:
    s = get_settings()
    notes = json.loads((notes_path or s.schema_notes_path).read_text(encoding="utf-8"))["tables"]
    examples = json.loads((examples_path or s.example_queries_path).read_text(encoding="utf-8"))
    client = get_client(persist_dir)

    # Two kinds of entries share the collection (metadata "kind"):
    #  - "table": the full table description + column list, returned to the SQL Analyst
    #  - "column": one line per column, used only to rank tables. A long table chunk
    #    scores poorly against a short question ("... by customer state" never matched
    #    the customers table), so tables are ranked by their best-matching column too.
    tables = list(notes)
    ids, docs, metas = [], [], []
    for t_name in tables:
        ids.append(t_name)
        docs.append(table_chunk(t_name, notes[t_name]))
        metas.append({"kind": "table", "table": t_name})
        for col, meta in notes[t_name]["columns"].items():
            ids.append(f"{t_name}.{col}")
            docs.append(f"{t_name}.{col}: {meta['meaning']}")
            metas.append({"kind": "column", "table": t_name})
    col = rebuild_collection(client, SCHEMA_COLLECTION)
    col.add(ids=ids, documents=docs, embeddings=embed(docs), metadatas=metas)

    # Embed the question only: users ask questions, not SQL, so question-to-question
    # similarity is what finds a good few-shot example. The SQL rides along as metadata.
    qs = [e["question"] for e in examples]
    col = rebuild_collection(client, EXAMPLES_COLLECTION)
    col.add(
        ids=[f"example-{e['id']}" for e in examples],
        documents=qs,
        embeddings=embed(qs),
        metadatas=[{"sql": e["sql"], "example_id": e["id"]} for e in examples],
    )
    return len(tables), len(examples)


if __name__ == "__main__":
    t, e = ingest_schema()
    print(f"Indexed {t} tables into '{SCHEMA_COLLECTION}' and {e} examples into '{EXAMPLES_COLLECTION}'")
