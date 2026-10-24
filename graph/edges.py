"""Conditional edges. Pure functions of the state, so they are easy to test.

Every edge first checks fail_reason: a crashed node or a declined approval sends
the turn straight to the fail node instead of continuing with half a state.
"""
from __future__ import annotations

from graph.state import MAX_RETRIES


def _failed(state) -> bool:
    return bool(state.get("fail_reason"))


def after_router(state) -> str:
    if _failed(state):
        return "fail"
    route = state.get("route")
    if route == "OUT_OF_SCOPE":
        return "out_of_scope"
    return "retrieve_schema" if route == "SQL" else "retrieve_docs"  # DOCS and BOTH both read the documents first


def after_docs(state) -> str:
    if _failed(state):
        return "fail"
    return "retrieve_schema" if state.get("route") == "BOTH" else "synthesize"


def after_schema(state) -> str:
    return "fail" if _failed(state) else "generate_sql"


def after_generate(state) -> str:
    return "fail" if _failed(state) else "validate_sql"


def _retry_or_fail(state) -> str:
    # `retries` counts regenerations already done; after MAX_RETRIES the next failure is final.
    return "fail" if state.get("retries", 0) >= MAX_RETRIES else "generate_sql"


def after_validate(state) -> str:
    if _failed(state):
        return "fail"
    if state.get("validation_error"):
        return _retry_or_fail(state)
    # Approval gate: only asked once per generated query.
    if state.get("requires_approval") and not state.get("approved"):
        return "approval"
    return "execute_sql"


def after_approval(state) -> str:
    # Declined or invalid edit sets fail_reason, so execution is skipped.
    return "fail" if _failed(state) or not state.get("approved") else "execute_sql"


def after_execute(state) -> str:
    if _failed(state):
        return "fail"
    if state.get("exec_error"):           # real SQL error, or the one-shot empty-result hint
        return _retry_or_fail(state)
    return "synthesize"
