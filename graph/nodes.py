"""Graph nodes. Each node is traced and returns (state_update, trace_info).

Dependencies (LLM, retrievers, SQL runner) are injected through Deps so tests can
run the whole graph with a fake LLM and no vector store.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable

from langchain_core.messages import AIMessage
from langgraph.types import interrupt

from graph.prompts import render
from graph.state import MAX_RETRIES
from graph.trace import traced
from tools.sql_validator import find_sensitive, validate_sql

ROUTES = {"SQL", "DOCS", "BOTH", "OUT_OF_SCOPE"}
RESULT_ROWS_IN_PROMPT = 40


@dataclass
class Deps:
    llm: Any
    docs_fn: Callable[[str], list[dict]]
    schema_fn: Callable[[str], str]
    run_fn: Callable[[str], Any]   # returns tools.sql_executor.ExecutionResult


# ---------------------------------------------------------------- helpers
def content_text(response: Any) -> str:
    """Chat models return a str or (Gemini) a list of content blocks; normalise to text."""
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)


def parse_json(text: str) -> dict | None:
    """Parse a JSON object from model output, tolerating ```json fences and surrounding prose."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    candidates = [text]
    braces = re.search(r"\{.*\}", text, re.DOTALL)
    if braces:
        candidates.append(braces.group(0))
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        return data if isinstance(data, dict) else None
    return None


def extract_sql(text: str) -> str:
    fenced = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    sql = fenced.group(1) if fenced else text
    return re.sub(r"^\s*SQL:\s*", "", sql.strip(), flags=re.IGNORECASE).strip()


def format_history(messages: list, max_messages: int = 6) -> str:
    """Previous turns only (the last message is the current question)."""
    past = messages[:-1][-max_messages:]
    lines = []
    for m in past:
        role = "User" if m.type == "human" else "Assistant"
        lines.append(f"{role}: {str(m.content)[:600]}")
    return "\n".join(lines) or "(none)"


def format_results(columns: list[str], rows: list[list]) -> str:
    if not columns:
        return ""
    shown = rows[:RESULT_ROWS_IN_PROMPT]
    out = [" | ".join(columns)] + [" | ".join(str(v) for v in r) for r in shown]
    if len(rows) > len(shown):
        out.append(f"(showing {len(shown)} of {len(rows)} rows)")
    if not rows:
        out.append("(0 rows)")
    return "\n".join(out)


def format_docs(chunks: list[dict]) -> str:
    return "\n\n".join(f"[{c['source']}] ({c['section']})\n{c['text']}" for c in chunks)


# ---------------------------------------------------------------- nodes
def make_nodes(deps: Deps) -> dict[str, Callable]:
    llm = deps.llm

    @traced("router")
    def router(state):
        prompt = render("router", history=format_history(state["messages"]), question=state["question"])
        raw = content_text(llm.invoke(prompt))
        data = parse_json(raw)
        if not data or data.get("route") not in ROUTES:
            # Unparseable router output: BOTH is the safe default (it can still answer, just costs more).
            update = {"route": "BOTH", "route_reason": "router output was not valid JSON; defaulted to BOTH",
                      "standalone_question": state["question"], "sub_tasks": []}
            return update, {"summary": "route=BOTH (fallback: invalid router JSON)", "success": False,
                            "llm_calls": 1, "input": state["question"], "output": raw}
        sub_tasks = [t for t in data.get("sub_tasks", []) if isinstance(t, dict)]
        update = {"route": data["route"], "route_reason": str(data.get("reason", "")),
                  "standalone_question": str(data.get("rewritten_question") or state["question"]),
                  "sub_tasks": sub_tasks}
        return update, {"summary": f"route={data['route']}: {update['route_reason']}", "llm_calls": 1,
                        "input": state["question"], "output": json.dumps(data)}

    @traced("retrieve_docs")
    def retrieve_docs(state):
        chunks = deps.docs_fn(state["standalone_question"])
        sources = sorted({c["source"] for c in chunks})
        summary = f"{len(chunks)} chunks from {', '.join(sources)}" if chunks else "no relevant document chunks"
        return {"doc_chunks": chunks}, {"summary": summary, "input": state["standalone_question"],
                                        "output": [f"{c['source']} ({c['score']})" for c in chunks]}

    @traced("retrieve_schema")
    def retrieve_schema(state):
        ctx = deps.schema_fn(state["standalone_question"])
        tables = re.findall(r"^Table (\w+):", ctx, re.MULTILINE)
        return {"schema_context": ctx}, {"summary": f"tables: {', '.join(tables)}",
                                         "input": state["standalone_question"], "output": ctx}

    @traced("generate_sql")
    def generate_sql(state):
        feedback, retries = "", state.get("retries", 0)
        problem = state.get("validation_error") or state.get("exec_error")
        if problem:
            retries += 1
            feedback = (f"\nYour previous query was:\n{state.get('sql', '')}\n"
                        f"It failed with this error:\n{problem}\n"
                        "Write a corrected query that fixes this error.\n")
        prompt = render("sql_gen", schema_context=state.get("schema_context", ""),
                        doc_context=format_docs(state.get("doc_chunks", [])),
                        question=state["standalone_question"], error_feedback=feedback)
        sql = extract_sql(content_text(llm.invoke(prompt)))
        update = {"sql": sql, "retries": retries, "validation_error": None, "exec_error": None,
                  "approved": None, "requires_approval": False}
        label = f"retry {retries}/{MAX_RETRIES}" if problem else "first attempt"
        return update, {"summary": f"{label}: {sql[:120]}", "llm_calls": 1,
                        "input": feedback or state["standalone_question"], "output": sql}

    @traced("validate_sql")
    def validate_node(state):
        r = validate_sql(state["sql"])
        if not r.ok:
            return ({"validation_error": r.error},
                    {"summary": f"rejected: {r.error[:120]}", "success": False, "input": state["sql"], "output": r.error})
        sensitive = find_sensitive(r.cleaned_sql) if r.requires_approval else []
        summary = "ok" + (f", needs approval (sensitive: {', '.join(sensitive)})" if r.requires_approval else "")
        return ({"sql": r.cleaned_sql, "validation_error": None, "requires_approval": r.requires_approval,
                 "sensitive_columns": sensitive},
                {"summary": summary, "input": state["sql"], "output": r.cleaned_sql})

    @traced("approval")
    def approval(state):
        decision = interrupt({
            "type": "approval_request",
            "sql": state["sql"],
            "sensitive_columns": state.get("sensitive_columns", []),
            "message": "This query touches sensitive columns. Approve, edit, or reject it.",
        })
        if isinstance(decision, bool):
            decision = {"approved": decision}
        if not decision.get("approved"):
            return ({"approved": False, "fail_reason": "approval_declined"},
                    {"summary": "human declined; query will not run", "success": False, "input": state["sql"]})
        edited = (decision.get("sql") or "").strip()
        if edited and edited != state["sql"]:
            r = validate_sql(edited)  # an edited query gets the same checks as a generated one
            if not r.ok:
                return ({"approved": False, "validation_error": r.error,
                         "fail_reason": f"edited_sql_invalid: {r.error}"},
                        {"summary": f"human edited SQL but it failed validation: {r.error[:100]}",
                         "success": False, "input": edited, "output": r.error})
            return ({"approved": True, "sql": r.cleaned_sql},
                    {"summary": "human approved an edited query", "input": edited, "output": r.cleaned_sql})
        return {"approved": True}, {"summary": "human approved", "input": state["sql"]}

    @traced("execute_sql")
    def execute_sql(state):
        res = deps.run_fn(state["sql"])
        if not res.ok:
            return ({"exec_error": res.error, "rows": [], "columns": []},
                    {"summary": f"error: {res.error[:120]}", "success": False, "input": state["sql"],
                     "output": res.error})
        rows = [list(r) for r in res.rows]
        update = {"columns": list(res.columns), "rows": rows, "exec_error": None}
        if not rows and state.get("retries", 0) == 0:
            # Empty-result path: one retry with a hint, because a 0-row answer is often a wrong filter value.
            update["exec_error"] = ("The query ran but returned 0 rows. Check filter values (for example "
                                    "order_status spellings, date ranges, category names) and try a broader query.")
        return update, {"summary": f"{len(rows)} rows, {len(res.columns)} columns in {res.duration_ms} ms",
                        "success": True, "input": state["sql"], "output": rows[:5]}

    @traced("synthesize")
    def synthesize(state):
        ran_sql = state.get("sql", "") if state.get("columns") else ""
        prompt = render("synthesize", question=state["standalone_question"], sql=ran_sql,
                        results=format_results(state.get("columns", []), state.get("rows", [])),
                        documents=format_docs(state.get("doc_chunks", [])))
        answer = content_text(llm.invoke(prompt)).strip()
        return ({"answer": answer, "messages": [AIMessage(answer)]},
                {"summary": f"answer written ({len(answer)} chars)", "llm_calls": 1,
                 "input": f"rows={len(state.get('rows', []))}, chunks={len(state.get('doc_chunks', []))}",
                 "output": answer})

    @traced("out_of_scope")
    def out_of_scope(state):
        answer = ("I can only help with questions about this marketplace: order, delivery, payment, review, "
                  "seller and product data, and the company's policies and metric definitions. "
                  "Please ask something in that area.")
        return ({"answer": answer, "messages": [AIMessage(answer)]},
                {"summary": "declined: question is outside the business domain", "input": state["question"]})

    @traced("fail")
    def fail(state):
        reason = state.get("fail_reason") or ""
        if reason == "approval_declined":
            answer = ("I did not run the query because it uses sensitive columns "
                      f"({', '.join(state.get('sensitive_columns', [])) or 'personal data'}) and approval was declined.")
        elif reason.startswith("edited_sql_invalid"):
            answer = f"I did not run the edited query because it failed validation. {reason.split(': ', 1)[-1]}"
        elif state.get("validation_error") or state.get("exec_error"):
            answer = (f"I could not produce a working query after {state.get('retries', 0) + 1} attempts. "
                      f"Last query: {state.get('sql', '')} Last error: "
                      f"{state.get('validation_error') or state.get('exec_error')}")
        else:
            answer = f"Something went wrong while answering ({reason or 'unknown error'}). Please try again."
        return ({"answer": answer, "messages": [AIMessage(answer)], "fail_reason": reason or "retries_exhausted"},
                {"summary": f"failed: {reason or 'retries exhausted'}", "success": False, "output": answer})

    return {"router": router, "retrieve_docs": retrieve_docs, "retrieve_schema": retrieve_schema,
            "generate_sql": generate_sql, "validate_sql": validate_node, "approval": approval,
            "execute_sql": execute_sql, "synthesize": synthesize, "out_of_scope": out_of_scope, "fail": fail}
