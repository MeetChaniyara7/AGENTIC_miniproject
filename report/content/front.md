## ack

We would like to express our sincere gratitude to our faculty guide for the direction, encouragement and patient feedback that shaped this mini project at every stage. We thank the Department of Computer Science and Information Technology, UnitedWorld Institute of Technology, and Karnavati University for giving us the opportunity to study Agentic AI and for providing the laboratory and computing facilities used for development and testing.

We are grateful to the maintainers of the open-source tools on which this work stands, including LangChain and LangGraph, ChromaDB, Sentence-Transformers, SQLite, sqlglot, Streamlit and pytest. We also thank Olist for publishing the Brazilian E-Commerce Public Dataset, and Groq and Google for the free-tier language model access that made repeated experiments possible without any cost.

Finally, we thank our team members and classmates for the discussions, code reviews and honest criticism that helped us find and fix many problems before this report was written. Their support taught us that a reliable AI system is built as much through careful testing and measurement as through clever design.

## abstract

Business questions such as "why was the late delivery rate so high in March 2018?" cannot be answered from numbers alone or from documents alone: the figures live in a database, while the definitions, targets and rules live in policy documents. This project presents Hybrid Analyst, an agentic AI system that answers such questions by combining Text-to-SQL over a company database with retrieval-augmented generation (RAG) over company policy documents.

The system is a single-agent workflow built with LangGraph. An LLM router chooses between a SQL path, a document path, or both. The SQL path retrieves the relevant schema, generates SQLite, validates it with sqlglot, runs it read-only, and repairs its own query from error feedback up to three times. A human-in-the-loop interrupt guards queries that touch sensitive columns, and per-thread memory supports follow-up questions. Every step is logged as a JSON trace. The system uses Python, LangChain, LangGraph, SQLite with the Olist e-commerce data, ChromaDB, Sentence-Transformers, Streamlit and a free-tier LLM.

On a 30-question test set, the system answered {m:accuracy} correctly, completed {m:completion} of non-safety questions, reached {m:sql_acc} SQL accuracy, blocked {m:safety_block} of unsafe requests and averaged {m:mean_latency} seconds per question. A single-prompt baseline matched its SQL accuracy but cannot use documents or guard queries. Failures were traced to retrieval depth, ambiguous questions and rounding.
