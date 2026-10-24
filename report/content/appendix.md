# APPENDIX

## Appendix A – Source Code

The important source code is explained in Chapter 7; the complete project is in the repository below.

**GitHub Repository:** https://github.com/MeetChaniyara7/AGENTIC_miniproject

**Deployed Link:** not deployed; the application runs locally with `streamlit run app.py`.

**How to run.** The `README.md` at the root of the repository explains setup, running the application, loading the data, and running the tests and the evaluation.

## Appendix B – Additional Screenshots

@@SHOT fig:app_followup | Insert Screenshot: Follow-up question. "How many orders were placed in 2017?" followed by "And in 2018?" in the same conversation, with the Agent trace showing the "Understood as" line | Follow-up question resolved from conversation memory
@@SHOT fig:app_empty | Insert Screenshot: Empty result. "Why did refunds spike last week?" showing the blue "returned no rows" banner | Friendly message for an empty result
@@SHOT fig:app_oos | Insert Screenshot: Out-of-scope question. "What is the capital of France?" showing the refusal banner | Friendly message for an out-of-scope question
@@SHOT fig:app_decline | Insert Screenshot: Rejected approval. The message shown after clicking Reject on the approval card | Message shown after approval is rejected

## Appendix C – Sample Prompts

The three prompts that drive the agent are plain text files in the `prompts/` folder; the fourth prompt is the one used by the evaluation baseline. Placeholders in the form `<<name>>` are filled in by the program at run time. The prompts are reproduced exactly as used.

@@TABLE prompts

### C.1 Router prompt (prompts/router.txt)

@@PROMPT router

### C.2 SQL generation prompt (prompts/sql_gen.txt)

@@PROMPT sql_gen

### C.3 Synthesis prompt (prompts/synthesize.txt)

@@PROMPT synthesize

### C.4 Baseline prompt (evaluation/baseline.py)

@@BASELINEPROMPT

## Appendix D – Test Data

### D.1 Database

The structured data is the Brazilian E-Commerce Public Dataset by Olist [18], loaded into SQLite by `scripts/load_olist.py` with typed columns and indexes. The tables and the number of rows loaded are listed below.

@@TABLE dbtables

### D.2 Policy documents

The six documents used for retrieval are synthetic: they were written for this project and are not real Olist policies. A README in the same folder says so.

@@TABLE docs

### D.3 Schema notes and example queries

`data/schema_notes.json` holds a plain-English description of every table and column, and marks four columns as sensitive. `data/example_queries.json` holds twelve question and SQL pairs that were each executed against the database before use; they are retrieved as examples by the SQL generator and are not reused as test questions.

@@TABLE examples

### D.4 Evaluation test set and results

The 30 evaluation questions, their category, the reference used for scoring, and the outcome of the run described in Chapter 8 are listed below. SQL references are the verified reference queries stored in `evaluation/test_set.json`; their result values are shown.

@@TABLE alltests
