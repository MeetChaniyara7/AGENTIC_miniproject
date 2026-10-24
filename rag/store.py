"""Shared Chroma + embedding helpers for the RAG package.

Design notes:
- We compute embeddings ourselves (config.get_embedder) and pass them to Chroma,
  so the embedding model stays swappable in one place and Chroma never
  downloads its own default model.
- Collections use cosine space; score = 1 - cosine distance, so higher is better
  and values land roughly in 0..1 for text.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import chromadb

from config import get_embedder, get_settings

DOCS_COLLECTION = "policy_docs"
SCHEMA_COLLECTION = "schema_notes"
EXAMPLES_COLLECTION = "example_queries"


@lru_cache(maxsize=1)
def _embedder():
    return get_embedder()  # loading the model takes seconds, so do it once per process


def embed(texts: list[str]) -> list[list[float]]:
    return _embedder().encode(texts, normalize_embeddings=True).tolist()


def get_client(persist_dir: Path | str | None = None) -> chromadb.ClientAPI:
    path = Path(persist_dir) if persist_dir else get_settings().chroma_dir
    path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(path))


def rebuild_collection(client: chromadb.ClientAPI, name: str):
    # Ingestion is idempotent: drop and recreate so reruns never duplicate chunks.
    try:
        client.delete_collection(name)
    except Exception:
        pass
    return client.create_collection(name, metadata={"hnsw:space": "cosine"})


def query_collection(name: str, query: str, n: int, persist_dir: Path | str | None = None) -> list[dict]:
    """Return up to n hits as {text, metadata, score}, best first."""
    client = get_client(persist_dir)
    try:
        col = client.get_collection(name)
    except Exception as e:
        raise RuntimeError(f"Collection '{name}' not found. Run: python -m rag.ingest_docs "
                           f"and python -m rag.ingest_schema") from e
    res = col.query(query_embeddings=embed([query]), n_results=min(n, max(col.count(), 1)))
    return [
        {"text": doc, "metadata": meta, "score": round(1.0 - dist, 4)}
        for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0])
    ]
