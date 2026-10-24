"""Turn a finished graph state into what the Streamlit page shows. No Streamlit imports, so it is unit-testable."""
from __future__ import annotations

from typing import Any

# Kinds drive the banner shown above/instead of the normal answer.
ANSWER, EMPTY, OUT_OF_SCOPE, DECLINED, SQL_FAILED, SERVICE_ERROR, OTHER_ERROR = (
    "answer", "empty", "out_of_scope", "declined", "sql_failed", "service_error", "error")


def classify(state: dict) -> str:
    reason = state.get("fail_reason") or ""
    if reason:
        if reason == "approval_declined":
            return DECLINED
        if reason == "retries_exhausted":
            return SQL_FAILED
        if "crashed" in reason:
            return SERVICE_ERROR
        return OTHER_ERROR
    if state.get("route") == "OUT_OF_SCOPE":
        return OUT_OF_SCOPE
    if state.get("columns") and not state.get("rows"):
        return EMPTY
    return ANSWER


def friendly_message(kind: str, state: dict) -> str | None:
    """Short, non-technical text for the banner. The technical detail stays in the trace."""
    reason = (state.get("fail_reason") or "").lower()
    if kind == SERVICE_ERROR:
        if any(w in reason for w in ("429", "quota", "rate", "resource_exhausted")):
            return "The AI service is busy or its free-tier limit was reached. Please wait a minute and try again."
        if any(w in reason for w in ("504", "deadline", "timeout", "timed out", "503", "unavailable")):
            return "The AI service took too long to respond. Please try again in a moment."
        return "Something went wrong while talking to the AI service. Please try again."
    if kind == SQL_FAILED:
        return ("I couldn't build a working database query for this question after several attempts. "
                "Try rephrasing it, for example by naming the metric and the time period.")
    if kind == DECLINED:
        return "The query was not run because approval was declined."
    if kind == EMPTY:
        return ("The query ran successfully but returned no rows. There may be no data for that period or filter. "
                "Try a wider period or different filter.")
    if kind == OUT_OF_SCOPE:
        return "That question is outside what I can help with. I answer questions about this marketplace's data and policies."
    if kind == OTHER_ERROR:
        return "I couldn't complete that request. See the agent trace for details."
    return None


def citations(state: dict) -> list[dict]:
    """Unique document sections that were retrieved for this answer (best score first)."""
    seen, out = set(), []
    for c in sorted(state.get("doc_chunks", []), key=lambda c: -c["score"]):
        key = (c["source"], c["section"])
        if key not in seen:
            seen.add(key)
            out.append({"source": c["source"], "section": c["section"], "score": c["score"]})
    return out


def trace_rows(state: dict) -> list[dict[str, Any]]:
    return [
        {"#": i, "node": e["node"], "status": "ok" if e["success"] else "failed",
         "ms": e["duration_ms"], "LLM calls": e["llm_calls"], "summary": e["summary"]}
        for i, e in enumerate(state.get("trace", []), 1)
    ]


def trace_totals(state: dict) -> dict[str, Any]:
    entries = state.get("trace", [])
    return {"nodes": len(entries), "retries": state.get("retries", 0),
            "llm_calls": sum(e["llm_calls"] for e in entries),
            "total_ms": round(sum(e["duration_ms"] for e in entries), 1)}


def turn_from_state(state: dict, trace_path: str | None = None) -> dict:
    """Plain, serialisable record of one finished turn (what the chat history stores)."""
    kind = classify(state)
    return {
        "question": state.get("question", ""),
        "answer": state.get("answer", ""),
        "kind": kind,
        "banner": friendly_message(kind, state),
        "route": state.get("route", ""),
        "route_reason": state.get("route_reason", ""),
        "standalone_question": state.get("standalone_question", ""),
        "sql": state.get("sql", "") if state.get("columns") or kind in (SQL_FAILED, DECLINED) else "",
        "columns": state.get("columns", []),
        "rows": state.get("rows", []),
        "citations": citations(state),
        "trace_rows": trace_rows(state),
        "totals": trace_totals(state),
        "trace_path": trace_path,
    }
