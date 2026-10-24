"""Assemble and compile the LangGraph.

    router -> OUT_OF_SCOPE -> out_of_scope -> END
           -> DOCS  -> retrieve_docs -> synthesize -> END
           -> SQL   -> retrieve_schema -> generate_sql -> validate_sql -> [approval] -> execute_sql -> synthesize
           -> BOTH  -> retrieve_docs -> retrieve_schema -> (same SQL loop)
    validate/execute failures loop back to generate_sql (max 3 retries) and then go to fail.
"""
from __future__ import annotations

from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from graph import edges
from graph.nodes import Deps, make_nodes
from graph.state import AgentState


def default_deps(llm=None, persist_dir: Path | None = None, db_path: Path | None = None) -> Deps:
    from config import get_chat_model
    from tools.doc_retriever import retrieve_docs
    from tools.schema_search import search_schema
    from tools.sql_executor import run_sql

    return Deps(
        llm=llm or get_chat_model(),
        docs_fn=lambda q: retrieve_docs(q, k=4, persist_dir=persist_dir),
        schema_fn=lambda q: search_schema(q, persist_dir=persist_dir),
        run_fn=lambda sql: run_sql(sql, db_path),
    )


def build_graph(deps: Deps | None = None, checkpointer=None):
    nodes = make_nodes(deps or default_deps())
    g = StateGraph(AgentState)
    for name, fn in nodes.items():
        g.add_node(name, fn)

    g.add_edge(START, "router")
    g.add_conditional_edges("router", edges.after_router,
                            ["retrieve_docs", "retrieve_schema", "out_of_scope", "fail"])
    g.add_conditional_edges("retrieve_docs", edges.after_docs, ["retrieve_schema", "synthesize", "fail"])
    g.add_conditional_edges("retrieve_schema", edges.after_schema, ["generate_sql", "fail"])
    g.add_conditional_edges("generate_sql", edges.after_generate, ["validate_sql", "fail"])
    g.add_conditional_edges("validate_sql", edges.after_validate,
                            ["generate_sql", "approval", "execute_sql", "fail"])
    g.add_conditional_edges("approval", edges.after_approval, ["execute_sql", "fail"])
    g.add_conditional_edges("execute_sql", edges.after_execute, ["generate_sql", "synthesize", "fail"])
    for terminal in ("synthesize", "out_of_scope", "fail"):
        g.add_edge(terminal, END)

    # MemorySaver = per-thread conversation memory held in process memory (lost on restart).
    return g.compile(checkpointer=checkpointer or MemorySaver())
