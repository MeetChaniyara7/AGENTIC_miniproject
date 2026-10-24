# Hybrid Analyst: rules for Claude

University mini project (Agentic AI, B.Tech CSE, Karnavati University). Full description: `docs/project-brief.md`.

## Stack
Python 3.11+, LangChain, LangGraph, SQLite (database), ChromaDB (vector store), sentence-transformers (local embeddings), Streamlit (UI), pytest, Google Gemini free tier (`langchain-google-genai`) as the primary LLM, Groq free tier (`langchain-groq`) as a hosted backup, Ollama (`langchain-ollama`) as the local fallback.

- Free providers only. The provider is chosen by `LLM_PROVIDER` in `.env` (`gemini`, `groq` or `ollama`). Hugging Face (`langchain-huggingface`) is an approved optional third provider, added only if needed.
- Cache LLM responses on disk during evaluation so reruns don't burn quota. Traces record real call counts and cache hits.
- Put the LLM and embedding choice behind one config module so it can be swapped.
- Keys live only in `.env`. Keep `.env.example` current.
- Ask before adding any dependency not listed above.

## Code style
- Small, clearly named files.
- Short comments explaining key decisions (the why, not the what).

## Tracing and metrics
- Everything the agent does is logged as a structured JSON trace: each node, tool call, input, output, success flag, duration. The report needs real numbers.
- Never fabricate results. All metrics come from files written by the evaluation harness.

## Agentic concepts
Only implement concepts that are real: planning, ReAct, tool calling, RAG, memory, multi-agent (supervisor + specialists), human-in-the-loop. Do not label something with a concept it does not actually implement.

## Agent design (LangGraph)
- **Planner/Supervisor**: reads the question, produces a plan of subtasks, each typed `SQL | DOCS | CALC`, and routes between agents.
- **SQL Analyst** (ReAct loop, max 3 retries): schema_lookup -> write SQL -> validate -> run_sql -> observe -> fix or finish.
- **Document Researcher**: doc_search -> grade relevance -> rewrite query once or twice if poor -> return chunks with sources.
- **Reviewer**: checks the draft answer is supported by the SQL results and retrieved chunks; sends it back if not.
- **Human-in-the-loop**: graph pauses (LangGraph interrupt) when the question is ambiguous (e.g. no time period) or a query is unusually broad; resumes after the user approves or edits.
- **Memory**: per-thread conversation state (LangGraph checkpointer) and a long-term store of user-approved question->SQL pairs, retrieved as few-shot examples.

## Phases
1. Scaffold + Olist data + synthetic policy docs
2. RAG pipeline
3. Tools
4. LangGraph agent
5. Streamlit UI
6. Evaluation harness
7. Project report

## End of every phase
Run tests, then reply with: what changed, how to run it, what is left. Then STOP and wait for the user's approval before starting the next phase.
