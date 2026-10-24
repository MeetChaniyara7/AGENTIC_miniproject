# Hybrid Analyst

An agentic AI system that answers business questions about an e-commerce marketplace by combining **Text-to-SQL** over a SQLite database (the public Olist dataset) with **retrieval-augmented generation (RAG)** over company policy documents.

*Example:* "What was the cancellation rate in August 2018, and does it exceed the escalation threshold in the refund policy?" The agent queries the database for the rate, retrieves the policy passage that defines the threshold, and writes one cited answer.

University mini project for the course **Agentic AI** (B.Tech CSE, Karnavati University). The course report is built from this repository: see [Building the report](#building-the-report).

## What it does

- **Router** (LLM) sends each question to the SQL path, the document path, both, or refuses it as out of scope, and rewrites follow-up questions using the conversation so far.
- **SQL path:** retrieve relevant schema and similar example queries, generate SQLite, validate it with sqlglot, run it on a read-only connection (10 s timeout), and repair it from the error message up to 3 times.
- **Document path:** search six policy documents stored in ChromaDB (local embeddings) and cite the file names.
- **Human-in-the-loop:** queries that read sensitive columns pause the graph (LangGraph interrupt) until the user approves or rejects.
- **Memory:** per-thread conversation memory (LangGraph `MemorySaver`, held in process memory).
- **Tracing:** every node, with duration, success flag and LLM calls, is saved as a JSON trace in `traces/`.
- **UI:** a Streamlit chat page showing the answer, the SQL, the result table, the sources and the agent trace.

What is **not** implemented: multiple cooperating agents, a reviewer step, long-term memory, document relevance grading and query rewriting, and a pause for ambiguous questions.

## Requirements

- Python 3.11 or newer (developed on 3.12).
- About 2 GB of disk space (CPU-only PyTorch keeps it small).
- Internet access for the hosted LLM and for the first download of the embedding model (`all-MiniLM-L6-v2`, about 90 MB).
- A free API key for **Groq** (recommended) or **Google Gemini**. Note that Gemini's free tier allowed only 20 requests per day for the model we used, which is too few for the evaluation. A local Ollama option is coded in `config.py` but has not been tested.

## Setup

```
python -m venv .venv
.venv\Scripts\activate                     # Windows; on Linux/macOS: source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu     # optional: smaller CPU-only build
pip install -r requirements.txt
copy .env.example .env                     # cp .env.example .env on Linux/macOS
```

Edit `.env`: set `LLM_PROVIDER` to `groq` or `gemini` and add the matching key (`GROQ_API_KEY` or `GOOGLE_API_KEY`). Keys live only in `.env`, which is excluded from version control. Model names are in `.env.example` (`GROQ_MODEL`, `GEMINI_MODEL`); provider model names change over time, so check the provider's list if you get a "model not found" error.

## Data (one-time)

1. Download the **Brazilian E-Commerce Public Dataset by Olist** from Kaggle and put the 9 CSV files in `data/raw/`.
2. Build the database and check the example queries:

```
python scripts/load_olist.py
python scripts/verify_examples.py
```

3. Index the documents, schema notes and example queries into ChromaDB:

```
python -m rag.ingest_docs
python -m rag.ingest_schema
```

The six documents in `data/docs/` are **synthetic**: they were written for this project and are not real Olist policies.

## Run

Web interface:

```
streamlit run app.py
```

Command line (several questions in one call share a conversation, so follow-ups use memory):

```
python -m graph.run "How many orders were placed in 2017?" "And in 2018?" --thread demo
python -m graph.run "List the unique customer IDs of buyers in Sao Paulo state" --approve ask
```

Try retrieval by hand:

```
python -m rag.try "What compensation does a customer get for a late delivery?" --raw
```

To use another provider for one command without editing `.env` (Windows): `set LLM_PROVIDER=groq`.

## Evaluate

The harness runs 30 questions (10 SQL, 8 documents, 8 hybrid, 4 safety) through the agent and a single-prompt baseline. LLM responses are cached on disk in `llm_cache/`, so an interrupted run resumes cheaply.

```
python -m evaluation.run_eval            # writes evaluation/results.csv, results_detail.json, baseline_results.csv, summary.md, traces/
python -m evaluation.report              # regenerates summary.md from results_detail.json without re-running anything
```

All reported metrics come from these files; nothing is typed in by hand. See `evaluation/summary.md` for the results of the last run, including every failed question and its likely cause.

## Test

```
python -m pytest -q
```

The tests use a tiny fake dataset (`tests/olist_fixture.py`), a fake LLM and Streamlit's `AppTest`, so they need no network, API key or Kaggle download. Some tests load the embedding model.

## Building the report

```
python report/build_diagrams.py          # Figures 1-3 (Figure 2 is read from the compiled LangGraph, Figure 3 from a real trace)
python report/build_report.py            # report/Hybrid_Analyst_Mini_Project_Report.docx
```

The `.docx` is written with the Python standard library only (no python-docx); the diagrams use Pillow, which Streamlit already installs. Open the `.docx` in Word, allow it to update fields (or right-click the contents and lists and choose Update Field), and insert your screenshots where the `[Insert Screenshot: ...]` boxes are; `report/screenshots_needed.json` lists them all.

## Project layout

| Path | Purpose |
|---|---|
| `app.py` | Streamlit chat interface |
| `config.py` | LLM and embedding choice, paths, SQL limits (the only place to swap providers) |
| `graph/` | LangGraph agent: state, nodes, edges, graph assembly, tracing, CLI, UI helpers |
| `tools/` | `retrieve_docs`, `search_schema`, `validate_sql`, `run_sql` |
| `rag/` | Ingestion into ChromaDB and retrieval helpers |
| `prompts/` | Router, SQL generation and synthesis prompts (plain text) |
| `data/` | `raw/` CSVs, `olist.db`, `docs/` policy documents, `schema_notes.json`, `example_queries.json` |
| `evaluation/` | Test set, runner, scoring, baseline, report generator and results |
| `scripts/` | Loading the Olist CSVs and verifying the example queries |
| `tests/` | Automated tests |
| `report/` | Report builder, diagrams and the generated `.docx` |

Rules for working on this project are in `CLAUDE.md`; the project description is in `docs/project-brief.md`.

## Data and credits

The structured data is the Olist Brazilian E-Commerce Public Dataset on Kaggle; see the dataset page for its terms. Built with LangGraph, LangChain, ChromaDB, Sentence-Transformers, sqlglot, SQLite and Streamlit.
