"""Single place to choose the LLM and embedding model.

Everything else in the project calls get_chat_model() / get_embedder(); swapping
providers means editing .env, not code. Provider packages are imported lazily so
the data scripts and tests run without them installed.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# --- SQL safety policy (used by tools/sql_validator.py and tools/sql_executor.py) ---
# Allow-list instead of block-list: anything not named here (sqlite_master, other
# attached databases, new tables) is rejected by default.
ALLOWED_TABLES = frozenset({
    "customers", "geolocation", "orders", "order_items", "order_payments",
    "order_reviews", "products", "sellers", "product_category_translation",
})
# Columns that can identify a person or home area (see data/schema_notes.json).
# Using them outside an aggregate needs human approval.
SENSITIVE_COLUMNS = {
    "customers": frozenset({"customer_unique_id", "customer_zip_code_prefix"}),
    "geolocation": frozenset({"geolocation_lat", "geolocation_lng"}),
}
SQL_ROW_LIMIT = 200       # default and maximum LIMIT
SQL_TIMEOUT_S = 10.0      # wall-clock budget per query
LLM_TIMEOUT_S = 45        # fail fast: a hung provider call becomes a traced error, not a frozen app
LLM_MAX_RETRIES = 1


def _load_dotenv(path: Path) -> None:
    # Tiny parser instead of python-dotenv: avoids a dependency not on the approved list.
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


@dataclass(frozen=True)
class Settings:
    provider: str
    gemini_model: str
    groq_model: str
    ollama_model: str
    ollama_base_url: str
    embedding_model: str
    raw_dir: Path
    db_path: Path
    docs_dir: Path
    schema_notes_path: Path
    example_queries_path: Path
    chroma_dir: Path
    trace_dir: Path


def get_settings() -> Settings:
    _load_dotenv(ROOT / ".env")
    env = os.environ.get
    data = ROOT / "data"
    return Settings(
        provider=env("LLM_PROVIDER", "gemini").lower(),
        gemini_model=env("GEMINI_MODEL", "gemini-3.8-flash"),
        groq_model=env("GROQ_MODEL", "openai/gpt-oss-120b"),
        ollama_model=env("OLLAMA_MODEL", "qwen2.5:7b"),
        ollama_base_url=env("OLLAMA_BASE_URL", "http://localhost:11434"),
        embedding_model=env("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"),
        raw_dir=data / "raw",
        db_path=data / "olist.db",
        docs_dir=data / "docs",
        schema_notes_path=data / "schema_notes.json",
        example_queries_path=data / "example_queries.json",
        chroma_dir=ROOT / "chroma_db",
        trace_dir=ROOT / "traces",
    )


def get_chat_model(temperature: float = 0.0):
    """Return a LangChain chat model for the configured provider."""
    s = get_settings()
    if s.provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(model=s.gemini_model, temperature=temperature,
                                      timeout=LLM_TIMEOUT_S, max_retries=LLM_MAX_RETRIES)
    if s.provider == "groq":
        from langchain_groq import ChatGroq

        return ChatGroq(model=s.groq_model, temperature=temperature, timeout=LLM_TIMEOUT_S, max_retries=LLM_MAX_RETRIES)
    if s.provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(model=s.ollama_model, base_url=s.ollama_base_url, temperature=temperature)
    raise ValueError(f"Unknown LLM_PROVIDER '{s.provider}' (use gemini, groq or ollama)")


def get_embedder():
    """Return a local sentence-transformers model (free, no API key)."""
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(get_settings().embedding_model)
