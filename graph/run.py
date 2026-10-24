"""Quick CLI: python -m graph.run "question 1" "question 2" --thread t1 [--approve ask|yes|no]

Several questions in one call share the same thread, so follow-ups use memory.
Each turn's JSON trace is saved to traces/.
"""
from __future__ import annotations

import argparse
from typing import Callable

from langgraph.types import Command

from config import get_settings
from graph.state import new_turn
from graph.trace import write_trace


def ask(graph, question: str, thread_id: str, approver: Callable[[dict], dict] | None = None) -> dict:
    """Run one turn. If the graph pauses for approval, `approver(payload)` supplies the decision."""
    cfg = {"configurable": {"thread_id": thread_id}}
    result = graph.invoke(new_turn(question), cfg)
    while result.get("__interrupt__"):
        payload = result["__interrupt__"][0].value
        if approver is None:
            return result  # caller (UI or test) will resume with Command(resume=...)
        result = graph.invoke(Command(resume=approver(payload)), cfg)
    return result


def cli_approver(mode: str) -> Callable[[dict], dict]:
    def decide(payload: dict) -> dict:
        print(f"\n  APPROVAL NEEDED: {payload['message']}\n  sensitive: {payload['sensitive_columns']}\n  SQL: {payload['sql']}")
        if mode == "yes":
            return {"approved": True}
        if mode == "no":
            return {"approved": False}
        answer = input("  approve? [y/N/e=edit]: ").strip().lower()
        if answer == "e":
            return {"approved": True, "sql": input("  new SQL: ").strip()}
        return {"approved": answer == "y"}
    return decide


def print_turn(state: dict) -> None:
    print(f"\nROUTE: {state.get('route')} | {state.get('route_reason', '')}")
    if state.get("standalone_question") != state.get("question"):
        print(f"REWRITTEN: {state['standalone_question']}")
    print("TRACE:")
    for i, e in enumerate(state["trace"], 1):
        flag = "ok  " if e["success"] else "FAIL"
        print(f"  {i:>2}. {flag} {e['node']:<16}{e['duration_ms']:>9.1f} ms  llm={e['llm_calls']}  {e['summary']}")
    print(f"\nANSWER:\n{state['answer']}\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("questions", nargs="+")
    ap.add_argument("--thread", default="cli")
    ap.add_argument("--approve", choices=["ask", "yes", "no"], default="ask")
    args = ap.parse_args()

    from graph.build_graph import build_graph  # imported late: loads the embedding model
    graph = build_graph()
    for q in args.questions:
        print("=" * 100 + f"\nQUESTION: {q}")
        state = ask(graph, q, args.thread, cli_approver(args.approve))
        print_turn(state)
        print(f"trace saved: {write_trace(state, args.thread, get_settings().trace_dir)}")


if __name__ == "__main__":
    main()
