from __future__ import annotations

import statistics


def recall_at_k(retrieved_ids: list[int], relevant_ids: set[int], k: int) -> float:
    if not relevant_ids:
        return 1.0
    topk = set(retrieved_ids[:k])
    return len(topk & relevant_ids) / len(relevant_ids)


def mrr(retrieved_ids: list[int], relevant_ids: set[int]) -> float:
    for rank, mid in enumerate(retrieved_ids, start=1):
        if mid in relevant_ids:
            return 1.0 / rank
    return 0.0


def percentiles(latencies_ms: list[float]) -> dict[str, float]:
    if not latencies_ms:
        return {"p50": 0.0, "p95": 0.0, "mean": 0.0}
    s = sorted(latencies_ms)
    n = len(s)
    p50 = s[int(0.5 * (n - 1))]
    p95 = s[int(0.95 * (n - 1))]
    return {"p50": p50, "p95": p95, "mean": statistics.fmean(s)}
