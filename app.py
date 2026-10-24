"""Hybrid Analyst: Streamlit chat UI.   Run: streamlit run app.py

All agent logic lives in graph/; this file only renders state and forwards the
user's choices (questions, approve/reject) to the graph.
"""
from __future__ import annotations

import uuid

import pandas as pd
import streamlit as st
from langgraph.types import Command

from config import get_settings
from graph.run import ask
from graph.trace import write_trace
from graph.ui_support import DECLINED, EMPTY, OUT_OF_SCOPE, turn_from_state

st.set_page_config(page_title="Hybrid Analyst", page_icon="📊", layout="centered")

EXAMPLES = [
    ("Data", "How many orders were placed each month in 2017?"),
    ("Policy", "What does our refund policy say about a product that arrives damaged?"),
    ("Data + policy", "Which month had the highest cancellation rate, and is that above our escalation threshold?"),
    ("Why question", "Why was the late delivery rate so high in March 2018?"),
    ("Flagship", "Why did refunds spike last week?"),
    ("Needs approval", "List the unique customer IDs of buyers located in Sao Paulo state"),
    ("Out of scope", "What is the capital of France?"),
]


@st.cache_resource(show_spinner="Loading the agent...")
def get_graph():
    # One graph (and one in-memory checkpointer) is shared by all browser sessions;
    # conversations stay separate because each session uses its own thread_id.
    from graph.build_graph import build_graph
    return build_graph()


def new_thread() -> None:
    st.session_state.thread_id = uuid.uuid4().hex[:8]
    st.session_state.turns = []
    st.session_state.pending = None


def model_label() -> str:
    s = get_settings()
    model = {"gemini": s.gemini_model, "groq": s.groq_model, "ollama": s.ollama_model}.get(s.provider, "?")
    return f"{s.provider} / {model}"


def finish_turn(state: dict) -> None:
    path = write_trace(state, st.session_state.thread_id, get_settings().trace_dir)
    st.session_state.turns.append(turn_from_state(state, str(path)))


def run_turn(question: str) -> None:
    cfg_thread = st.session_state.thread_id
    with st.spinner("Routing, retrieving and querying..."):
        state = ask(get_graph(), question, cfg_thread)  # no approver: returns at an interrupt
    if state.get("__interrupt__"):
        st.session_state.pending = {"question": question, "payload": state["__interrupt__"][0].value}
    else:
        finish_turn(state)


def resume_turn(approved: bool) -> None:
    cfg = {"configurable": {"thread_id": st.session_state.thread_id}}
    with st.spinner("Resuming..."):
        state = get_graph().invoke(Command(resume={"approved": approved}), cfg)
    st.session_state.pending = None
    finish_turn(state)


def render_turn(turn: dict) -> None:
    with st.chat_message("user"):
        st.markdown(turn["question"])
    with st.chat_message("assistant"):
        banner = turn["banner"]
        if banner:
            (st.info if turn["kind"] in (EMPTY, OUT_OF_SCOPE, DECLINED) else st.error)(banner)
        # (a) final answer. Failures already show a friendly banner, so the raw failure text stays in the trace.
        if turn["kind"] not in ("service_error", "error", "sql_failed"):
            st.markdown(turn["answer"])
        # (b) SQL
        if turn["sql"]:
            with st.expander("SQL used", expanded=turn["kind"] != "answer"):
                st.code(turn["sql"], language="sql")
        # (c) result table
        if turn["rows"]:
            st.dataframe(pd.DataFrame(turn["rows"], columns=turn["columns"]), hide_index=True, width="stretch")
        # (d) citations
        if turn["citations"]:
            st.caption("Sources retrieved")
            for c in turn["citations"]:
                st.markdown(f"- 📄 **{c['source']}** — {c['section']} (relevance {c['score']:.2f})")
        # (e) trace
        t = turn["totals"]
        label = (f"Agent trace · route {turn['route'] or '?'} · {t['nodes']} steps · "
                 f"{t['retries']} retries · {t['llm_calls']} LLM calls · {t['total_ms'] / 1000:.1f}s")
        with st.expander(label):
            if turn["route_reason"]:
                st.caption(f"Router: {turn['route_reason']}")
            if turn["standalone_question"] and turn["standalone_question"] != turn["question"]:
                st.caption(f"Understood as: {turn['standalone_question']}")
            st.dataframe(pd.DataFrame(turn["trace_rows"]), hide_index=True, width="stretch")
            if turn["trace_path"]:
                st.caption(f"Saved: {turn['trace_path']}")


def render_approval() -> None:
    pending = st.session_state.pending
    with st.chat_message("user"):
        st.markdown(pending["question"])
    with st.chat_message("assistant"):
        st.warning("**Approval needed.** This query reads sensitive columns "
                   f"({', '.join(pending['payload']['sensitive_columns']) or 'personal data'}). "
                   "Review the SQL and choose whether it may run.")
        st.code(pending["payload"]["sql"], language="sql")
        approve, reject, _ = st.columns([1, 1, 3])
        if approve.button("Approve", type="primary", key="approve"):
            resume_turn(True)
            st.rerun()
        if reject.button("Reject", key="reject"):
            resume_turn(False)
            st.rerun()


# ------------------------------------------------------------------ page
if "thread_id" not in st.session_state:
    new_thread()

with st.sidebar:
    st.header("Hybrid Analyst")
    st.caption("Answers business questions by combining SQL over the Olist database with search over company policy documents.")
    st.markdown(f"**Model**  \n`{model_label()}`")
    st.markdown(f"**Conversation**  \n`{st.session_state.thread_id}`")
    if st.button("New conversation", width="stretch"):
        new_thread()
        st.rerun()
    st.divider()
    st.subheader("Example questions")
    for tag, question in EXAMPLES:
        if st.button(f"{tag}: {question}", key=f"ex-{tag}", width="stretch",
                     disabled=bool(st.session_state.pending)):
            st.session_state.queued = question

st.title("📊 Hybrid Analyst")
if not st.session_state.turns and not st.session_state.pending:
    st.markdown("Ask about orders, delivery, reviews, sellers or company policy. "
                "Pick an example in the sidebar or type your own question below. "
                "Follow-up questions like *“and in 2018?”* use the conversation so far.")

for turn in st.session_state.turns:
    render_turn(turn)
if st.session_state.pending:
    render_approval()

prompt = st.chat_input("Ask a question about the marketplace...", disabled=bool(st.session_state.pending))
prompt = prompt or st.session_state.pop("queued", None)
if prompt and not st.session_state.pending:
    run_turn(prompt)
    st.rerun()
