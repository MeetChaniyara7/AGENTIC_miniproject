"""Shared state for the Hybrid Analyst graph.

Per-turn fields are reset by new_turn() at the start of every question. The
checkpointer keeps the state per thread, so only `messages` (the conversation)
carries over between turns; everything else describes the current question.
"""
from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage, HumanMessage
from langgraph.graph.message import add_messages

MAX_RETRIES = 3  # SQL regenerations after the first attempt


class AgentState(TypedDict, total=False):
    question: str                       # what the user typed this turn
    standalone_question: str            # rewritten by the router using conversation memory
    messages: Annotated[list[AnyMessage], add_messages]  # conversation memory (per thread)
    route: str                          # SQL | DOCS | BOTH | OUT_OF_SCOPE
    route_reason: str
    sub_tasks: list[dict]               # [{"type": "SQL"|"DOCS", "task": str}]
    schema_context: str                 # tables + similar example queries
    doc_chunks: list[dict]              # {text, source, section, score}
    sql: str                            # latest SQL (cleaned by the validator once it passes)
    validation_error: str | None
    requires_approval: bool
    sensitive_columns: list[str]
    approved: bool | None               # None = not asked yet
    exec_error: str | None
    columns: list[str]
    rows: list[list[Any]]
    retries: int                        # SQL regenerations so far this turn
    fail_reason: str | None             # set when the turn must end in the fail node
    answer: str
    trace: list[dict]                   # one entry per executed node


def new_turn(question: str) -> dict:
    """Input for graph.invoke(): resets per-turn fields, appends the question to memory."""
    return {
        "question": question,
        "messages": [HumanMessage(question)],
        "standalone_question": question,
        "route": "", "route_reason": "", "sub_tasks": [],
        "schema_context": "", "doc_chunks": [],
        "sql": "", "validation_error": None, "requires_approval": False, "sensitive_columns": [],
        "approved": None, "exec_error": None, "columns": [], "rows": [],
        "retries": 0, "fail_reason": None, "answer": "", "trace": [],
    }
