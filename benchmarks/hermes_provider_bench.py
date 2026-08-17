"""Hindsight-parity benchmark for the luminary Hermes memory provider.

Measures, for N synthetic memories with a fixed query set:

- luminary recall p50/p95 latency (end-to-end, incl. embedding)
- peak RSS (resource usage) during the run
- ``luminary-memory lifecycle`` duration

The Hindsight local_embedded comparison arm is documented but optional
(its install is multi-hundred-MB); the luminary arm alone is CI-safe.

Usage:
    python benchmarks/hermes_provider_bench.py --n 5000 --backend sqlite \
        --report /tmp/lum_vs_hindsight.json
"""

from __future__ import annotations

import argparse
import json
import resource
import statistics
import sys
import tempfile
import time
from pathlib import Path

# Allow running as `python benchmarks/hermes_provider_bench.py` from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.synthetic import generate_memories, generate_queries


class _FakeEngine:
    """Deterministic embedding engine for pure-latency runs."""

    def embed(self, t: str) -> list[float]:
        v = [0.0] * 384
        v[hash(t) % 384] = 1.0
        return v

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


def _percentiles(latencies_ms: list[float]) -> dict[str, float]:
    if not latencies_ms:
        return {"p50": 0.0, "p95": 0.0, "mean": 0.0}
    s = sorted(latencies_ms)
    n = len(s)
    return {
        "p50": s[int(0.5 * (n - 1))],
        "p95": s[int(0.95 * (n - 1))],
        "mean": statistics.fmean(s),
    }


def _peak_rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def main() -> None:
    ap = argparse.ArgumentParser(description="Luminary vs Hindsight parity benchmark")
    ap.add_argument("--n", type=int, default=5000, help="Number of synthetic memories")
    ap.add_argument("--backend", choices=["sqlite"], default="sqlite")
    ap.add_argument("--report", type=str, default="/tmp/lum_vs_hindsight.json")
    ap.add_argument("--queries", type=int, default=5)
    args = ap.parse_args()

    from luminary_memory.api import MemoryClient
    from luminary_memory.ingest.llm import NoopEnricher

    tmp = Path(tempfile.mktemp(suffix=".db"))
    client = MemoryClient(db_path=str(tmp), engine=_FakeEngine(), enricher=NoopEnricher())

    memories = generate_memories(n=args.n, seed=42)
    t0 = time.perf_counter()
    client.ingest_batch(
        [m["content"] for m in memories], tags=[m["tags"] for m in memories]
    )
    ingest_ms = (time.perf_counter() - t0) * 1000

    queries = [q["query"] for q in generate_queries(n=args.queries)]

    recall_latencies: list[float] = []
    for q in queries:
        s = time.perf_counter()
        client.recall(q, limit=10, token_budget=2048)
        recall_latencies.append((time.perf_counter() - s) * 1000)

    # Lifecycle duration on the same store.
    t1 = time.perf_counter()
    client.run_lifecycle()
    lifecycle_ms = (time.perf_counter() - t1) * 1000

    peak_rss = _peak_rss_mb()

    report = {
        "n": args.n,
        "backend": args.backend,
        "ingest_ms": ingest_ms,
        "recall_latency_ms": _percentiles(recall_latencies),
        "lifecycle_ms": lifecycle_ms,
        "peak_rss_mb": peak_rss,
        "queries": queries,
        "reference": {
            "hindsight_local_embedded": {
                "note": "Optional arm; Hindsight's local_embedded install is "
                "multi-hundred-MB. Run manually and record p50/p95 + RSS "
                "following benchmarks/README.md.",
                "measured": None,
            }
        },
    }

    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))

    print(f"Benchmark n={args.n} backend={args.backend}")
    print(json.dumps(report, indent=2))

    try:
        tmp.unlink(missing_ok=True)
    except OSError:
        pass
    client.close()


if __name__ == "__main__":
    main()
