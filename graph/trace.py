"""Structured tracing for graph nodes.

Every node is wrapped by @traced(name). It records node, summary, success flag,
duration, number of LLM calls and a clipped input/output into state["trace"], and
turns unexpected exceptions into a fail_reason so one broken node ends the turn
cleanly instead of crashing the app. write_trace() saves the JSON for the report.
"""
from __future__ import annotations

import functools
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from langgraph.errors import GraphBubbleUp

CLIP = 2000  # long enough for a full generated SQL query


def clip(value, limit: int = CLIP):
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= limit else text[:limit] + f"... [{len(text)} chars]"


def traced(name: str) -> Callable:
    """Wrap fn(state) -> (state_update, info). info keys: summary, success, llm_calls, input, output."""
    def deco(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(state: dict) -> dict:
            start = time.perf_counter()
            try:
                update, info = fn(state)
            except GraphBubbleUp:      # human-in-the-loop interrupts must pass through untouched
                raise
            except Exception as e:     # noqa: BLE001 - any node failure should end the turn gracefully
                update = {"fail_reason": f"{name} crashed: {type(e).__name__}: {e}"}
                info = {"summary": f"exception: {type(e).__name__}: {e}", "success": False}
            entry = {
                "node": name,
                "summary": info["summary"],
                "success": info.get("success", True),
                "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                "llm_calls": info.get("llm_calls", 0),
                "input": clip(info.get("input")),
                "output": clip(info.get("output")),
            }
            return {**update, "trace": state.get("trace", []) + [entry]}
        return wrapper
    return deco


def write_trace(state: dict, thread_id: str, trace_dir: Path) -> Path:
    trace_dir.mkdir(parents=True, exist_ok=True)
    entries = state.get("trace", [])
    record = {
        "thread_id": thread_id,
        "question": state.get("question"),
        "route": state.get("route"),
        "answer": state.get("answer"),
        "totals": {
            "nodes": len(entries),
            "llm_calls": sum(e["llm_calls"] for e in entries),
            "duration_ms": round(sum(e["duration_ms"] for e in entries), 1),
            "retries": state.get("retries", 0),
            "success": not state.get("fail_reason"),
        },
        "trace": entries,
    }
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = trace_dir / f"{thread_id}-{stamp}.json"
    path.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    return path
