"""doc_search tool: semantic search over the policy documents."""
from __future__ import annotations

from pathlib import Path

from rag.store import DOCS_COLLECTION, query_collection

# Cosine-similarity floor below which a chunk is treated as "not about this".
# Chosen from measured scores (see tests/test_rag.py and the Phase 2 report),
# not guessed: relevant questions score well above it, off-topic ones below.
DEFAULT_MIN_SCORE = 0.30


def retrieve_docs(query: str, k: int = 4, min_score: float = DEFAULT_MIN_SCORE,
                  persist_dir: Path | str | None = None) -> list[dict]:
    """Return up to k chunks as {text, source, section, score}, best first.

    Returns an empty list when nothing reaches min_score, so the agent can tell
    "documents have no answer" apart from "documents say X".
    """
    hits = query_collection(DOCS_COLLECTION, query, k, persist_dir)
    return [
        {"text": h["text"], "source": h["metadata"]["source"], "section": h["metadata"]["section"],
         "score": h["score"]}
        for h in hits if h["score"] >= min_score
    ]
