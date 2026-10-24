"""UI tests: Streamlit's AppTest runs the real app.py headlessly against a graph built on a fake LLM."""
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from graph import ui_support as ui
from scripts.load_olist import load_all
from tests.olist_fixture import write_csvs
from tests.test_graph import FakeLLM, SENSITIVE_SQL, make

APP = Path(__file__).resolve().parents[1] / "app.py"


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    d = tmp_path_factory.mktemp("olist")
    write_csvs(d / "raw")
    load_all(d / "raw", d / "olist.db")
    return d / "olist.db"


@pytest.fixture
def app(db, monkeypatch, tmp_path):
    """Factory: app(llm) -> AppTest with the graph (fake LLM, fixture DB) patched in."""
    def start(llm):
        graph, _ = make(db, llm)
        monkeypatch.setattr("graph.build_graph.build_graph", lambda *a, **k: graph)
        monkeypatch.setattr("config.ROOT", tmp_path)  # traces from tests go to a temp folder
        st.cache_resource.clear()
        at = AppTest.from_file(str(APP), default_timeout=30)
        at.run()
        return at
    return start


def ask(at, text):
    at.chat_input[0].set_value(text).run()
    return at


def texts(elements):
    return " ".join(str(e.value) for e in elements)


# ---------------------------------------------------------------- page structure
def test_home_screen_has_sidebar_and_examples(app):
    at = app(FakeLLM())
    assert not at.exception
    assert at.title[0].value.endswith("Hybrid Analyst")
    labels = [b.label for b in at.sidebar.button]
    assert "New conversation" in labels and sum(l.startswith(("Data", "Policy", "Flagship")) for l in labels) >= 3
    assert "Model" in texts(at.sidebar.markdown)


def test_answer_shows_answer_sql_table_and_trace(app):
    at = ask(app(FakeLLM("SQL")), "How many orders are there?")
    assert not at.exception
    assert "FINAL ANSWER" in texts(at.markdown)
    assert any("SELECT" in c.value for c in at.code)                       # (b) SQL
    assert len(at.dataframe) == 2                                          # (c) result table + trace table
    labels = [e.label for e in at.expander]
    assert any(l.startswith("Agent trace") and "route SQL" in l and "0 retries" in l for l in labels)  # (e)


def test_docs_answer_shows_citations(app):
    at = ask(app(FakeLLM("DOCS")), "What counts as a late delivery?")
    assert "delivery_sla.md" in texts(at.markdown)
    assert not any("SELECT" in c.value for c in at.code)


# ---------------------------------------------------------------- approval flow
def test_approval_prompt_then_approve_runs_query(app):
    at = ask(app(FakeLLM("SQL", sqls=[SENSITIVE_SQL])), "list customers")
    assert "Approval needed" in texts(at.warning)
    assert any("customer_unique_id" in c.value for c in at.code)
    assert at.chat_input[0].disabled
    assert [b.label for b in at.button if b.key in ("approve", "reject")] == ["Approve", "Reject"]
    at.button(key="approve").click().run()
    assert not at.exception and not at.warning
    assert "FINAL ANSWER" in texts(at.markdown) and len(at.dataframe) == 2
    assert not at.chat_input[0].disabled


def test_reject_does_not_run_query(app):
    at = ask(app(FakeLLM("SQL", sqls=[SENSITIVE_SQL])), "list customers")
    at.button(key="reject").click().run()
    assert "approval was declined" in texts(at.info)
    assert len(at.dataframe) == 1  # only the trace table, no results


# ---------------------------------------------------------------- friendly messages
def test_out_of_scope_message(app):
    at = ask(app(FakeLLM("OUT_OF_SCOPE")), "capital of France?")
    assert "outside what I can help with" in texts(at.info)


def test_empty_result_message(app):
    sql = "SELECT order_id FROM orders WHERE order_status = 'no_such_status'"
    at = ask(app(FakeLLM("SQL", sqls=[sql])), "q")
    assert "returned no rows" in texts(at.info)


def test_api_error_is_friendly_not_a_traceback(app):
    at = ask(app(FakeLLM("SQL", boom_on="sql")), "q")
    assert not at.exception
    assert "AI service" in texts(at.error) and "simulated API outage" not in texts(at.error)


def test_new_conversation_clears_history(app):
    at = ask(app(FakeLLM("SQL")), "q")
    first_thread = at.session_state.thread_id
    at.sidebar.button[[b.label for b in at.sidebar.button].index("New conversation")].click().run()
    assert at.session_state.turns == [] and at.session_state.thread_id != first_thread


def test_example_button_asks_the_question(app):
    at = app(FakeLLM("SQL"))
    idx = next(i for i, b in enumerate(at.sidebar.button) if b.label.startswith("Data:"))
    at.sidebar.button[idx].click().run()
    assert len(at.session_state.turns) == 1 and at.session_state.turns[0]["question"].startswith("How many orders")


# ---------------------------------------------------------------- display logic (no Streamlit)
@pytest.mark.parametrize("state,kind", [
    ({"route": "SQL", "columns": ["a"], "rows": [[1]]}, ui.ANSWER),
    ({"route": "DOCS"}, ui.ANSWER),
    ({"route": "SQL", "columns": ["a"], "rows": []}, ui.EMPTY),
    ({"route": "OUT_OF_SCOPE"}, ui.OUT_OF_SCOPE),
    ({"fail_reason": "approval_declined"}, ui.DECLINED),
    ({"fail_reason": "retries_exhausted"}, ui.SQL_FAILED),
    ({"fail_reason": "generate_sql crashed: GoogleAPIError: 504"}, ui.SERVICE_ERROR),
    ({"fail_reason": "something else"}, ui.OTHER_ERROR),
])
def test_classify(state, kind):
    assert ui.classify(state) == kind


def test_friendly_messages_distinguish_rate_limit_and_timeout():
    rate = ui.friendly_message(ui.SERVICE_ERROR, {"fail_reason": "router crashed: ClientError: 429 RESOURCE_EXHAUSTED"})
    slow = ui.friendly_message(ui.SERVICE_ERROR, {"fail_reason": "router crashed: GoogleAPIError: 504 DEADLINE_EXCEEDED"})
    assert "limit" in rate and "too long" in slow


def test_citations_are_unique_and_sorted():
    chunks = [{"source": "a.md", "section": "S1", "score": 0.5, "text": ""},
              {"source": "a.md", "section": "S1", "score": 0.4, "text": ""},
              {"source": "b.md", "section": "S2", "score": 0.7, "text": ""}]
    assert [c["source"] for c in ui.citations({"doc_chunks": chunks})] == ["b.md", "a.md"]
