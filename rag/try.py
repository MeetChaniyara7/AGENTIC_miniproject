"""Try retrieval by hand: python -m rag.try "why did cancellations rise?" [--min-score 0.3]

Prints the document chunks that pass the threshold, then the schema context.
With --raw it also shows the top chunks regardless of score (handy for tuning).
"""
import argparse

from rag.store import DOCS_COLLECTION, query_collection
from tools.doc_retriever import DEFAULT_MIN_SCORE, retrieve_docs
from tools.schema_search import search_schema


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--min-score", type=float, default=DEFAULT_MIN_SCORE)
    ap.add_argument("-k", type=int, default=4)
    ap.add_argument("--raw", action="store_true", help="also show top chunks ignoring the threshold")
    args = ap.parse_args()

    print(f"=== DOCUMENTS (min_score={args.min_score}) ===")
    hits = retrieve_docs(args.question, k=args.k, min_score=args.min_score)
    if not hits:
        print("(nothing passed the threshold)")
    for h in hits:
        print(f"[{h['score']:.3f}] {h['source']} > {h['section']}\n    {h['text'][:200]!r}")
    if args.raw:
        print("--- raw top chunks ---")
        for h in query_collection(DOCS_COLLECTION, args.question, args.k):
            print(f"[{h['score']:.3f}] {h['metadata']['source']} > {h['metadata']['section']}")
    print("\n=== SCHEMA CONTEXT ===")
    print(search_schema(args.question))


if __name__ == "__main__":
    main()
