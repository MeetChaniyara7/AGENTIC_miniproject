"""Run the 30-question test set through the agent and the single-prompt baseline.

    python -m evaluation.run_eval                 # everything
    python -m evaluation.run_eval --only sql-01,hyb-02 --skip-baseline

Writes evaluation/results.csv, results_detail.json, baseline_results.csv, summary.md and traces/.
LLM responses are cached on disk (llm_cache/), so an interrupted run resumes cheaply.
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
import time
from datetime import date
from pathlib import Path

from config import ROOT, get_settings
from evaluation import report
from evaluation.baseline import full_schema, run_baseline
from evaluation.llm_cache import CachedLLM
from evaluation.scoring import judge, missing_keywords, results_match, retrieval_hit
from graph.run import ask
from graph.trace import write_trace
from tools.sql_executor import run_sql

HERE = Path(__file__).resolve().parent
TOOL_NODES = ("retrieve_docs", "retrieve_schema", "validate_sql", "execute_sql")
CSV_COLUMNS = ["id", "category", "question", "expected_route", "route", "route_ok", "ended_at", "passed",
               "sql_match", "retrieval_hit", "retrieval_hit_direct", "keywords_ok", "retries", "tool_calls",
               "tool_failures", "llm_calls", "cache_hits", "api_retries", "approvals", "latency_ms",
               "fail_reason", "fail_reasons", "sql"]


def preview(rows, n: int = 3) -> str:
    return json.dumps([list(r) for r in rows[:n]], default=str) + (f" ... ({len(rows)} rows)" if len(rows) > n else "")


def reference_rows(item: dict, db: Path) -> list:
    res = run_sql(item["reference_sql"], db)
    if not res.ok:
        raise RuntimeError(f"reference SQL for {item['id']} failed: {res.error}")
    return res.rows


def run_question(graph, item: dict, llm: CachedLLM, db: Path, trace_dir: Path, direct_retrieve, ref_rows: list | None) -> dict:
    llm.reset_stats()
    approvals = []

    def approver(payload: dict) -> dict:
        approvals.append(payload["sql"])
        # A person reviewing a legitimate analytics query would approve it; harmful requests are declined.
        return {"approved": item["category"] != "safety"}

    state, crashed = {}, None
    start = time.perf_counter()
    try:
        state = ask(graph, item["question"], f"eval-{item['id']}", approver)
    except Exception as e:  # noqa: BLE001 - one broken question must not stop the run
        crashed = f"{type(e).__name__}: {e}"
    wall_ms = (time.perf_counter() - start) * 1000
    stats = llm.snapshot()

    trace = state.get("trace", [])
    tool_stats = {t: [sum(e["node"] == t for e in trace), sum(e["node"] == t and not e["success"] for e in trace)]
                  for t in TOOL_NODES}
    chunks = state.get("doc_chunks", [])
    rows, cols = state.get("rows", []), state.get("columns", [])
    cat = item["category"]
    sql_match = bool("reference_sql" in item and ref_rows is not None and rows and results_match(rows, ref_rows))
    missing = missing_keywords(state.get("answer", ""), item["must_contain"]) if "must_contain" in item else []

    run = {
        "id": item["id"], "category": cat, "question": item["question"], "expected_route": item.get("expected_route", ""),
        "route": state.get("route", ""), "ended_at": trace[-1]["node"] if trace else "crash",
        "sql": state.get("sql", ""), "sql_match": sql_match,
        "retrieval_hit": retrieval_hit(chunks, item.get("reference_source")),
        "retrieval_hit_direct": retrieval_hit(direct_retrieve(item["question"]), item.get("reference_source"))
        if item.get("reference_source") else False,
        "missing_keywords": missing, "keywords_ok": not missing,
        "retries": state.get("retries", 0), "tool_stats": tool_stats,
        "tool_calls": sum(v[0] for v in tool_stats.values()), "tool_failures": sum(v[1] for v in tool_stats.values()),
        "llm_calls": stats["llm_calls"], "cache_hits": stats["cache_hits"], "api_retries": stats["api_retries"],
        "approvals": len(approvals),
        # wall time plus the original latency of cached calls = what an uncached run would have taken
        "latency_ms": round(wall_ms + stats["cached_llm_latency_s"] * 1000, 1),
        "fail_reason": state.get("fail_reason") or "", "last_error": state.get("validation_error") or state.get("exec_error") or "",
        "exec_ok": bool(not state.get("fail_reason") and cols), "crashed": crashed,
        "answer": state.get("answer", ""), "reference_keys": [k for k in ("reference_sql", "reference_source") if k in item],
        "agent_rows_preview": preview(rows) if rows else "no rows", "reference_rows_preview": preview(ref_rows) if ref_rows else "",
        "retrieved_sources": sorted({c["source"] for c in chunks}),
        "route_ok": item.get("expected_route", "") == state.get("route", "") if cat != "safety" else None,
    }
    if crashed:
        run["fail_reason"] = run["fail_reason"] or "harness_exception"
    run["passed"], run["fail_reasons"] = judge(item, run)
    if state:
        write_trace(state, item["id"], trace_dir)
    return run


def table_counts(db: Path) -> dict:
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {n: con.execute(f"SELECT COUNT(*) FROM {n}").fetchone()[0] for n in names}
    finally:
        con.close()


def write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({**r, "fail_reasons": " | ".join(r.get("fail_reasons", [])) if "fail_reasons" in r else ""})


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma-separated question ids")
    ap.add_argument("--skip-baseline", action="store_true")
    ap.add_argument("--pace", type=float, default=0.0, help="seconds to wait between questions (rate limits)")
    ap.add_argument("--out-dir", type=Path, default=HERE)
    args = ap.parse_args()

    from config import get_chat_model
    from graph.build_graph import build_graph, default_deps
    from tools.doc_retriever import retrieve_docs

    s = get_settings()
    model = {"gemini": s.gemini_model, "groq": s.groq_model, "ollama": s.ollama_model}[s.provider]
    llm = CachedLLM(get_chat_model(), ROOT / "llm_cache", f"{s.provider}:{model}")
    graph = build_graph(default_deps(llm=llm))

    items = json.loads((HERE / "test_set.json").read_text(encoding="utf-8"))
    if args.only:
        wanted = set(args.only.split(","))
        items = [i for i in items if i["id"] in wanted]
    out = args.out_dir
    (out / "traces").mkdir(parents=True, exist_ok=True)
    before = table_counts(s.db_path)
    ref_cache = {i["id"]: reference_rows(i, s.db_path) for i in items if "reference_sql" in i}

    results = []
    for n, item in enumerate(items, 1):
        r = run_question(graph, item, llm, s.db_path, out / "traces", lambda q: retrieve_docs(q, k=4), ref_cache.get(item["id"]))
        results.append(r)
        print(f"[{n:>2}/{len(items)}] {r['id']:<8} {'PASS' if r['passed'] else 'FAIL'}  route={r['route'] or '-':<12} "
              f"retries={r['retries']} {r['latency_ms'] / 1000:5.1f}s  {'; '.join(r['fail_reasons'])[:110]}", flush=True)
        if args.pace:
            time.sleep(args.pace)

    baseline = []
    if not args.skip_baseline:
        schema = full_schema(s.db_path)
        for item in (i for i in items if "reference_sql" in i):
            llm.reset_stats()
            b = run_baseline(llm, item["question"], schema, s.db_path)
            b["latency_ms"] = round(b["latency_ms"] + llm.snapshot()["cached_llm_latency_s"] * 1000, 1)
            b.update(id=item["id"], category=item["category"], question=item["question"],
                     sql_match=bool(b["rows"] and results_match(b["rows"], ref_cache[item["id"]])),
                     rows_preview=preview(b["rows"]) if b["rows"] else "no rows")
            b.pop("rows"), b.pop("columns")
            baseline.append(b)
            print(f"[baseline] {b['id']:<8} {'MATCH' if b['sql_match'] else 'miss '} exec_ok={b['exec_ok']} {b['latency_ms'] / 1000:5.1f}s", flush=True)

    after = table_counts(s.db_path)
    meta = {"date": date.today().isoformat(), "provider": s.provider, "model": model, "db": s.db_path.name,
            "db_unchanged": before == after, "table_counts": after}
    detail = {"meta": meta, "results": results, "baseline": baseline}
    (out / "results_detail.json").write_text(json.dumps(detail, indent=2, default=str), encoding="utf-8")
    write_csv(out / "results.csv", results, CSV_COLUMNS)
    if baseline:
        write_csv(out / "baseline_results.csv", baseline,
                  ["id", "category", "question", "sql_match", "exec_ok", "latency_ms", "llm_calls", "error", "sql"])
    (out / "summary.md").write_text(report.render(detail), encoding="utf-8")
    print(f"\nPassed {sum(r['passed'] for r in results)}/{len(results)}. Wrote results.csv, summary.md in {out}")


if __name__ == "__main__":
    main()
