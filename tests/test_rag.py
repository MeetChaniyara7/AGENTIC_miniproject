import pytest

from rag.ingest_docs import CHUNK_SIZE, ingest_docs
from rag.ingest_schema import ingest_schema
from rag.store import DOCS_COLLECTION, EXAMPLES_COLLECTION, SCHEMA_COLLECTION, get_client
from tools.doc_retriever import retrieve_docs
from tools.schema_search import search_schema


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    d = tmp_path_factory.mktemp("chroma")
    n_chunks = ingest_docs(persist_dir=d)
    n_tables, n_examples = ingest_schema(persist_dir=d)
    return d, n_chunks, n_tables, n_examples


def test_collections_created(store):
    d, n_chunks, n_tables, n_examples = store
    client = get_client(d)
    assert client.get_collection(DOCS_COLLECTION).count() == n_chunks > 40
    schema = client.get_collection(SCHEMA_COLLECTION).get(where={"kind": "table"})
    assert len(schema["ids"]) == n_tables == 9  # one table chunk per table (column entries are extra)
    assert client.get_collection(EXAMPLES_COLLECTION).count() == n_examples == 12


def test_chunks_have_heading_metadata_and_respect_size(store):
    got = get_client(store[0]).get_collection(DOCS_COLLECTION).get()
    assert all(m["section"] and m["source"].endswith(".md") for m in got["metadatas"])
    assert max(len(t) for t in got["documents"]) <= CHUNK_SIZE
    assert "README.md" not in {m["source"] for m in got["metadatas"]}


def test_reingest_is_idempotent(store):
    d, n_chunks, *_ = store
    assert ingest_docs(persist_dir=d) == n_chunks
    assert get_client(d).get_collection(DOCS_COLLECTION).count() == n_chunks


@pytest.mark.parametrize("question,source", [
    ("How long does a credit card refund take?", "refund_policy.md"),
    ("What compensation do customers get when delivery is 10 days late?", "refund_policy.md"),
    ("What counts as a late delivery?", "delivery_sla.md"),
    ("What commission does Olist charge sellers?", "seller_guidelines.md"),
    ("What does a review score of 2 mean?", "review_moderation.md"),
    ("What is the difference between customer_id and customer_unique_id?", "data_dictionary.md"),
    ("How is cancellation rate calculated?", "metrics_glossary.md"),
    ("How is average order value defined?", "metrics_glossary.md"),
])
def test_known_questions_retrieve_expected_source(store, question, source):
    hits = retrieve_docs(question, k=4, persist_dir=store[0])
    assert source in {h["source"] for h in hits}
    assert all({"text", "source", "section", "score"} <= set(h) for h in hits)


@pytest.mark.parametrize("question", [
    "What is the capital of France?",
    "How do I bake a chocolate cake?",
    "Explain quantum entanglement",
])
def test_unrelated_question_returns_nothing(store, question):
    assert retrieve_docs(question, persist_dir=store[0]) == []


def test_min_score_filters_results(store):
    q = "How long does a credit card refund take?"
    assert retrieve_docs(q, min_score=0.0, persist_dir=store[0])
    assert retrieve_docs(q, min_score=0.99, persist_dir=store[0]) == []


def test_schema_search_returns_tables_and_two_examples(store):
    out = search_schema("late delivery rate by customer state", persist_dir=store[0])
    assert "Table orders" in out and "Table customers" in out
    assert out.count("SQL:") == 2


def test_schema_search_finds_reviews_table(store):
    assert "Table order_reviews" in search_schema("average review score per month", persist_dir=store[0])


def test_missing_collection_gives_clear_error(tmp_path):
    with pytest.raises(RuntimeError, match="rag.ingest_docs"):
        retrieve_docs("anything", persist_dir=tmp_path)
