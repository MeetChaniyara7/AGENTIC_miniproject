"""Build the course report as a .docx from report/content/*.md plus the real evaluation files.

    python report/build_report.py

Numbers are never typed into the prose of Chapters 8-9: they are tokens such as {m:accuracy} that
are resolved here from evaluation/results_detail.json, so the report cannot drift from the data.
"""
from __future__ import annotations

import ast
import glob
import importlib.metadata as md
import json
import math
import re
import sqlite3
import statistics
import sys
import textwrap
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from docx_writer import CONTENT_W, Doc  # noqa: E402
from evaluation import report as ev  # noqa: E402

OUT = HERE / "Hybrid_Analyst_Mini_Project_Report.docx"
TITLE = ("Hybrid Analyst: An Agentic AI System for Answering Business Questions by Combining "
         "Text-to-SQL and Retrieval-Augmented Generation")
STUDENTS = [("Meet Chaniyara", "202307020021"), ("Disha Shah", "202307020142"), ("Sanjeev Gupta", "202307020103")]
DETAIL = json.loads((ROOT / "evaluation" / "results_detail.json").read_text(encoding="utf-8"))
TESTSET = {i["id"]: i for i in json.loads((ROOT / "evaluation" / "test_set.json").read_text(encoding="utf-8"))}
RESULTS = {r["id"]: r for r in DETAIL["results"]}
BASELINE = DETAIL["baseline"]
META = DETAIL["meta"]
TEST_RUN = json.loads((HERE / "test_run.json").read_text(encoding="utf-8"))


# ====================================================================== text helpers
def clean(text: str, limit: int | None = None) -> str:
    """Single-line, ASCII-friendly version of model output for tables."""
    text = (text.replace("‑", "-").replace("‐", "-").replace(" ", " ").replace(" ", " ")
            .replace("【", "[").replace("】", "]").replace("**", "").replace("`", "").replace("’", "'")
            .replace("“", '"').replace("”", '"').replace("–", "-").replace("—", "-"))
    text = " ".join(text.split())
    return text if not limit or len(text) <= limit else text[:limit].rstrip() + "..."


def sec(ms: float, nd: int = 1) -> str:
    return f"{ms / 1000:.{nd}f}"


# ====================================================================== tokens
def build_tokens() -> tuple[dict, dict]:
    m = ev.compute(DETAIL["results"], BASELINE)
    res = DETAIL["results"]
    lat = [r["latency_ms"] / 1000 for r in res]
    cmp_all, cmp_sql, cmp_hyb = m["compare"]["all SQL + hybrid"], m["compare"]["sql only"], m["compare"]["hybrid (SQL part only)"]
    frac = lambda a, b: f"{a}/{b}"
    M = {
        "n_total": str(m["n"]), "n_passed": str(m["passed"]), "n_failed": str(m["n"] - m["passed"]),
        "accuracy": ev.pct(m["passed"], m["n"]), "completion": ev.pct(*m["completion"]),
        "sql_acc": ev.pct(*m["sql_accuracy"]), "sql_only_acc": ev.pct(*m["sql_only_accuracy"]),
        "tool_success": ev.pct(*m["tool_success"]), "retr_agent": ev.pct(*m["retrieval_agent"]),
        "retr_direct": ev.pct(*m["retrieval_direct"]), "route_acc": ev.pct(*m["route_accuracy"]),
        "safety_block": ev.pct(*m["safety_block"]), "safety_n": str(m["safety_block"][1]),
        "mean_latency": f"{statistics.fmean(lat):.1f}", "med_latency": f"{statistics.median(lat):.1f}", "max_latency": f"{max(lat):.1f}",
        "lat_sql": f"{statistics.fmean(m['latency']['sql']):.1f}", "lat_docs": f"{statistics.fmean(m['latency']['docs']):.1f}",
        "lat_hybrid": f"{statistics.fmean(m['latency']['hybrid']):.1f}", "lat_safety": f"{statistics.fmean(m['latency']['safety']):.1f}",
        "llm_calls_total": str(m["llm_calls_total"]), "cache_hits": str(m["cache_hits"]), "api_retries": str(m["api_retries"]),
        "n_compare": str(cmp_all["n"]),
        "base_match_all": frac(cmp_all["base_match"], cmp_all["n"]), "agent_match_all": frac(cmp_all["agent_match"], cmp_all["n"]),
        "base_sql": frac(cmp_sql["base_match"], cmp_sql["n"]), "agent_sql": frac(cmp_sql["agent_match"], cmp_sql["n"]),
        "base_hyb": frac(cmp_hyb["base_match"], cmp_hyb["n"]), "agent_hyb": frac(cmp_hyb["agent_match"], cmp_hyb["n"]),
        "base_lat": f"{cmp_all['base_latency']:.1f}", "agent_lat": f"{cmp_all['agent_latency']:.1f}",
        "base_calls": f"{cmp_all['base_calls']:.2f}", "agent_calls": f"{cmp_all['agent_calls']:.2f}",
    }
    hyb = json.load(open(sorted(glob.glob(str(ROOT / "evaluation" / "traces" / "hyb-01-*.json")))[0], encoding="utf-8"))
    from rag.ingest_docs import SKIP, chunk_document
    docs_dir = ROOT / "data" / "docs"
    n_chunks = sum(len(chunk_document(p)) for p in sorted(docs_dir.glob("*.md")) if p.name not in SKIP)
    C = {
        "eval_date": META["date"], "eval_model": META["model"], "eval_provider": META["provider"].capitalize(),
        "hyb01_total": f"{hyb['totals']['duration_ms'] / 1000:.1f}", "n_chunks": str(n_chunks),
        "tests_summary": f"{TEST_RUN['passed']} of {TEST_RUN['total']} automated tests passed",
        "tests_passed": str(TEST_RUN["passed"]), "tests_total": str(TEST_RUN["total"]),
    }
    return M, C


M, C = build_tokens()
V = {n: md.version(n) for n in ("langgraph", "langchain", "langchain-core", "langchain-groq", "langchain-google-genai", "chromadb",
                                "sentence-transformers", "torch", "streamlit", "sqlglot", "pytest", "langchain-text-splitters")}


def resolve(text: str, refs: dict[str, str]) -> str:
    def sub(mo: re.Match) -> str:
        kind, key = mo.group(1), mo.group(2)
        if kind == "m":
            return M[key]
        if kind == "c":
            return C[key]
        return refs[f"{kind}:{key}"]
    out = re.sub(r"\{(m|c|fig|tab):([A-Za-z0-9_\-\.]+)\}", sub, text)
    return out


# ====================================================================== generated tables
def tbl(key, caption, header, rows, widths, align=None, size=20):
    return dict(key=key, caption=caption, header=header, rows=rows, widths=widths, align=align, size=size)


def ref_rows_preview(item: dict) -> str:
    from tools.sql_executor import run_sql
    res = run_sql(item["reference_sql"])
    return ev_preview(res.rows)


def ev_preview(rows, n=3) -> str:
    def fmt(v):
        return f"{v:,.2f}".rstrip("0").rstrip(".") if isinstance(v, float) else (f"{v:,}" if isinstance(v, int) else str(v))
    s = "; ".join(", ".join(fmt(v) for v in r) for r in rows[:n])
    return s + (f" ... ({len(rows)} rows)" if len(rows) > n else "")


def agent_preview(r: dict) -> str:
    p = r.get("agent_rows_preview", "")
    try:
        rows = json.loads(p.split(" ... ")[0])
        return ev_preview(rows)
    except Exception:  # noqa: BLE001
        return clean(p, 80)


def t_lit():
    rows = [
        ["1", "ReAct [1]", "2023", "Prompts an LLM to interleave reasoning steps with actions on external tools and observations of their results.",
         "Combining reasoning with actions improved results on question-answering and decision-making tasks compared with reasoning-only or acting-only prompting.",
         "Depends on the model choosing good actions; extra model calls add cost and latency."],
        ["2", "Retrieval-Augmented Generation [2]", "2020", "Combines a text generator with a retriever over an external document index.",
         "Grounding generation in retrieved passages gave strong results on knowledge-intensive tasks, and knowledge can be updated by changing the index.",
         "Answer quality is limited by retrieval quality."],
        ["3", "Spider [3]", "2018", "Large human-labelled benchmark of questions and SQL over many databases with different schemas.",
         "Made cross-domain Text-to-SQL measurable and showed that generalising to unseen schemas and complex queries is hard.",
         "Benchmark databases are small and clean compared with company data; no documents are involved."],
        ["4", "DIN-SQL [4]", "2023", "Decomposes Text-to-SQL into sub-problems and adds a self-correction step, using in-context prompting of an LLM.",
         "Decomposition and self-correction improved LLM query accuracy on benchmark datasets.",
         "Several LLM calls per question increase cost and latency."],
        ["5", "LangGraph [5]", "2024", "Library for building stateful LLM applications as graphs, with checkpointing and human-in-the-loop interrupts.",
         "Makes control flow, state, memory and approval pauses explicit and testable.",
         "It is a framework, not a method: behaviour still depends on prompts and the LLM."],
    ]
    return tbl("tab:lit", "Summary of reviewed research and frameworks", ["Sr. No.", "Paper / System", "Year", "Approach", "Key Finding", "Limitation"],
               rows, [0.55, 1.3, 0.55, 2.0, 2.3, 1.9], ["center", "left", "center", "left", "left", "left"], size=18)


def t_compare():
    rows = [
        ["Autonomous Execution", "Limited: one prompt, one query, no recovery", "Yes, bounded: routes each question and repairs failed SQL up to 3 times"],
        ["Task Planning", "None", "Routing into fixed paths (SQL, DOCS, BOTH); sub-task list is recorded but not executed"],
        ["Reasoning", "One LLM call", "LLM reasoning in the router, SQL generation and synthesis; rule-based decisions between nodes"],
        ["Tool Usage", "SQL executed directly, without validation", "Document retriever, schema retriever, SQL validator, read-only executor (invoked by the graph)"],
        ["Memory", "None", "Per-thread conversation memory held in process; no long-term memory"],
        ["RAG", "No", "Yes: policy documents, schema notes and example queries"],
        ["Multi-Agent Support", "No", "Not implemented"],
        ["Human Intervention", "None", "Approval before queries that read sensitive columns"],
        ["Traceability", "None", "JSON trace of every step"],
    ]
    return tbl("tab:compare", "Comparison of the existing and proposed systems", ["Feature", "Existing System (single-prompt Text-to-SQL)", "Proposed System (Hybrid Analyst)"],
               rows, [1.5, 2.2, 3.3])


def t_hardware():
    # measured on the development machine on 2026-10-24 with PowerShell Get-CimInstance
    rows = [["Processor", "11th Gen Intel Core i7-11800H, 2.30 GHz (8 cores, 16 threads)"], ["RAM", "15.7 GB"],
            ["Storage", "About 2 GB used (Python environment 1.6 GB, Olist database 172 MB, vector store 2 MB); 37 GB free on a 200 GB drive"],
            ["GPU", "NVIDIA GeForce RTX 3050 Ti Laptop GPU is present but not used: PyTorch is the CPU-only build"],
            ["Internet Connection", "Needed for the hosted LLM (Groq or Google Gemini); not needed for retrieval or for a local Ollama model"]]
    return tbl("tab:hardware", "Hardware used for development and evaluation", ["Component", "Requirement (machine used)"], rows, [1.6, 5.4])


def t_software():
    import sqlite3 as s3
    rows = [["Operating System", "Microsoft Windows 11 Home Single Language 10.0.26100"],
            ["Programming Language", f"Python {sys.version.split()[0]}"],
            ["IDE/Environment", "Visual Studio Code; Python virtual environment (.venv)"],
            ["Agent Framework", f"LangGraph {V['langgraph']}; LangChain {V['langchain']} (langchain-core {V['langchain-core']})"],
            ["LLM", f"{META['model']} on {META['provider'].capitalize()} (used for the evaluation; langchain-groq {V['langchain-groq']}); Google Gemini via "
                    f"langchain-google-genai {V['langchain-google-genai']} (tested, but its free tier was quickly exhausted). A local Ollama option is coded in config.py "
                    "but was not tested"],
            ["Vector Database", f"ChromaDB {V['chromadb']} (persistent, cosine similarity)"],
            ["Embedding Model", f"all-MiniLM-L6-v2 via sentence-transformers {V['sentence-transformers']}; PyTorch {V['torch']} (CPU)"],
            ["Frontend", f"Streamlit {V['streamlit']}"],
            ["APIs/Tools", f"SQLite {s3.sqlite_version} (Python sqlite3); sqlglot {V['sqlglot']}; langchain-text-splitters {V['langchain-text-splitters']}; pytest {V['pytest']}; Groq API; Google Gemini API"]]
    return tbl("tab:software", "Technologies Used", ["Software/Technology", "Version/Specification"], rows, [1.8, 5.2])


def t_functional():
    rows = [
        ["FR1", "Accept a natural-language question together with a conversation identifier.", "app.py, graph/state.py (new_turn)"],
        ["FR2", "Understand the objective: choose SQL, DOCS, BOTH or refuse, and rewrite follow-ups into standalone questions.", "router node, prompts/router.txt"],
        ["FR3", "Generate a plan by selecting the execution path for the chosen route.", "graph/edges.py (after_router)"],
        ["FR4", "Select the required tools for the route.", "graph/build_graph.py, graph/edges.py"],
        ["FR5", "Retrieve relevant policy passages, tables and example queries.", "tools/doc_retriever.py, tools/schema_search.py, rag/"],
        ["FR6", "Generate SQL from the question, schema, examples and business definitions.", "generate_sql node, prompts/sql_gen.txt"],
        ["FR7", "Validate SQL and execute it read-only with a timeout.", "tools/sql_validator.py, tools/sql_executor.py"],
        ["FR8", "Handle errors: feed them back, retry up to three times, then fail with a clear message.", "graph/edges.py, fail node"],
        ["FR9", "Ask a human before running queries that read sensitive columns.", "approval node (LangGraph interrupt), app.py"],
        ["FR10", "Maintain conversation memory per thread.", "MemorySaver in graph/build_graph.py"],
        ["FR11", "Generate the final answer from evidence only, with source citations.", "synthesize node, prompts/synthesize.txt"],
        ["FR12", "Record a structured trace of every step.", "graph/trace.py"],
        ["FR13", "Present the answer, SQL, table, sources and trace in a web interface.", "app.py, graph/ui_support.py"],
        ["FR14", "Evaluate the system against a reference test set and a baseline.", "evaluation/"],
    ]
    return tbl("tab:functional", "Functional Requirements", ["ID", "Requirement", "Implemented in"], rows, [0.6, 4.0, 2.4], ["center", "left", "left"])


def t_components():
    rows = [["User Interface", "Streamlit chat page (app.py): sidebar, answer, SQL, result table, sources, expandable trace and the approval card."],
            ["LLM", "Chat model chosen in config.py (Groq or Google Gemini; an Ollama option is coded but untested); used by the router, generate_sql and synthesize nodes."],
            ["Agent", "The compiled LangGraph state graph (graph/build_graph.py) with the shared AgentState."],
            ["Planner", "The router node: route classification, standalone-question rewriting and an informational sub-task list."],
            ["Reasoning Module", "LLM reasoning inside three nodes, plus rule-based edge functions that decide what happens next (graph/edges.py)."],
            ["Tools", "Document retriever, schema search, SQL validator and read-only SQL executor (tools/)."],
            ["Memory", "LangGraph MemorySaver checkpointer holding each thread's messages (in process memory)."],
            ["Knowledge Base", "ChromaDB collections (policy_docs, schema_notes, example_queries) and the SQLite database olist.db."],
            ["Retriever", "retrieve_docs and retrieve_schema nodes over rag/store.py with local Sentence-Transformers embeddings."],
            ["Executor", "validate_sql and execute_sql nodes (tools/sql_validator.py, tools/sql_executor.py)."],
            ["Output Generator", "synthesize node (prompts/synthesize.txt) and the Streamlit display (graph/ui_support.py)."]]
    return tbl("tab:components", "Architecture components", ["Component", "Description"], rows, [1.5, 5.5])


def t_roles():
    rows = [["Main Agent", "The LangGraph workflow: routes the question, generates SQL, decides retries and approval, and writes the answer."],
            ["Tool Executor", "The validate_sql and execute_sql nodes: check the query, run it read-only, report rows or an error."],
            ["Retriever", "The retrieve_docs and retrieve_schema nodes: find policy passages, relevant tables and similar example queries."],
            ["Memory Module", "The MemorySaver checkpointer: stores each thread's messages so that follow-up questions can be resolved."]]
    return tbl("tab:roles", "Responsibilities of the components of the single-agent system", ["Component / Agent", "Responsibility"], rows, [1.6, 5.4])


def t_tools():
    rows = [["retrieve_docs", "Find policy passages relevant to the question.", "Question, k = 4, minimum score 0.30", "List of {text, source, section, score}; empty if nothing passes"],
            ["search_schema", "Give the SQL generator only the relevant tables and examples.", "Standalone question", "Text with the top 3 tables (with column meanings) and 2 similar example queries"],
            ["validate_sql", "Check generated SQL for safety and correctness rules.", "SQL string", "(ok, cleaned_sql, error, requires_approval)"],
            ["run_sql", "Execute a validated query on a read-only connection.", "SQL string, timeout", "Columns, rows, error message and duration; never raises"]]
    return tbl("tab:tools", "Tools used by the agent", ["Tool", "Purpose", "Input", "Output"], rows, [1.2, 2.0, 1.8, 2.4])


CASE_IDS = ["sql-05", "sql-02", "sql-06", "docs-03", "docs-01", "hyb-02", "hyb-07", "safe-02", "safe-03", "safe-04"]


def expected_text(item: dict) -> str:
    parts = []
    if "reference_sql" in item:
        parts.append("Result: " + ref_rows_preview(item))
    if "reference_source" in item:
        kws = ", ".join(f'"{k}"' for k in item["must_contain"])
        parts.append(f"Answer contains {kws} (source {item['reference_source']})")
    if item["category"] == "safety":
        parts.append("Request is blocked (refused, rejected or declined)")
    return "\n".join(parts)


def actual_text(r: dict, item: dict) -> str:
    if item["category"] == "safety":
        return f"Route {r['route']}; ended at {r['ended_at']}" + (f" ({r['fail_reason']})" if r["fail_reason"] else "")
    parts = []
    if "reference_sql" in item:
        parts.append("Result: " + agent_preview(r))
    if "reference_source" in item:
        parts.append("Answer: " + re.sub(r"^Answer:\s*", "", clean(r["answer"])).strip()[:150])
    return "\n".join(parts)


def t_testcases():
    rows = []
    for n, i in enumerate(CASE_IDS, 1):
        item, r = TESTSET[i], RESULTS[i]
        rows.append([f"TC{n:02d}", f"[{i}] {item['question']}", expected_text(item), actual_text(r, item), "Pass" if r["passed"] else "Fail"])
    return tbl("tab:testcases", "Test Cases", ["Test Case ID", "Input", "Expected Output", "Actual Output", "Status"], rows,
               [0.7, 2.0, 1.9, 2.3, 0.6], ["center", "left", "left", "left", "center"], size=17)


def t_trace_hyb01():
    tr = json.load(open(sorted(glob.glob(str(ROOT / "evaluation" / "traces" / "hyb-01-*.json")))[0], encoding="utf-8"))
    rows = [[str(i), e["node"], f"{e['duration_ms']:.0f}", str(e["llm_calls"]), "ok" if e["success"] else "failed", clean(e["summary"], 90)]
            for i, e in enumerate(tr["trace"], 1)]
    return tbl("tab:trace", "Execution trace of test case hyb-01", ["#", "Node", "Duration (ms)", "LLM calls", "Status", "Summary"], rows,
               [0.4, 1.4, 0.9, 0.8, 0.7, 3.0], ["center", "left", "right", "center", "center", "left"], size=18)


def t_perf():
    rows = [["Task Completion Rate", "Non-safety questions that ended with an answer / non-safety questions", M["completion"]],
            ["Accuracy", "Questions meeting their category's pass rule / all evaluation questions", M["accuracy"]],
            ["SQL Accuracy", "SQL and hybrid questions whose result equals the reference result / SQL and hybrid questions", M["sql_acc"]],
            ["Tool Success Rate", "Successful tool calls / total tool calls (retrieve_docs, retrieve_schema, validate_sql, execute_sql)", M["tool_success"]],
            ["Average Response Time", "Mean end-to-end time per evaluation question", f"{M['mean_latency']} s (median {M['med_latency']} s, maximum {M['max_latency']} s)"],
            ["Retrieval Accuracy", "Document and hybrid questions whose expected file was among the top-4 retrieved chunks / such questions (file-level)", M["retr_agent"]],
            ["Test Case Success Rate", "Automated software tests passed / total tests (pytest)", f"{ev.pct(TEST_RUN['passed'], TEST_RUN['total'])}"],
            ["Route Accuracy", "Router chose the expected route / non-safety questions", M["route_acc"]],
            ["Safety Block Rate", "Safety requests that were stopped / safety requests", M["safety_block"]]]
    return tbl("tab:perf", "Performance Evaluation", ["Metric", "Evaluation Method", "Result"], rows, [1.7, 3.6, 1.7])


def t_bycat():
    m = ev.compute(DETAIL["results"], BASELINE)
    rows = []
    for c, (p, n) in m["by_category"].items():
        x = m["latency"][c]
        rows.append([c, str(n), str(p), f"{100 * p / n:.1f}%", f"{statistics.fmean(x):.1f}", f"{statistics.median(x):.1f}", f"{max(x):.1f}"])
    allx = [r["latency_ms"] / 1000 for r in DETAIL["results"]]
    rows.append(["all", str(m["n"]), str(m["passed"]), f"{100 * m['passed'] / m['n']:.1f}%", f"{statistics.fmean(allx):.1f}", f"{statistics.median(allx):.1f}", f"{max(allx):.1f}"])
    return tbl("tab:bycat", "Accuracy and response time per question by category (seconds)",
               ["Category", "Questions", "Passed", "Pass rate", "Mean time", "Median time", "Max time"], rows, [1.4, 1, 0.9, 1, 1, 1.1, 1], ["left"] + ["center"] * 6)


def t_toolbreak():
    m = ev.compute(DETAIL["results"], BASELINE)
    rows = [[t, str(c), str(f), ev.pct(c - f, c)] for t, (c, f) in m["tools"].items()]
    tc, tf = sum(v[0] for v in m["tools"].values()), sum(v[1] for v in m["tools"].values())
    rows.append(["all tools", str(tc), str(tf), ev.pct(tc - tf, tc)])
    return tbl("tab:toolbreak", "Tool calls and failures", ["Tool", "Calls", "Failures", "Success rate"], rows, [2, 1.2, 1.2, 2.2], ["left", "center", "center", "center"])


def t_retrieval():
    m = ev.compute(DETAIL["results"], BASELINE)
    rows = [[c, str(a), str(d), str(n)] for c, (a, d, n) in m["retrieval_by_cat"].items()]
    return tbl("tab:retrieval", "Retrieval accuracy by category (file-level)", ["Category", "Expected file in agent's top-4", "Expected file with raw question", "Questions"],
               rows, [1.5, 2.2, 2.2, 1.2], ["left", "center", "center", "center"])


def safety_how(r: dict) -> str:
    return ("router refused (out of scope)" if r["route"] == "OUT_OF_SCOPE" else "approval declined" if r["fail_reason"] == "approval_declined" else
            "validator rejected every attempt (retries exhausted)" if r["fail_reason"] == "retries_exhausted" else r["fail_reason"] or "not stopped")


def t_safety():
    rows = [[r["id"], TESTSET[r["id"]]["subtype"], r["route"], r["ended_at"], str(r["approvals"]), safety_how(r), "yes" if r["passed"] else "no"]
            for r in DETAIL["results"] if r["category"] == "safety"]
    return tbl("tab:safety", "How each safety request was stopped", ["ID", "Type", "Route", "Ended at", "Approvals asked", "Stopped by", "Blocked"], rows,
               [0.8, 1.1, 1.2, 1.0, 0.8, 2.3, 0.7], ["left", "left", "left", "left", "center", "left", "center"], size=18)


def t_baseline():
    m = ev.compute(DETAIL["results"], BASELINE)
    rows = []
    for label, c in m["compare"].items():
        rows.append([label, str(c["n"]), "Agent", ev.pct(c["agent_match"], c["n"]), ev.pct(c["agent_exec"], c["n"]), f"{c['agent_latency']:.1f}", f"{c['agent_calls']:.2f}"])
        rows.append(["", "", "Baseline", ev.pct(c["base_match"], c["n"]), ev.pct(c["base_exec"], c["n"]), f"{c['base_latency']:.1f}", f"{c['base_calls']:.2f}"])
    return tbl("tab:baseline", "Agent compared with the single-prompt baseline", ["Subset", "Questions", "System", "Result match", "Executed", "Avg time (s)", "Avg LLM calls"],
               rows, [1.6, 0.8, 0.9, 1.3, 1.3, 0.9, 0.9], ["left", "center", "left", "center", "center", "center", "center"], size=18)


def t_failures():
    rows = [[r["id"], r["category"], clean(r["question"], 140), clean(ev.likely_cause(r), 420)] for r in DETAIL["results"] if not r["passed"]]
    return tbl("tab:failures", "Failed test cases and likely causes", ["ID", "Category", "Question", "Likely cause (from the recorded run, checked against the answer)"], rows,
               [0.7, 0.8, 2.3, 3.6], ["left", "left", "left", "left"], size=17)


def t_prompts():
    rows = [["1", "Router prompt (prompts/router.txt)", "Chooses the route, rewrites the question using the conversation, lists sub-tasks and gives a reason; output is JSON."],
            ["2", "SQL generation prompt (prompts/sql_gen.txt)", "Writes one SQLite SELECT from the question, schema, example queries, business definitions and, on a retry, the previous error."],
            ["3", "Synthesis prompt (prompts/synthesize.txt)", "Writes the final answer using only the supplied rows and passages, with citations."],
            ["4", "Baseline prompt (evaluation/baseline.py)", "Single prompt with the full schema, used only for the baseline comparison."]]
    return tbl("tab:prompts", "Prompts used in the system", ["Sr. No.", "Prompt", "Purpose"], rows, [0.7, 2.6, 3.7], ["center", "left", "left"])


def t_dbtables():
    notes = json.loads((ROOT / "data" / "schema_notes.json").read_text(encoding="utf-8"))["tables"]
    counts = META["table_counts"]
    rows = [[name, f"{counts[name]:,}", clean(notes[name]["description"].split(". ")[0].rstrip(".") + ".", 160)] for name in notes]
    return tbl("tab:dbtables", "Tables of the Olist database loaded for this project", ["Table", "Rows", "Description"], rows, [1.9, 0.9, 4.2], ["left", "right", "left"])


def t_docs():
    from rag.ingest_docs import chunk_document
    rows = []
    for p in sorted((ROOT / "data" / "docs").glob("*.md")):
        if p.name == "README.md":
            continue
        text = p.read_text(encoding="utf-8")
        title = next(l[2:].strip() for l in text.splitlines() if l.startswith("# "))
        rows.append([p.name, str(len(text.split())), str(len(chunk_document(p))), title])
    return tbl("tab:docs", "Policy documents used for retrieval", ["File", "Words", "Chunks", "Title"], rows, [2.2, 0.8, 0.8, 3.2], ["left", "center", "center", "left"])


def t_examples():
    ex = json.loads((ROOT / "data" / "example_queries.json").read_text(encoding="utf-8"))
    return tbl("tab:examples", "Example question and SQL pairs used as few-shot examples", ["ID", "Question"], [[str(e["id"]), e["question"]] for e in ex], [0.6, 6.4], ["center", "left"])


def t_alltests():
    rows = []
    for i, item in TESTSET.items():
        r = RESULTS[i]
        if "reference_sql" in item:
            ref = "Result: " + ref_rows_preview(item)
            if "reference_source" in item:
                ref += f"; {item['reference_source']}: " + ", ".join(item["must_contain"])
        elif "reference_source" in item:
            ref = f"{item['reference_source']}: " + ", ".join(item["must_contain"])
        else:
            ref = "must be blocked"
        rows.append([i, item["category"], item["question"], ref, r["route"] or "-", "Pass" if r["passed"] else "Fail", sec(r["latency_ms"])])
    return tbl("tab:alltests", "Evaluation test set and outcome of each question", ["ID", "Category", "Question", "Reference", "Route", "Result", "Time (s)"], rows,
               [0.65, 0.65, 2.5, 1.7, 0.75, 0.5, 0.5], ["left", "left", "left", "left", "left", "center", "center"], size=15)


TABLES = {"lit": t_lit, "compare": t_compare, "hardware": t_hardware, "software": t_software, "functional": t_functional, "components": t_components,
          "roles": t_roles, "tools": t_tools, "testcases": t_testcases, "perf": t_perf, "bycat": t_bycat,
          "toolbreak": t_toolbreak, "retrieval": t_retrieval, "safety": t_safety, "baseline": t_baseline, "failures": t_failures, "prompts": t_prompts,
          "dbtables": t_dbtables, "docs": t_docs, "examples": t_examples, "alltests": t_alltests}


# ====================================================================== code, tree, cases
def snippet(spec: str) -> tuple[list[str], str]:
    path, _, name = spec.partition("::")
    src = (ROOT / path.strip()).read_text(encoding="utf-8")
    tree = ast.parse(src)
    node = next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == name.strip())
    start = min([node.lineno] + [d.lineno for d in node.decorator_list])
    lines = textwrap.dedent("\n".join(src.splitlines()[start - 1:node.end_lineno])).splitlines()
    return lines, path.strip()


TREE_NOTES = {
    "app.py": "Streamlit chat interface", "config.py": "LLM / embedding choice, paths, SQL limits", "requirements.txt": "dependencies",
    "README.md": "setup, run, evaluate", ".env.example": "template for keys (real keys live in .env)",
    "graph": "LangGraph agent", "state.py": "AgentState and new_turn()", "nodes.py": "all nodes (router ... fail)", "edges.py": "conditional routing rules",
    "build_graph.py": "assembles and compiles the graph", "trace.py": "tracing decorator and JSON writer", "run.py": "command-line runner",
    "prompts.py": "prompt loader", "ui_support.py": "turns graph state into what the UI shows", "tools": "agent tools",
    "doc_retriever.py": "retrieve_docs", "schema_search.py": "search_schema", "sql_validator.py": "validate_sql (sqlglot)", "sql_executor.py": "run_sql (read-only)",
    "rag": "ingestion and retrieval helpers", "ingest_docs.py": "chunk and index policy documents", "ingest_schema.py": "index schema notes and examples",
    "store.py": "Chroma and embedding helpers", "try.py": "try retrieval from the command line", "prompts": "prompt templates (plain text)",
    "evaluation": "evaluation harness", "run_eval.py": "runs the test set and the baseline", "scoring.py": "pass / fail rules", "baseline.py": "single-prompt baseline",
    "llm_cache.py": "disk cache and rate-limit retries", "report.py": "builds summary.md", "test_set.json": "30 evaluation questions",
    "results.csv": "one row per question", "summary.md": "generated summary", "data": "database, documents and notes",
    "docs": "project brief", "data/docs": "six policy documents (synthetic)", "data/docs/README.md": "states that the documents are synthetic",
    "schema_notes.json": "table and column descriptions", "example_queries.json": "12 question / SQL pairs", "scripts": "data loading", "load_olist.py": "CSV to SQLite",
    "verify_examples.py": "runs the example queries", "tests": "automated tests (pytest)", "report": "report builder (this document)",
}
TREE_SKIP = {".venv", "chroma_db", "__pycache__", ".pytest_cache", "llm_cache", "node_modules", ".git", "figures", "content", "Hybrid_Analyst_Mini_Project_Report.docx"}


def tree_lines() -> list[str]:
    lines = [f"{ROOT.name}/"]

    def walk(d: Path, prefix: str) -> None:
        entries = sorted([p for p in d.iterdir()
                          if p.name not in TREE_SKIP and p.name not in (".env", "__init__.py", ".gitkeep")
                          and not p.name.endswith((".pyc", ".log")) and not p.name.startswith("_")],
                         key=lambda p: (p.is_file(), p.name.lower()))
        for i, p in enumerate(entries):
            last = i == len(entries) - 1
            note = TREE_NOTES.get(p.relative_to(ROOT).as_posix()) or TREE_NOTES.get(p.name, "")
            lines.append(f"{prefix}{'└── ' if last else '├── '}{p.name}{'/' if p.is_dir() else ''}" + (f"   # {note}" if note else ""))
            if p.is_dir() and p.name not in ("traces", "raw"):   # generated / downloaded content: show the folder only
                walk(p, prefix + ("    " if last else "│   "))

    walk(ROOT, "")
    return lines


def case_data(spec: str) -> dict:
    if spec.startswith("traces:"):
        # several runs share the prefix: use the one in which the graph really reached the approval node
        candidates = [json.load(open(f, encoding="utf-8")) for f in sorted(glob.glob(str(ROOT / "traces" / f"{spec.split(':', 1)[1]}-*.json")))]
        tr = next(c for c in candidates if any(e["node"] == "approval" for e in c["trace"]))
        return {"title": "human-in-the-loop (command-line run, not part of the 30-question set)", "question": tr["question"], "trace": tr["trace"],
                "answer": tr["answer"], "status": "Approval declined by the user; the query was not run", "route": tr["route"]}
    r, item = RESULTS[spec], TESTSET[spec]
    f = sorted(glob.glob(str(ROOT / "evaluation" / "traces" / f"{spec}-*.json")))[0]
    tr = json.load(open(f, encoding="utf-8"))
    return {"title": f"{item['category']} question ({spec})", "question": item["question"], "trace": tr["trace"], "answer": r["answer"],
            "status": ("Pass" if r["passed"] else "Fail") + f"; route {r['route']}; {sec(r['latency_ms'])} s", "route": r["route"]}


# ====================================================================== parsing
def parse(path: Path) -> list[dict]:
    blocks, para, items, kind = [], [], [], None

    def flush():
        nonlocal para, items, kind
        if para:
            blocks.append({"t": "p", "text": " ".join(para)})
            para = []
        if items:
            blocks.append({"t": kind, "items": items})
            items, kind = [], None

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if not line.strip():
            flush()
            continue
        if line.startswith("@@"):
            flush()
            cmd, _, rest = line[2:].partition(" ")
            parts = [x.strip() for x in rest.split("|")]
            if cmd == "TABLE":
                blocks.append({"t": "table", "name": rest.strip()})
            elif cmd == "FIG":
                blocks.append({"t": "fig", "key": parts[0], "path": parts[1], "width": float(parts[2]), "caption": parts[3]})
            elif cmd == "SHOT":
                blocks.append({"t": "shot", "key": parts[0], "desc": parts[1], "caption": parts[2]})
            elif cmd == "CASE":
                blocks.append({"t": "case", "spec": parts[0], "key": parts[1], "caption": parts[2]})
            elif cmd == "SNIPPET":
                blocks.append({"t": "snippet", "spec": parts[0], "label": parts[1] if len(parts) > 1 else ""})
            elif cmd == "PROMPT":
                blocks.append({"t": "prompt", "name": rest.strip()})
            elif cmd == "BASELINEPROMPT":
                blocks.append({"t": "baselineprompt"})
            elif cmd == "TREE":
                blocks.append({"t": "tree"})
            else:
                raise ValueError(f"unknown directive {line}")
            continue
        m = re.match(r"^(#{1,3}) (.*)$", line)
        if m:
            flush()
            blocks.append({"t": "h", "lvl": len(m.group(1)), "text": m.group(2)})
            continue
        if line.startswith("- "):
            if para or kind == "ol":
                flush()
            kind = "ul"
            items.append(line[2:])
            continue
        m = re.match(r"^\d+\. (.*)$", line)
        if m:
            if para or kind == "ul":
                flush()
            kind = "ol"
            items.append(m.group(1))
            continue
        if items:      # continuation line of a list item
            items[-1] += " " + line.strip()
        else:
            para.append(line.strip())
    flush()
    return blocks


# ====================================================================== numbering and rendering
def number(blocks: list[dict]) -> tuple[dict[str, str], list[tuple[str, str, str]], list[tuple[str, str, str]]]:
    refs, figs, tabs = {}, [], []
    for b in blocks:
        if b["t"] in ("fig", "shot", "case"):
            n = len(figs) + 1
            refs[b["key"]] = f"Figure {n}"
            figs.append((b["key"], f"Figure {n}", b["caption"]))
            b["n"] = n
        elif b["t"] == "table":
            meta = TABLES[b["name"]]()
            n = len(tabs) + 1
            refs[meta["key"]] = f"Table {n}"
            tabs.append((meta["key"], f"Table {n}", meta["caption"]))
            b["n"], b["meta"] = n, meta
    return refs, figs, tabs


def bm_name(key: str) -> str:
    return "_Ref_" + re.sub(r"[^A-Za-z0-9]", "_", key)


def words(text: str) -> int:
    return len(re.findall(r"\b\w[\w'’-]*\b", text))


def build() -> None:
    chapters = [parse(HERE / "content" / f) for f in ("ch1_3.md", "ch4_7.md", "ch8_12.md", "appendix.md")]
    blocks = [b for ch in chapters for b in ch]
    refs, figs, tabs = number(blocks)
    R = lambda s: resolve(s, refs)

    front = (HERE / "content" / "front.md").read_text(encoding="utf-8")
    ack = re.search(r"## ack\n(.*?)(?=\n## |\Z)", front, re.S).group(1).strip()
    abstract = R(re.search(r"## abstract\n(.*?)(?=\n## |\Z)", front, re.S).group(1).strip())
    n_ack, n_abs = words(ack), words(abstract)
    assert 150 <= n_ack <= 200, f"acknowledgement has {n_ack} words (template: 150-200)"
    assert 150 <= n_abs <= 250, f"abstract has {n_abs} words (template: 150-250)"

    doc = Doc(TITLE, ", ".join(n for n, _ in STUDENTS))
    P, run = doc.para, doc.run

    # ---------------------------------------------------------------- cover
    def center(text, size=24, bold=True, before=0, after=120):
        P(run(text, bold=bold, size=size), jc="center", spacing={"before": before, "after": after, "line": 276, "lineRule": "auto"})

    center("[Insert Karnavati University logo]", size=22, bold=False, before=0, after=240)
    center("KARNAVATI UNIVERSITY", 28, after=0)
    center("UNITEDWORLD INSTITUTE OF TECHNOLOGY (UIT)", 24, after=360)
    center("MINI PROJECT REPORT", 36, after=240)
    center("ON", 24, after=240)
    center(f"“{TITLE}”", 32, after=360)
    center("Submitted as a part of the course", 24, after=120)
    center("AGENTIC AI", 36, after=240)
    center("Submitted By", 26, after=120)
    doc.table(["Student Name", "Enrollment No."], [[n, e] for n, e in STUDENTS], [1, 1], size=24, align=["center", "center"])
    center("Program: B.Tech CSE", 24, after=0)
    center("Semester: VI", 24, after=0)
    center("Section: __________", 24, after=240)
    center("Under the Guidance of", 26, after=120)
    center("Faculty Name: ______________________", 24, after=0)
    center("Assistant Professor", 24, bold=False, after=0)
    center("Department of Computer Science & Information Technology", 24, bold=False, after=0)

    # ---------------------------------------------------------------- certificate and declaration
    def student_table():
        doc.table(["Sr. No.", "Student Name", "Enrollment No."], [[str(i), n, e] for i, (n, e) in enumerate(STUDENTS, 1)], [0.8, 2.6, 2.0], size=24, align=["center", "left", "center"])

    P(run("CERTIFICATE"), style="FrontHeading")
    center("Karnavati University, Gandhinagar", 24, after=60)
    center("Academic Year: 2026–27", 24, after=240)
    P(doc.inline(f"This is to certify that the mini project entitled “**{TITLE}**” has been successfully completed by the following students of B.Tech CSE "
                 "Semester VI, Karnavati University, as a part of the course **Agentic AI** during the academic year 2026–27."))
    student_table()
    P(doc.inline("The project has been carried out under the guidance and supervision of the faculty member. The work presented in this report is the original work "
                 "carried out by the students as part of their mini project."))
    P(run("Faculty Guide", bold=True), spacing={"before": 240, "after": 0})
    for label in ("Name", "Signature", "Date"):
        P(run(f"{label}: ______________________________"), jc="left", spacing={"before": 0, "after": 0})

    P(run("DECLARATION"), style="FrontHeading")
    P(doc.inline(f"We hereby declare that the mini project entitled “**{TITLE}**” submitted as part of the course **Agentic AI** is our original work carried out "
                 "under the guidance of the faculty member."))
    P(run("We further declare that this work has not been submitted previously to any other institution or university for the award of any degree, diploma, or academic certification."))
    P(run("All research papers, datasets, frameworks, APIs, libraries, websites, and other resources used during the development of the project have been appropriately acknowledged and referenced."))
    student_table()
    P(run("Date: __________________"), jc="left", spacing={"before": 360, "after": 0})
    P(doc.inline("**Place:** Gandhinagar"), jc="left")

    P(run("ACKNOWLEDGEMENT"), style="FrontHeading")
    for para in ack.split("\n\n"):
        P(doc.inline(para.strip()))
    P(run("ABSTRACT"), style="FrontHeading")
    for para in abstract.split("\n\n"):
        P(doc.inline(para.strip()))

    # ---------------------------------------------------------------- TOC, list of figures, list of tables
    P(run("TABLE OF CONTENTS"), style="FrontHeading")
    heads = [b for b in blocks if b["t"] == "h"]
    entries = [(b["lvl"], R(b["text"])) for b in heads]

    def toc_par(style, text, first=False, last=False):
        x = f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr>'
        if first:
            x += ('<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText xml:space="preserve"> TOC \\o "1-3" \\h \\z \\u </w:instrText></w:r>'
                  '<w:r><w:fldChar w:fldCharType="separate"/></w:r>')
        x += doc.run(text)
        if last:
            x += '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
        doc.body.append(x + "</w:p>")

    for i, (lvl, text) in enumerate(entries):
        toc_par(f"TOC{lvl}", text, first=(i == 0), last=(i == len(entries) - 1))
    P(doc.inline("*In Microsoft Word, right-click the table of contents and the two lists below and choose Update Field (or allow Word to update fields when the file opens) to fill in page numbers.*"),
      style="TableText", spacing={"before": 120, "after": 0})

    P(run("LIST OF FIGURES"), style="FrontHeading")
    doc.table(["Figure No.", "Figure Title", "Page No."], [[n, cap, "{{PAGEREF:" + bm_name(k) + "}}"] for k, n, cap in figs], [1.0, 5.0, 0.9], align=["left", "left", "center"], size=22)
    P(run("LIST OF TABLES"), style="FrontHeading")
    doc.table(["Table No.", "Table Title", "Page No."], [[n, cap, "{{PAGEREF:" + bm_name(k) + "}}"] for k, n, cap in tabs], [1.0, 5.0, 0.9], align=["left", "left", "center"], size=22)

    # ---------------------------------------------------------------- body
    placeholders = []
    case_no = 0
    est = {"lines": 0.0, "tables": 0.0, "figs": 0.0, "code": 0.0}
    in_appendix = False
    est_stop = False

    def caption(kind: str, n: int, key: str, text: str):
        style = "Caption" if kind == "Figure" else "TableCaption"
        bm = doc.bookmark(bm_name(key), run(f"{kind} ") + doc.field(f"SEQ {kind} \\* ARABIC", str(n)) + run(f": {R(text)}"))
        P(bm, style=style)

    def text_par(s: str):
        s = R(s)
        P(doc.inline(s))
        if not est_stop:
            est["lines"] += math.ceil(len(s) / 83) * 20.7 + 6

    for b in blocks:
        t_ = b["t"]
        if t_ == "h":
            if b["lvl"] == 1 and b["text"].startswith("APPENDIX"):
                in_appendix = True
                est_stop = True
            doc.heading(b["lvl"], R(b["text"]))
        elif t_ == "p":
            text_par(b["text"])
        elif t_ in ("ul", "ol"):
            items = [R(i) for i in b["items"]]
            (doc.bullets if t_ == "ul" else doc.numbered)(items)
            if not est_stop:
                est["lines"] += sum(math.ceil(len(i) / 78) * 20.7 + 3 for i in items)
        elif t_ == "table":
            meta = b["meta"]
            caption("Table", b["n"], meta["key"], meta["caption"])
            rows = [[R(c) for c in r] for r in meta["rows"]]
            doc.table(meta["header"], rows, meta["widths"], size=meta["size"], align=meta["align"])
            if not est_stop:
                tot = sum(meta["widths"])
                h = 0.0
                for r in [meta["header"]] + rows:
                    mx = max(max(1, math.ceil(len(c) * (meta["size"] / 20) / max(1, 83 * w / tot * 0.85))) for c, w in zip(r, meta["widths"]))
                    h += mx * (meta["size"] / 2 * 1.2) + 6
                est["tables"] += h + 40
        elif t_ == "fig":
            doc.image(HERE / b["path"], b["width"])
            caption("Figure", b["n"], b["key"], b["caption"])
            from PIL import Image
            w, h = Image.open(HERE / b["path"]).size
            if not est_stop:
                est["figs"] += b["width"] * 72 * h / w + 60
        elif t_ == "shot":
            P(doc.run(f"[{R(b['desc'])}]", italic=True, color="595959"), border="dashed", shade="F7F7F7", jc="center", keep_next=True,
              spacing={"before": 120, "after": 120, "line": 276, "lineRule": "auto"}, ind={"left": 200, "right": 200})
            caption("Figure", b["n"], b["key"], b["caption"])
            placeholders.append((refs[b["key"]], b["desc"], b["caption"]))
            if not est_stop:
                est["figs"] += 230
        elif t_ == "case":
            d = case_data(b["spec"])
            label = f"TC{CASE_IDS.index(b['spec']) + 1:02d}" if b["spec"] in CASE_IDS else "Additional case"   # same IDs as Table 8.1
            doc.heading(3, f"{label}: {d['title']}")
            # raw runs (not doc.inline): SQL and model output contain asterisks that must not be read as markdown
            P(run("Input: ", bold=True) + run(clean(d["question"])), jc="left")
            steps = "; ".join(f"{i}. {e['node']} ({clean(e['summary'], 70)}; {e['duration_ms']:.0f} ms)" for i, e in enumerate(d["trace"], 1))
            P(run("Agent Action: ", bold=True) + run(steps), jc="left")
            P(run("Output: ", bold=True) + run(clean(d["answer"], 650)), jc="left")
            P(run("Result: ", bold=True) + run(f"{d['status']}."), jc="left")
            P(run("Screenshot:", bold=True), jc="left", keep_next=True)
            P(doc.run(f"[Insert Screenshot: {clean(d['question'], 120)}]", italic=True, color="595959"), border="dashed", shade="F7F7F7", jc="center", keep_next=True,
              spacing={"before": 120, "after": 120, "line": 276, "lineRule": "auto"}, ind={"left": 200, "right": 200})
            caption("Figure", b["n"], b["key"], b["caption"])
            placeholders.append((refs[b["key"]], f"Question: {d['question']}", b["caption"]))
            if not est_stop:
                est["lines"] += 12 * 24 + len(d["trace"]) * 40
                est["figs"] += 230
        elif t_ == "snippet":
            lines, file = snippet(b["spec"])
            P(doc.run(b["label"] or file, italic=True, size=22), jc="left", keep_next=True, spacing={"before": 60, "after": 40, "line": 240, "lineRule": "auto"})
            doc.code(lines)
            doc.empty()
            if not est_stop:
                est["code"] += len(lines) * 10.8 + 24
        elif t_ == "prompt":
            doc.code((ROOT / "prompts" / f"{b['name']}.txt").read_text(encoding="utf-8").splitlines(), size=17)
            doc.empty()
        elif t_ == "baselineprompt":
            from evaluation.baseline import PROMPT
            doc.code(PROMPT.splitlines(), size=17)
            doc.empty()
        elif t_ == "tree":
            lines = tree_lines()
            doc.code(lines, size=16)
            doc.empty()
            est["code"] += len(lines) * 9.6

    # ---------------------------------------------------------------- checks and output
    chapter12 = []
    grab = False
    for b in blocks:
        if b["t"] == "h" and b["lvl"] == 1:
            grab = b["text"].startswith("CHAPTER 12")
            continue
        if grab and b["t"] == "p":
            chapter12.append(R(b["text"]))
    n_con = words(" ".join(chapter12))
    assert 250 <= n_con <= 400, f"conclusion has {n_con} words (template: 250-400)"

    body_words = sum(words(R(b["text"])) for b in blocks if b["t"] == "p") + sum(words(R(i)) for b in blocks if b["t"] in ("ul", "ol") for i in b["items"])
    unresolved = re.findall(r"\{(?:m|c|fig|tab):[^}]+\}", "".join(doc.body))
    assert not unresolved, f"unresolved tokens: {unresolved[:5]}"

    doc.save(OUT)
    pages = (est["lines"] + est["tables"] + est["figs"] + est["code"]) / 698
    print(f"wrote {OUT}")
    print(f"acknowledgement {n_ack} words, abstract {n_abs} words, conclusion {n_con} words, prose {body_words} words")
    print(f"figures: {len(figs)} ({len(placeholders)} screenshot placeholders), tables: {len(tabs)}")
    print(f"rough length estimate for chapters 1-12 (excluding appendix): ~{pages:.0f} pages (lines {est['lines'] / 698:.1f}, tables {est['tables'] / 698:.1f}, "
          f"figures {est['figs'] / 698:.1f}, code {est['code'] / 698:.1f}); front matter adds ~10 pages")
    (HERE / "screenshots_needed.json").write_text(json.dumps([{"figure": f, "what": d, "caption": c} for f, d, c in placeholders], indent=2), encoding="utf-8")


if __name__ == "__main__":
    build()
