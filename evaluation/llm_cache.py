"""Disk cache + rate-limit retry around any chat model (CLAUDE.md: cache LLM responses during evaluation).

- Key = sha256(model id + prompt). Errors are never cached.
- Each entry stores the latency of the original call, so a re-run can still report the latency a
  fresh run would have had (`original_latency_s`), alongside how many calls were cache hits.
- 429 / rate-limit errors are retried with backoff here, and counted, because a free tier throttles
  an evaluation run long before it finishes.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from types import SimpleNamespace

from graph.nodes import content_text

RATE_LIMIT_MARKERS = ("429", "rate limit", "rate_limit", "resource_exhausted", "quota", "too many requests")


class CachedLLM:
    def __init__(self, llm, cache_dir: Path, model_id: str, max_api_retries: int = 4, sleep=time.sleep):
        self.llm, self.cache_dir, self.model_id = llm, Path(cache_dir), model_id
        self.max_api_retries, self._sleep = max_api_retries, sleep
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.reset_stats()

    def reset_stats(self) -> None:
        self.calls = self.hits = self.api_retries = 0
        self.original_latency_s = 0.0   # sum of the original latencies of every call (hits included)
        self.hit_latency_s = 0.0        # the part of that sum that was served from cache

    def snapshot(self) -> dict:
        return {"llm_calls": self.calls, "cache_hits": self.hits, "api_retries": self.api_retries,
                "original_llm_latency_s": round(self.original_latency_s, 3),
                "cached_llm_latency_s": round(self.hit_latency_s, 3)}

    def _path(self, prompt: str) -> Path:
        return self.cache_dir / (hashlib.sha256(f"{self.model_id}\n{prompt}".encode("utf-8")).hexdigest() + ".json")

    def invoke(self, prompt):
        self.calls += 1
        path = self._path(prompt)
        if path.exists():
            entry = json.loads(path.read_text(encoding="utf-8"))
            self.hits += 1
            self.original_latency_s += entry["latency_s"]
            self.hit_latency_s += entry["latency_s"]
            return SimpleNamespace(content=entry["text"])

        for attempt in range(self.max_api_retries + 1):
            start = time.perf_counter()
            try:
                text = content_text(self.llm.invoke(prompt))
                break
            except Exception as e:  # noqa: BLE001
                limited = any(m in str(e).lower() for m in RATE_LIMIT_MARKERS)
                if not limited or attempt == self.max_api_retries:
                    raise
                self.api_retries += 1
                self._sleep(5 * 2 ** attempt)
        latency = time.perf_counter() - start
        self.original_latency_s += latency
        path.write_text(json.dumps({"text": text, "latency_s": latency, "model": self.model_id}), encoding="utf-8")
        return SimpleNamespace(content=text)
