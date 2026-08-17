from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from benchmarks.metrics import mrr, percentiles, recall_at_k
from benchmarks.synthetic import generate_memories


class _FakeEngine:
    def embed(self, t: str) -> list[float]:
        v = [0.0] * 384
        v[hash(t) % 384] = 1.0
        return v

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


def main() -> None:
    ap = argparse.ArgumentParser(description="Run luminary-memory benchmarks")
    ap.add_argument("--n", type=int, default=500, help="Number of synthetic memories")
    ap.add_argument("--backend", choices=["sqlite"], default="sqlite")
    ap.add_argument("--report", type=str, default="/tmp/bench.json", help="Output JSON report path")
    args = ap.parse_args()

    import tempfile

    from luminary_memory.api import MemoryClient
    from luminary_memory.ingest.llm import NoopEnricher

    tmp = Path(tempfile.mktemp(suffix=".db"))
    client = MemoryClient(db_path=str(tmp), engine=_FakeEngine(), enricher=NoopEnricher())

    memories = generate_memories(n=args.n, seed=42)
    t0 = time.perf_counter()
    client.ingest_batch([m["content"] for m in memories],
                        tags=[m["tags"] for m in memories])
    ingest_ms = (time.perf_counter() - t0) * 1000

    queries = ["postgres vector search", "deploy target staging", "sanitize FTS"]
    latencies: dict[str, list[float]] = {"semantic": [], "keyword": [], "temporal": [], "graph": [], "e2e": []}
    # Per-strategy timing via direct calls; e2e via client.recall
    from luminary_memory.recall.graph import graph_recall
    from luminary_memory.recall.keyword import keyword_recall
    from luminary_memory.recall.semantic import semantic_recall
    from luminary_memory.recall.temporal import temporal_recall

    for q in queries:
        for name, fn in [
            ("semantic", lambda qq=q: semantic_recall(client.backend, client.engine, qq, limit=10)),
            ("keyword", lambda qq=q: keyword_recall(client.backend, qq, limit=10)),
            ("temporal", lambda qq=q: temporal_recall(client.backend, limit=10)),
            ("graph", lambda qq=q: graph_recall(client.backend, qq, limit=10)),
        ]:
            s = time.perf_counter()
            fn()
            latencies[name].append((time.perf_counter() - s) * 1000)
        s = time.perf_counter()
        # Ground truth for recall@k: ids whose content contains query terms
        res = client.recall(q, limit=10)
        latencies["e2e"].append((time.perf_counter() - s) * 1000)
        # Also compute quality metrics (illustrative)
        _ = res

    # Quality: recall@k and MRR against naive relevant set (id overlap is synthetic, so use keyword hits as proxy)
    # Build relevant sets as keyword_search top-20 ids per query
    quality: dict[str, dict] = {}
    for q in queries:
        relevant_rows = client.search(q, limit=20)
        relevant_ids = {m.id for m, _ in relevant_rows if m.id is not None}
        res = client.recall(q, limit=10)
        retrieved = [m.id for m in res.memories if m.id is not None]
        quality[q] = {
            "recall@5": recall_at_k(retrieved, relevant_ids, 5),
            "recall@10": recall_at_k(retrieved, relevant_ids, 10),
            "mrr": mrr(retrieved, relevant_ids),
        }

    report = {
        "n": args.n,
        "backend": args.backend,
        "ingest_ms": ingest_ms,
        "latency_ms": {k: percentiles(v) for k, v in latencies.items()},
        "quality": quality,
    }
    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    # Markdown summary to stdout
    print(f"Benchmark n={args.n} backend={args.backend}")
    print(json.dumps(report, indent=2))
    try:
        tmp.unlink(missing_ok=True)
    except OSError:
        pass  # best-effort cleanup; temp dir is reclaimed by the OS
    client.close()


if __name__ == "__main__":
    main()
