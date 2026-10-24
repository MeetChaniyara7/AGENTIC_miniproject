# Viva cheat-sheet: Hybrid Analyst

25 likely questions with short answers based on this code. Numbers come from `evaluation/summary.md` (one run of 30 questions on Groq `openai/gpt-oss-120b`); quote them with that caveat.

## The idea

**1. What problem does your project solve?**
Business questions often need numbers from a database *and* rules from policy documents (for example "is our cancellation rate above the escalation threshold?"). Hybrid Analyst decides which sources a question needs, queries the data safely, retrieves the policy text, and writes one cited answer.

**2. Why not just one LLM prompt?**
A single prompt cannot read documents, cannot recover from a failed query, and runs whatever SQL it is given. We measured this with a baseline: it matched our SQL accuracy (14 of 18) but could not do documents, safety or recovery, and had no trace. Our agent was slower (14.3 s against 5.0 s on those questions).

**3. Is it a multi-agent system?**
No. It is one agent: a single LangGraph graph with one shared state. The nodes are steps of one workflow, not independent agents. There is no supervisor, specialist agents or reviewer; those are future work.

**4. What agentic concepts are actually implemented?**
Routing/task decomposition into fixed paths, a ReAct-style repair loop, tool use (orchestrated by the graph), RAG, per-thread conversation memory, human-in-the-loop approval, and tracing. Not implemented: multi-agent, long-term memory, a reviewer, dynamic planning.

## Architecture and workflow

**5. Walk me through one question.**
`router` picks SQL, DOCS, BOTH or OUT_OF_SCOPE and rewrites the question. DOCS: `retrieve_docs` then `synthesize`. SQL: `retrieve_schema`, `generate_sql`, `validate_sql`, (`approval`), `execute_sql`, `synthesize`. BOTH: documents first, then the SQL path. Failures go to `fail`. See `graph/build_graph.py` and Figure 2 of the report.

**6. Why LangGraph?**
It makes control flow an explicit graph: shared state, conditional edges, a checkpointer for memory, and `interrupt` for human approval. Edge functions in `graph/edges.py` are plain functions of the state, so they are easy to unit-test.

**7. How does the router work, and what if its output is bad?**
`prompts/router.txt` asks the LLM for JSON with `route`, `rewritten_question`, `sub_tasks` and `reason`. The parser tolerates code fences. If the JSON is invalid or the route is unknown, the system falls back to BOTH and records the step as failed in the trace.

**8. What is the "plan"? Do you do planning?**
Only in a limited sense: the route chosen by the router is the plan. The router also returns a list of sub-tasks, but the graph does not execute that list; it is recorded for transparency. There is no plan-and-execute loop.

**9. Is this ReAct?**
Partly. The SQL loop is generate (reason), validate and execute (act), observe the error, and regenerate. But the order of tools is fixed by the graph; the LLM does not choose tools or write its own thoughts between actions. So it is ReAct-style, not full ReAct.

**10. Do you use native tool calling?**
No. The four tools (`retrieve_docs`, `search_schema`, `validate_sql`, `run_sql`) are called by graph nodes. The route from the LLM router and deterministic edges decide which tools run.

## SQL path and safety

**11. How does the retry loop work?**
When validation or execution fails, the error text and failed query are inserted into the SQL prompt and `generate_sql` runs again. `retries` counts regenerations; `MAX_RETRIES = 3`, so there are at most 4 generations (the first plus 3 retries), then the `fail` node. A first empty result gets one retry with a hint to check filters.

**12. What does `validate_sql` check?**
With sqlglot (SQLite dialect): exactly one statement and it must be a SELECT or UNION; no comments; only allow-listed tables (no `main.orders`, no `pragma_table_info(...)`); no `load_extension` and similar functions; LIMIT added if missing and capped at 200; `LIMIT -1` rejected; sensitive columns flagged. Errors are worded so an LLM can fix the query (for example "did you mean 'order_items'?").

**13. Why reject `LIMIT -1`?**
In SQLite a negative limit means "no limit", which would bypass the row cap.

**14. How is execution made safe?**
`run_sql` opens SQLite with `mode=ro`, so even a query that slipped past the validator cannot write. A progress handler aborts queries longer than 10 seconds, and rows are capped. The tests confirm a `DELETE` fails on the read-only connection.

**15. How does human-in-the-loop work?**
If the query reads a sensitive column outside an aggregate (`customer_unique_id`, `customer_zip_code_prefix`, `geolocation_lat`, `geolocation_lng`), the `approval` node calls LangGraph's `interrupt`. The UI shows the SQL with Approve and Reject; the graph resumes with the decision. Reject ends in `fail` and the query never runs. `COUNT(DISTINCT customer_unique_id)` needs no approval.

**16. Did the safety tests really test the approval gate?**
No, and the report says so. 3 of the 4 safety requests were refused by the router; the PII request was stopped because the model wrote a refusal sentence as "SQL", which the validator rejected four times. The approval gate and validator are covered by automated tests, not by the live safety questions.

## RAG and memory

**17. Explain your RAG pipeline.**
Six synthetic policy documents are split by heading, then into about 500-character chunks with 80 overlap (heading kept as metadata), embedded locally with `all-MiniLM-L6-v2`, and stored in a persistent ChromaDB collection (cosine). At query time the top 4 chunks are retrieved and chunks scoring below 0.30 are dropped. Code: `rag/ingest_docs.py`, `tools/doc_retriever.py`.

**18. How did you choose the 0.30 threshold?**
From measurements in Phase 2: relevant questions scored 0.39 to 0.77 on their best chunk, off-topic ones 0.12 to 0.20, so 0.30 separates them. It is not tuned further.

**19. What else is in the vector store?**
Two more collections: `schema_notes` (one entry per table and per column) and `example_queries` (12 question and SQL pairs). `search_schema` ranks tables by their best-matching column or table entry, because long table descriptions alone scored poorly against short questions.

**20. How does memory work?**
A LangGraph `MemorySaver` checkpointer keyed by `thread_id` keeps the `messages` list. The router prompt includes the last six previous messages and rewrites "and in 2018?" into a full question. Limits: it is in process memory (lost on restart) and there is no long-term memory.

## Evaluation and results

**21. How did you evaluate it?**
30 questions: 10 SQL, 8 document, 8 hybrid, 4 safety. SQL passes if the result set equals a verified reference query's result; document questions need the expected file in the top 4 and all keywords in the answer; hybrid needs both; safety needs the request blocked. Everything is written by `evaluation/run_eval.py` into `results.csv` and `summary.md`.

**22. What were the results?**
Accuracy 76.7% (23/30), task completion 100% (26/26), SQL accuracy 77.8% (14/18), tool success 93.5% (72/77), route accuracy 100%, retrieval 100% (file-level), safety 4/4, mean time 12.0 s (hybrid 22.4 s), and 182 of 182 automated tests passing. It is a single run on one model.

**23. Why did the 7 questions fail?**
Three were retrieval depth: the right file was retrieved but the answer passage was outside the top 4 chunks. Three were ambiguity or rounding (one SQL prompt rule over-applied, two rounding differences). One was a genuine SQL error: an inner join dropped canceled orders that have no items (461 instead of 625).

**24. Why does the retrieval figure say 100% if three answers lacked the passage?**
Because the metric is file-level: the right file appeared in the top 4. It does not prove the right passage did. We report this limitation; a chunk-level metric is future work.

## Limits and future work

**25. What are the main limitations and what would you do next?**
Limits: single agent with fixed paths, no reviewer, no long-term memory, no pause for ambiguous questions, dependence on a free-tier LLM (Gemini's free tier allowed 20 requests per day; Groq latency 10 to 15 s per call), synthetic documents, and Olist data that effectively ends in August 2018. Next: a reviewer agent, long-term memory of approved SQL, deeper or hybrid retrieval, executing the router's sub-tasks, and a persistent checkpointer.

## Quick reference

| Item | Where |
|---|---|
| Graph assembly | `graph/build_graph.py` |
| Nodes | `graph/nodes.py` |
| Routing rules and retry cap | `graph/edges.py` |
| State | `graph/state.py` |
| Tracing | `graph/trace.py` |
| SQL validator | `tools/sql_validator.py` |
| SQL executor | `tools/sql_executor.py` |
| Document / schema retrieval | `tools/doc_retriever.py`, `tools/schema_search.py` |
| Provider and embedding choice | `config.py` |
| Evaluation | `evaluation/` |
