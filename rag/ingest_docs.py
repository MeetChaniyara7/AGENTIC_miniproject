"""Chunk the policy documents and store them in the Chroma collection "policy_docs".

Run: python -m rag.ingest_docs
"""
from __future__ import annotations

import re
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import get_settings
from rag.store import DOCS_COLLECTION, embed, get_client, rebuild_collection

CHUNK_SIZE, CHUNK_OVERLAP = 500, 80
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
# README.md describes the folder itself; indexing it would pollute policy answers.
SKIP = {"README.md"}


def split_sections(markdown: str) -> list[tuple[str, str]]:
    """Return (heading, body) pairs. Text before the first H2 belongs to the H1 title."""
    sections: list[tuple[str, list[str]]] = [("", [])]
    for line in markdown.splitlines():
        m = HEADING.match(line)
        if m:
            sections.append((m.group(2).strip(), []))
        else:
            sections[-1][1].append(line)
    return [(h, "\n".join(body).strip()) for h, body in sections if "\n".join(body).strip()]


def chunk_document(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    title = next((m.group(2) for line in text.splitlines() if (m := HEADING.match(line)) and m.group(1) == "#"),
                 path.stem)
    splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
    chunks = []
    for heading, body in split_sections(text):
        section = heading or title
        for piece in splitter.split_text(body):
            chunks.append({"text": piece, "source": path.name, "title": title, "section": section})
    return chunks


def ingest_docs(docs_dir: Path | None = None, persist_dir: Path | None = None) -> int:
    docs_dir = docs_dir or get_settings().docs_dir
    chunks = [c for p in sorted(docs_dir.glob("*.md")) if p.name not in SKIP for c in chunk_document(p)]
    if not chunks:
        raise FileNotFoundError(f"No .md documents found in {docs_dir}")
    col = rebuild_collection(get_client(persist_dir), DOCS_COLLECTION)
    # Embed "section + text" so a chunk like a bare table row still carries its topic;
    # the stored document stays the clean chunk text that gets shown to the LLM.
    col.add(
        ids=[f"{c['source']}::{i}" for i, c in enumerate(chunks)],
        documents=[c["text"] for c in chunks],
        embeddings=embed([f"{c['section']}\n{c['text']}" for c in chunks]),
        metadatas=[{"source": c["source"], "title": c["title"], "section": c["section"]} for c in chunks],
    )
    return len(chunks)


if __name__ == "__main__":
    print(f"Indexed {ingest_docs()} chunks into '{DOCS_COLLECTION}'")
