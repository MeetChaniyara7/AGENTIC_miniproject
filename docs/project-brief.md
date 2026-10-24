# Project Brief: Hybrid Analyst

Course: Agentic AI, B.Tech CSE, Karnavati University (mini project).

## Goal
An agentic system that answers business questions by combining two sources:
- **Structured data**: Text-to-SQL over the Olist e-commerce SQLite database (public Kaggle dataset).
- **Unstructured data**: RAG over synthetic company policy documents (refunds, delivery SLA, seller rules, review moderation, data dictionary, metrics glossary).

Example: *"Why did refunds spike last week?"* The SQL side finds that refunds rose and where (product, region, day). The document side finds a likely cause (e.g. a faulty release or a policy change). The answer combines both, with evidence cited.

## Stack
Python 3.11+, LangChain, LangGraph, SQLite, ChromaDB, sentence-transformers (local embeddings), Streamlit, pytest, Google Gemini free tier as the primary LLM with Ollama as a local fallback (chosen by `LLM_PROVIDER` in `.env`). Responses are cached on disk during evaluation to stay within free-tier limits. LLM and embedding choice sit behind one config module; secrets only in `.env`.

## Agent design (LangGraph)

| Node / agent | Role |
|---|---|
| Planner/Supervisor | Reads the question, produces a plan of subtasks typed `SQL`, `DOCS` or `CALC`, and routes between agents. |
| SQL Analyst | ReAct loop, max 3 retries: schema_lookup -> write SQL -> validate -> run_sql -> observe -> fix or finish. |
| Document Researcher | doc_search -> grade relevance -> rewrite query once or twice if poor -> return chunks with sources. |
| Reviewer | Checks the draft answer is supported by SQL results and retrieved chunks; sends it back if not. |
| Human-in-the-loop | Graph pauses (LangGraph interrupt) on ambiguous questions (e.g. no time period) or unusually broad queries; resumes after the user approves or edits. |

### Memory
- **Short-term**: conversation state per thread via a LangGraph checkpointer.
- **Long-term**: store of user-approved question->SQL pairs, retrieved as few-shot examples for the SQL Analyst.

### Agentic concepts actually used
Planning, ReAct, tool calling, RAG, memory, multi-agent (supervisor + specialists), human-in-the-loop.

## Observability
Every run writes a structured JSON trace: each node, tool call, input, output, success flag, duration. All reported metrics come from files written by the evaluation harness, never typed in by hand.

## Phases

| # | Phase | Outcome |
|---|---|---|
| 1 | Scaffold + Olist data + synthetic policy docs | Repo layout, config module, `.env.example`, SQLite DB and sample documents. |
| 2 | RAG pipeline | Chunking, local embeddings, ChromaDB index, retrieval. |
| 3 | Tools | schema_lookup, validate/run_sql, doc_search, calculator, each traced. |
| 4 | LangGraph agent | Planner, SQL Analyst, Document Researcher, Reviewer, HITL, memory. |
| 5 | Streamlit UI | Chat, plan/trace view, approve/edit prompt for interrupts. |
| 6 | Evaluation harness | Question set with expected answers; writes metrics files. |
| 7 | Project report | Report built from real harness output and traces. |

Each phase ends with tests passing, a summary (what changed, how to run, what is left), and a stop for approval.
