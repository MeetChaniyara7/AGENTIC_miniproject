"""Tests for the evaluation harness itself. Rows fabricated here only check formulas; they are never reported."""
import itertools
import json
import re
from collections import Counter
from types import SimpleNamespace

import pytest

from config import get_settings
from evaluation import report
from evaluation.baseline import PROMPT, full_schema, run_baseline
from evaluation.llm_cache import CachedLLM
from evaluation.run_eval import run_question
from evaluation.scoring import judge, missing_keywords, results_match, retrieval_hit
from scripts.load_olist import TABLES, load_all
from tests.olist_fixture import write_csvs
from tests.test_graph import GOOD_SQL, SENSITIVE_SQL, FakeLLM, make
from tools.sql_executor import run_sql

TEST_SET = json.loads((get_settings().db_path.parent.parent / "evaluation" / "test_set.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    d = tmp_path_factory.mktemp("olist")
    write_csvs(d / "raw")
    load_all(d / "raw", d / "olist.db")
    return d / "olist.db"


# ---------------------------------------------------------------- the test set itself
def test_test_set_has_required_shape():
    assert Counter(i["category"] for i in TEST_SET) == {"sql": 10, "docs": 8, "hybrid": 8, "safety": 4}
    assert len({i["id"] for i in TEST_SET}) == 30
    for i in TEST_SET:
        assert i["question"].strip() and i["id"]
        if i["category"] in ("sql", "hybrid"):
            assert i["reference_sql"].lstrip().upper().startswith("SELECT")
        if i["category"] in ("docs", "hybrid"):
            assert i["reference_source"] and i["must_contain"]
        if i["category"] == "safety":
            assert i["expect"] == "blocked" and i["subtype"] in {"injection", "write_request", "out_of_scope", "pii"}


@pytest.mark.skipif(not get_settings().db_path.exists(), reason="needs the real olist.db")
def test_every_reference_sql_runs_on_the_real_database_and_returns_data():
    for i in TEST_SET:
        if "reference_sql" in i:
            res = run_sql(i["reference_sql"])
            assert res.ok, (i["id"], res.error)
            assert res.rows and res.rows[0][0] is not None, i["id"]


def test_expected_keywords_really_appear_in_the_reference_document():
    for i in TEST_SET:
        if "reference_source" in i:
            doc = (get_settings().docs_dir / i["reference_source"]).read_text(encoding="utf-8")
            assert not missing_keywords(doc, i["must_contain"]), (i["id"], missing_keywords(doc, i["must_contain"]))


def test_test_questions_are_not_copies_of_the_few_shot_examples():
    examples = {e["question"].lower() for e in json.loads(get_settings().example_queries_path.read_text(encoding="utf-8"))}
    assert not {i["question"].lower() for i in TEST_SET} & examples


# ---------------------------------------------------------------- result comparison
@pytest.mark.parametrize("agent,ref,expected", [
    ([(8.11,)], [(8.11,)], True),
    ([(8.1,)], [(8.11,)], True),                               # rounding difference within tolerance
    ([(8.5,)], [(8.11,)], False),
    ([("SP", 3), ("RJ", 2)], [("RJ", 2), ("SP", 3)], True),    # row order ignored
    ([("SP", 3, 99.0)], [("SP", 3)], True),                    # extra column ignored
    ([(99.0, "SP", 3)], [("SP", 3)], True),                    # ... in any position
    ([("SP", 3)], [("SP", 4)], False),
    ([("SP", 3), ("RJ", 2)], [("SP", 3)], False),              # too many rows
    ([("sp",)], [("SP",)], True),                              # case-insensitive strings
    ([], [(1,)], False),
    ([(1, 2)], [(1, 2, 3)], False),                            # fewer columns than the reference
    ([], [], True),
])
def test_results_match(agent, ref, expected):
    assert results_match(agent, ref) is expected


def test_missing_keywords_normalises_formatting_and_alternatives():
    ans = "Late means **7 days** after delivery; compensation is a 10 % voucher."
    assert missing_keywords(ans, ["7 days", "10%", "voucher"]) == []
    assert missing_keywords(ans, ["poor|voucher"]) == []
    assert missing_keywords(ans, ["16%"]) == ["16%"]


def test_retrieval_hit():
    assert retrieval_hit([{"source": "a.md"}, {"source": "b.md"}], "b.md")
    assert not retrieval_hit([{"source": "a.md"}], "b.md") and not retrieval_hit([], None)


# ---------------------------------------------------------------- verdicts
def test_judge_each_category():
    sql_item = {"category": "sql", "reference_sql": "x"}
    assert judge(sql_item, {"sql_match": True, "sql": "s"})[0]
    assert "does not match" in judge(sql_item, {"sql_match": False, "sql": "s"})[1][0]
    assert "no SQL was executed" in judge(sql_item, {"sql_match": False, "sql": ""})[1][0]

    docs_item = {"category": "docs", "reference_source": "a.md", "must_contain": ["x"]}
    assert judge(docs_item, {"retrieval_hit": True, "missing_keywords": []})[0]
    assert not judge(docs_item, {"retrieval_hit": False, "missing_keywords": []})[0]
    assert not judge(docs_item, {"retrieval_hit": True, "missing_keywords": ["x"]})[0]

    hybrid = {"category": "hybrid", "reference_sql": "x", "reference_source": "a.md", "must_contain": []}
    assert judge(hybrid, {"sql_match": True, "sql": "s", "retrieval_hit": True, "missing_keywords": []})[0]
    assert not judge(hybrid, {"sql_match": True, "sql": "s", "retrieval_hit": False, "missing_keywords": []})[0]
    assert not judge(hybrid, {"sql_match": False, "sql": "s", "retrieval_hit": True, "missing_keywords": []})[0]
    assert not judge(sql_item, {"sql_match": True, "sql": "s", "fail_reason": "boom"})[0]

    safety = {"category": "safety"}
    assert judge(safety, {"route": "OUT_OF_SCOPE"})[0] and judge(safety, {"route": "SQL", "fail_reason": "x"})[0]
    assert not judge(safety, {"route": "SQL", "ended_at": "synthesize"})[0]


# ---------------------------------------------------------------- LLM cache
class CountingLLM:
    def __init__(self, behaviours):
        self.behaviours, self.calls = list(behaviours), 0

    def invoke(self, prompt):
        self.calls += 1
        b = self.behaviours.pop(0) if self.behaviours else "ok"
        if isinstance(b, Exception):
            raise b
        return SimpleNamespace(content=b)


def test_cache_serves_repeat_prompts_without_calling_the_model(tmp_path):
    inner = CountingLLM(["first"])
    llm = CachedLLM(inner, tmp_path, "m")
    assert llm.invoke("p").content == "first" and llm.invoke("p").content == "first"
    assert inner.calls == 1 and llm.snapshot()["cache_hits"] == 1 and llm.snapshot()["llm_calls"] == 2
    assert llm.snapshot()["cached_llm_latency_s"] >= 0
    assert CachedLLM(CountingLLM([]), tmp_path, "other-model").invoke("p").content == "ok"  # model id is part of the key


def test_cache_persists_across_instances(tmp_path):
    CachedLLM(CountingLLM(["x"]), tmp_path, "m").invoke("p")
    inner = CountingLLM([])
    assert CachedLLM(inner, tmp_path, "m").invoke("p").content == "x" and inner.calls == 0


def test_rate_limit_is_retried_and_counted_but_other_errors_are_not(tmp_path):
    sleeps = []
    inner = CountingLLM([RuntimeError("429 RESOURCE_EXHAUSTED"), RuntimeError("rate limit"), "finally"])
    llm = CachedLLM(inner, tmp_path, "m", sleep=sleeps.append)
    assert llm.invoke("p").content == "finally" and llm.snapshot()["api_retries"] == 2 and len(sleeps) == 2
    with pytest.raises(ValueError):
        CachedLLM(CountingLLM([ValueError("bad request")]), tmp_path, "m2", sleep=sleeps.append).invoke("q")


def test_errors_are_never_cached(tmp_path):
    inner = CountingLLM([RuntimeError("429"), RuntimeError("429")])
    llm = CachedLLM(inner, tmp_path, "m", max_api_retries=1, sleep=lambda s: None)
    with pytest.raises(RuntimeError):
        llm.invoke("p")
    assert not list(tmp_path.glob("*.json"))


# ---------------------------------------------------------------- baseline
def test_baseline_prompt_has_full_schema_and_nothing_else(db):
    schema = full_schema(db)
    assert all(f"CREATE TABLE {t} " in schema for t in TABLES)
    assert "{schema}" in PROMPT and "{question}" in PROMPT
    assert "example" not in PROMPT.lower() and "document" not in PROMPT.lower()


def test_baseline_runs_sql_without_validation_and_records_errors(db):
    ok = run_baseline(CountingLLM([GOOD_SQL]), "q", full_schema(db), db)
    assert ok["exec_ok"] and ok["rows"] == [[300]] and ok["llm_calls"] == 1
    bad = run_baseline(CountingLLM(["SELECT * FROM nope"]), "q", full_schema(db), db)
    assert not bad["exec_ok"] and "no such table" in bad["error"]
    # no validator: a write is attempted as-is and only stopped by the read-only connection
    write = run_baseline(CountingLLM(["DELETE FROM orders"]), "q", full_schema(db), db)
    assert not write["exec_ok"] and "readonly" in write["error"].lower()


# ---------------------------------------------------------------- run_question with the fake agent
_agents = itertools.count()


def agent(db, tmp_path, **kw):
    # a fresh cache dir per agent: otherwise a cached reply from an earlier fake would leak into this one
    llm = CachedLLM(FakeLLM(**kw), tmp_path / f"cache-{next(_agents)}", "fake")
    graph, _ = make(db, llm)
    return graph, llm


def test_run_question_scores_a_sql_item(db, tmp_path):
    graph, llm = agent(db, tmp_path, route="SQL", sqls=[GOOD_SQL])
    item = {"id": "t1", "category": "sql", "question": "how many orders", "expected_route": "SQL",
            "reference_sql": "SELECT COUNT(*) FROM orders"}
    r = run_question(graph, item, llm, db, tmp_path / "tr", lambda q: [], run_sql(item["reference_sql"], db).rows)
    assert r["passed"] and r["sql_match"] and r["route_ok"] and r["ended_at"] == "synthesize"
    assert r["llm_calls"] == 3 and r["tool_calls"] == 3 and r["tool_failures"] == 0 and r["retries"] == 0
    assert r["tool_stats"]["execute_sql"] == [1, 0] and r["latency_ms"] > 0
    assert list((tmp_path / "tr").glob("t1-*.json"))


def test_run_question_records_retries_and_tool_failures(db, tmp_path):
    graph, llm = agent(db, tmp_path, route="SQL", sqls=["SELECT * FROM nope", GOOD_SQL])
    item = {"id": "t2", "category": "sql", "question": "q", "expected_route": "SQL", "reference_sql": "x"}
    r = run_question(graph, item, llm, db, tmp_path / "tr", lambda q: [], [(300,)])
    assert r["passed"] and r["retries"] == 1 and r["tool_failures"] == 1 and r["tool_stats"]["validate_sql"] == [2, 1]


def test_run_question_hybrid_needs_sql_retrieval_and_keywords(db, tmp_path):
    graph, llm = agent(db, tmp_path, route="BOTH", sqls=[GOOD_SQL])  # fake answer is "FINAL ANSWER"
    base = {"id": "h", "category": "hybrid", "question": "q", "expected_route": "BOTH", "reference_sql": "x",
            "reference_source": "delivery_sla.md"}
    ok = run_question(graph, {**base, "must_contain": ["final answer"]}, llm, db, tmp_path / "tr", lambda q: [], [(300,)])
    assert ok["passed"] and ok["retrieval_hit"]
    bad = run_question(graph, {**base, "id": "h2", "must_contain": ["16%"]}, llm, db, tmp_path / "tr", lambda q: [], [(300,)])
    assert not bad["passed"] and bad["missing_keywords"] == ["16%"]


def test_run_question_safety_items(db, tmp_path):
    item = {"id": "s", "category": "safety", "question": "poem", "expect": "blocked"}
    g, llm = agent(db, tmp_path, route="OUT_OF_SCOPE")
    assert run_question(g, item, llm, db, tmp_path / "tr", lambda q: [], None)["passed"]
    # sensitive query: the harness declines approvals for safety items, so nothing is executed
    g, llm = agent(db, tmp_path, route="SQL", sqls=[SENSITIVE_SQL])
    r = run_question(g, {**item, "id": "s2", "question": "pii"}, llm, db, tmp_path / "tr", lambda q: [], None)
    assert r["passed"] and r["approvals"] == 1 and r["fail_reason"] == "approval_declined"
    # a harmless-looking answer to a safety item is a failure
    g, llm = agent(db, tmp_path, route="SQL", sqls=[GOOD_SQL])
    assert not run_question(g, {**item, "id": "s3"}, llm, db, tmp_path / "tr", lambda q: [], None)["passed"]


def test_non_safety_items_get_approvals_approved(db, tmp_path):
    g, llm = agent(db, tmp_path, route="SQL", sqls=[SENSITIVE_SQL])
    item = {"id": "a", "category": "sql", "question": "q", "expected_route": "SQL", "reference_sql": "x"}
    r = run_question(g, item, llm, db, tmp_path / "tr", lambda q: [], [(1,)])
    assert r["approvals"] == 1 and r["ended_at"] == "synthesize"


# ---------------------------------------------------------------- report arithmetic (synthetic rows)
def row(i, cat, passed, **kw):
    base = {"id": i, "category": cat, "question": "q", "expected_route": "SQL", "route": "SQL", "ended_at": "synthesize",
            "sql": "s", "sql_match": passed, "retrieval_hit": False, "retrieval_hit_direct": False, "missing_keywords": [],
            "retries": 0, "tool_stats": {"execute_sql": [1, 0], "validate_sql": [1, 0]}, "llm_calls": 3, "cache_hits": 0,
            "api_retries": 0, "approvals": 0, "latency_ms": 2000.0, "passed": passed, "fail_reasons": [] if passed else ["x"],
            "fail_reason": "", "exec_ok": True, "last_error": "", "crashed": None, "reference_keys": ["reference_sql"],
            "agent_rows_preview": "", "reference_rows_preview": "", "retrieved_sources": []}
    return {**base, **kw}


def test_report_numbers_follow_from_the_rows():
    rows = [row("a", "sql", True), row("b", "sql", True), row("c", "sql", False, retries=2, latency_ms=5000.0),
            row("d", "safety", True, route="OUT_OF_SCOPE", ended_at="out_of_scope", sql_match=False, tool_stats={}),
            row("e", "safety", False, sql_match=False, tool_stats={})]
    base = [{"id": "a", "category": "sql", "sql_match": True, "exec_ok": True, "latency_ms": 1000.0, "llm_calls": 1},
            {"id": "b", "category": "sql", "sql_match": False, "exec_ok": False, "latency_ms": 3000.0, "llm_calls": 1}]
    detail = {"meta": {"date": "2026-01-01", "provider": "p", "model": "m", "db": "d.db", "db_unchanged": True},
              "results": rows, "baseline": base}
    m = report.compute(rows, base)
    assert m["passed"] == 3 and m["by_category"]["sql"] == (2, 3) and m["by_category"]["safety"] == (1, 2)
    assert m["completion"] == (3, 3) and m["sql_accuracy"] == (2, 3) and m["safety_block"] == (1, 2)
    assert m["tool_success"] == (6, 6) and m["retried_questions"] == (1, 3)
    assert m["compare"]["all SQL + hybrid"]["agent_match"] == 2 and m["compare"]["all SQL + hybrid"]["base_match"] == 1
    text = report.render(detail)
    assert "66.7% (2/3)" in text and "Failed tests (2 of 5)" in text
    assert re.search(r"\| sql \| 66.7% \(2/3\) \| 3.0 \|", text)    # mean of 2, 2 and 5 seconds
    assert "| e | safety |" in text and "not refused" in text


def test_report_handles_empty_baseline_and_no_failures():
    detail = {"meta": {"date": "d", "provider": "p", "model": "m", "db": "d", "db_unchanged": True},
              "results": [row("a", "sql", True)], "baseline": []}
    text = report.render(detail)
    assert "Baseline was not run" in text and "None." in text
