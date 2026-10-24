"""Graph tests with a scripted fake LLM: no network, no vector store, real validator and SQLite."""
import json
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from graph import edges
from graph.build_graph import build_graph
from graph.nodes import Deps
from graph.run import ask
from graph.state import MAX_RETRIES
from graph.trace import write_trace
from scripts.load_olist import load_all
from tests.olist_fixture import write_csvs
from tools.sql_executor import run_sql

GOOD_SQL = "SELECT COUNT(*) AS orders FROM orders"
SENSITIVE_SQL = "SELECT customer_unique_id FROM customers"


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    d = tmp_path_factory.mktemp("olist")
    write_csvs(d / "raw")
    load_all(d / "raw", d / "olist.db")
    return d / "olist.db"


class FakeLLM:
    """Answers by prompt type. `sqls` are used in order; the last one repeats forever."""

    def __init__(self, route="SQL", sqls=(GOOD_SQL,), rewritten=None, router_raw=None, boom_on=None):
        self.route, self.sqls, self.rewritten, self.router_raw, self.boom_on = route, list(sqls), rewritten, router_raw, boom_on
        self.prompts = {"router": [], "sql": [], "synth": []}

    def invoke(self, prompt):
        if "[[ROUTER]]" in prompt:
            kind = "router"
            q = prompt.split("Current question:\n", 1)[1].split("\n", 1)[0]
            text = self.router_raw or json.dumps({"route": self.route, "rewritten_question": self.rewritten or q,
                                                  "sub_tasks": [{"type": "SQL", "task": q}], "reason": "test route"})
        elif "[[SQL_GEN]]" in prompt:
            kind = "sql"
            text = self.sqls[min(len(self.prompts["sql"]), len(self.sqls) - 1)]
        else:
            kind, text = "synth", "FINAL ANSWER"
        self.prompts[kind].append(prompt)
        if kind == self.boom_on:
            raise RuntimeError("simulated API outage")
        return SimpleNamespace(content=text)


def make(db, llm):
    calls = []

    def run_fn(sql):
        calls.append(sql)
        return run_sql(sql, db)

    deps = Deps(llm=llm,
                docs_fn=lambda q: [{"text": "Late means delivered after estimate.", "source": "delivery_sla.md",
                                    "section": "4", "score": 0.7}],
                schema_fn=lambda q: "RELEVANT TABLES:\nTable orders: one row per order\nSIMILAR EXAMPLE QUERIES:\n",
                run_fn=run_fn)
    return build_graph(deps), calls


def nodes_of(state):
    return [e["node"] for e in state["trace"]]


# ---------------------------------------------------------------- routes
def test_sql_route(db):
    graph, calls = make(db, FakeLLM("SQL"))
    s = ask(graph, "How many orders are there?", "t")
    assert nodes_of(s) == ["router", "retrieve_schema", "generate_sql", "validate_sql", "execute_sql", "synthesize"]
    assert s["answer"] == "FINAL ANSWER" and s["rows"] == [[300]] and len(calls) == 1


def test_docs_route_never_touches_sql(db):
    graph, calls = make(db, FakeLLM("DOCS"))
    s = ask(graph, "What counts as a late delivery?", "t")
    assert nodes_of(s) == ["router", "retrieve_docs", "synthesize"]
    assert calls == [] and s["doc_chunks"][0]["source"] == "delivery_sla.md"


def test_both_route_reads_docs_then_schema_then_sql(db):
    graph, _ = make(db, FakeLLM("BOTH"))
    s = ask(graph, "Is our late rate within target?", "t")
    assert nodes_of(s) == ["router", "retrieve_docs", "retrieve_schema", "generate_sql", "validate_sql",
                           "execute_sql", "synthesize"]


def test_out_of_scope_makes_only_the_router_call(db):
    llm = FakeLLM("OUT_OF_SCOPE")
    graph, calls = make(db, llm)
    s = ask(graph, "Who won the world cup?", "t")
    assert nodes_of(s) == ["router", "out_of_scope"]
    assert len(llm.prompts["sql"]) == 0 and len(llm.prompts["synth"]) == 0 and calls == []
    assert "marketplace" in s["answer"]


def test_invalid_router_json_defaults_to_both(db):
    graph, _ = make(db, FakeLLM(router_raw="I think SQL maybe"))
    s = ask(graph, "anything", "t")
    assert s["route"] == "BOTH" and s["trace"][0]["success"] is False
    assert "synthesize" in nodes_of(s)


# ---------------------------------------------------------------- retry loop
def test_retry_loop_stops_at_three(db):
    llm = FakeLLM("SQL", sqls=["SELECT * FROM nope"])  # always invalid
    graph, calls = make(db, llm)
    s = ask(graph, "q", "t")
    assert len(llm.prompts["sql"]) == MAX_RETRIES + 1 == 4  # first attempt + 3 retries
    assert s["retries"] == 3 and nodes_of(s)[-1] == "fail" and calls == []
    assert "Unknown table" in s["answer"] and s["fail_reason"] == "retries_exhausted"
    assert "synthesize" not in nodes_of(s)


def test_error_feedback_reaches_the_next_generation(db):
    llm = FakeLLM("SQL", sqls=["SELECT * FROM nope", GOOD_SQL])
    graph, _ = make(db, llm)
    s = ask(graph, "q", "t")
    assert s["retries"] == 1 and nodes_of(s)[-1] == "synthesize"
    retry_prompt = llm.prompts["sql"][1]
    assert "SELECT * FROM nope" in retry_prompt and "Unknown table" in retry_prompt
    assert "previous query" not in llm.prompts["sql"][0]


def test_execution_error_is_fed_back_and_recovers(db):
    llm = FakeLLM("SQL", sqls=["SELECT nosuchcolumn FROM orders", GOOD_SQL])
    graph, calls = make(db, llm)
    s = ask(graph, "q", "t")
    assert "no such column" in llm.prompts["sql"][1] and len(calls) == 2 and s["rows"] == [[300]]


def test_empty_result_retries_once_then_answers_honestly(db):
    empty = "SELECT order_id FROM orders WHERE order_status = 'no_such_status'"
    llm = FakeLLM("SQL", sqls=[empty])
    graph, calls = make(db, llm)
    s = ask(graph, "q", "t")
    assert len(calls) == 2 and s["retries"] == 1
    assert nodes_of(s)[-1] == "synthesize" and "returned 0 rows" in llm.prompts["sql"][1]
    assert "(0 rows)" in llm.prompts["synth"][0]


# ---------------------------------------------------------------- human in the loop
def paused(db, sql=SENSITIVE_SQL):
    llm = FakeLLM("SQL", sqls=[sql])
    graph, calls = make(db, llm)
    cfg = {"configurable": {"thread_id": "hitl"}}
    state = ask(graph, "list customers", "hitl")  # no approver -> returns at the interrupt
    return graph, calls, cfg, state


def test_sensitive_query_pauses_before_executing(db):
    _, calls, _, state = paused(db)
    payload = state["__interrupt__"][0].value
    assert payload["type"] == "approval_request" and "customer_unique_id" in payload["sensitive_columns"]
    assert payload["sql"].startswith("SELECT customer_unique_id") and calls == []


def test_approval_resumes_and_executes(db):
    graph, calls, cfg, _ = paused(db)
    s = graph.invoke(Command(resume={"approved": True}), cfg)
    assert nodes_of(s)[-3:] == ["approval", "execute_sql", "synthesize"] and len(calls) == 1 and s["rows"]


def test_rejected_approval_skips_execution(db):
    graph, calls, cfg, _ = paused(db)
    s = graph.invoke(Command(resume={"approved": False}), cfg)
    assert "execute_sql" not in nodes_of(s) and nodes_of(s)[-2:] == ["approval", "fail"]
    assert calls == [] and "approval was declined" in s["answer"] and s["rows"] == []


def test_edited_sql_is_revalidated_and_used(db):
    graph, calls, cfg, _ = paused(db)
    edit = "SELECT customer_state, COUNT(DISTINCT customer_unique_id) AS buyers FROM customers GROUP BY customer_state"
    s = graph.invoke(Command(resume={"approved": True, "sql": edit}), cfg)
    assert len(calls) == 1 and "GROUP BY" in calls[0] and s["columns"] == ["customer_state", "buyers"]


def test_edited_sql_that_fails_validation_is_not_run(db):
    graph, calls, cfg, _ = paused(db)
    s = graph.invoke(Command(resume={"approved": True, "sql": "DROP TABLE customers"}), cfg)
    assert calls == [] and nodes_of(s)[-1] == "fail" and "failed validation" in s["answer"]


def test_non_sensitive_query_never_asks(db):
    graph, _ = make(db, FakeLLM("SQL"))
    assert "approval" not in nodes_of(ask(graph, "q", "t"))


# ---------------------------------------------------------------- memory
def test_follow_up_uses_thread_memory(db):
    llm = FakeLLM("SQL", rewritten="How many orders were placed in 2017?")
    graph, _ = make(db, llm)
    ask(graph, "How many orders were placed in 2017?", "t1")
    s2 = ask(graph, "and in 2018?", "t1")
    second_router = llm.prompts["router"][1]
    assert "How many orders were placed in 2017?" in second_router and "FINAL ANSWER" in second_router
    assert s2["standalone_question"] == "How many orders were placed in 2017?"
    assert "How many orders were placed in 2017?" in llm.prompts["sql"][1]  # rewritten question reaches SQL gen
    assert len(s2["messages"]) == 4  # 2 questions + 2 answers kept in the checkpoint


def test_threads_do_not_share_memory(db):
    llm = FakeLLM("SQL")
    graph, _ = make(db, llm)
    ask(graph, "first question", "A")
    ask(graph, "other thread", "B")
    assert "first question" not in llm.prompts["router"][1] and "(none)" in llm.prompts["router"][1]


def test_graph_uses_memory_saver(db):
    graph, _ = make(db, FakeLLM())
    assert isinstance(graph.checkpointer, MemorySaver)


# ---------------------------------------------------------------- tracing and failures
def test_trace_entries_are_complete_and_reset_each_turn(db):
    graph, _ = make(db, FakeLLM("SQL"))
    s1 = ask(graph, "one", "t")
    s2 = ask(graph, "two", "t")
    assert len(s2["trace"]) == len(s1["trace"]) == 6
    for e in s2["trace"]:
        assert {"node", "summary", "success", "duration_ms", "llm_calls", "input", "output"} <= set(e)
        assert e["duration_ms"] >= 0 and isinstance(e["success"], bool)
    assert sum(e["llm_calls"] for e in s2["trace"]) == 3  # router + sql + synthesize


def test_node_crash_ends_in_fail_not_exception(db):
    graph, _ = make(db, FakeLLM("SQL", boom_on="sql"))
    s = ask(graph, "q", "t")
    assert nodes_of(s)[-1] == "fail" and "simulated API outage" in s["fail_reason"]
    assert any(not e["success"] for e in s["trace"])
    assert "went wrong" in s["answer"]


def test_write_trace_creates_json(db, tmp_path):
    graph, _ = make(db, FakeLLM("SQL"))
    s = ask(graph, "q", "t")
    path = write_trace(s, "t", tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["totals"]["llm_calls"] == 3 and data["totals"]["success"] and len(data["trace"]) == 6


# ---------------------------------------------------------------- edges as pure functions
@pytest.mark.parametrize("state,expected", [
    ({"validation_error": "x", "retries": 0}, "generate_sql"),
    ({"validation_error": "x", "retries": 2}, "generate_sql"),
    ({"validation_error": "x", "retries": 3}, "fail"),
    ({"requires_approval": True, "approved": None}, "approval"),
    ({"requires_approval": True, "approved": True}, "execute_sql"),
    ({}, "execute_sql"),
    ({"fail_reason": "boom"}, "fail"),
])
def test_after_validate(state, expected):
    assert edges.after_validate(state) == expected


@pytest.mark.parametrize("state,expected", [
    ({"exec_error": "e", "retries": 1}, "generate_sql"),
    ({"exec_error": "e", "retries": 3}, "fail"),
    ({"exec_error": None, "rows": []}, "synthesize"),
])
def test_after_execute(state, expected):
    assert edges.after_execute(state) == expected
