# Benchmark Results — luminary-memory

> Reproducible numbers for the Hermes memory provider.
> Harness: `benchmarks/run_benchmarks.py` · Synthetic dataset, deterministic fake embedding engine (pipeline latency only, 0 LLM tokens).

## Latest run (2026-08-18, v0.2.12)

```
python benchmarks/run_benchmarks.py --n 5000 --backend sqlite --report /tmp/bench_final_run.json
```

| Metric | Value |
|--------|-------|
| Memories | 5,000 |
| Ingest (5k, batch) | 2.1 s (~2,400 mem/s) |
| Recall e2e p50 | **76.9 ms** (p95 76.9, mean 78.2) |
| Quality — MRR | **1.0** on all queries |
| Quality — recall@5 / recall@10 | 0.25 / 0.5 (see table below) |
| Persistent context build (per turn) | **4 ms** (measured, warm) |
| Rule auto-replace scan (vectorized) | **31 ms** (measured, warm) |
| Temporal recall (limit 20) | **28 ms** (measured, warm) |

## Latency by strategy (5k store, deterministic embedding)

Measured by `run_benchmarks.py` (fake engine, pipeline only — no ONNX load):

| Strategy | p50 | p95 | mean |
|----------|-----|-----|------|
| **End-to-end recall** | **76.9 ms** | 76.9 ms | 78.2 ms |
| Semantic (vectorized matmul) | 48.1 ms | 48.1 ms | 43.1 ms |
| Keyword (FTS5 BM25) | 2.4 ms | 2.4 ms | 2.7 ms |
| Temporal (batched fetch) | 30.5 ms | 30.5 ms | 30.7 ms |
| Graph (SQL aggregation) | 22.9 ms | 22.9 ms | 23.0 ms |

For reference, the same workload at 1k memories: e2e recall **8.7 ms** p50,
ingest 0.4 s.

## Quality (recall@k / MRR against keyword-top-20 relevance)

| Query | recall@5 | recall@10 | MRR |
|-------|----------|-----------|-----|
| `postgres vector search` | 0.25 | 0.5 | 1.0 |
| `deploy target staging` | 0.2 | 0.2 | 1.0 |
| `sanitize FTS` | 0.25 | 0.3 | 1.0 |

MRR 1.0 means the top-ranked result is always relevant; recall@k is lower
because the synthetic dataset is 5k near-identical rows (`id:N` noise), so the
top-20 keyword-relevant set is large and sparse — the numbers are not
representative of a real store.

## Per-turn bookkeeping (Hermes provider, measured at 5k)

| Operation | Measured | Why it matters |
|-----------|----------|----------------|
| Persistent context (top-8 by importance) | **4 ms** | Runs every turn; lean scan reads only id/content/importance/access_count, no embedding decode |
| Rule auto-replace scan | **31 ms** | One matmul over stored embeddings instead of N Python cosines |
| Access bookkeeping (`touch_memories`) | batched | One `UPDATE ... WHERE id IN (...)` instead of N writes |
| Temporal recall | **28 ms** | Batch top-id fetch (`get_many`), no N+1 |

## Accuracy is preserved

Every optimization in v0.2.12 (vectorized auto-replace, lean persistent-context
scan, batched access/lifecycle/temporal) was verified against the
pre-optimization baseline: the quality metrics (recall@5, recall@10, MRR) are
**identical** for the same store and queries. Speed did not cost accuracy.

## What was optimized (identical results, no approximation)

1. **Vectorized cosine similarity** — per-row numpy loop → single matmul (`sqlite.py`).
2. **`scan_embeddings_matrix`** — rule auto-replace loads (id, matrix) without full Memory materialization; one matmul instead of N Python cosines.
3. **`top_by_importance`** — persistent-context scan reads only id/content/importance/access_count, no embedding blobs.
4. **`touch_memories`** — access bookkeeping in one `UPDATE ... WHERE id IN (...)`.
5. **`delete_many` / `update_importances`** — lifecycle passes issue a handful of statements instead of one write per memory.
6. **`get_many`** — temporal recall fetches top ids in one `SELECT ... WHERE id IN (...)`.
7. **SQL graph aggregation** — 210k relation rows → `SUM/COUNT ... GROUP BY` in the database (`graph.py`).
8. **Single UNION query** for direct-entity memory ids — 5 queries → 1.
9. **`temporal_scan()`** — temporal recall fetches only `(id, created_at, access_count)`, no JSON/embedding parse.
10. **Relation cap (8/memory) + indexes** — dense graph (280k rows) → sparse (80k), storage 3.5× smaller.

## Competitive positioning

Third-party figures from [Hamza Shabbir's 2026 benchmark](https://hamzashabbir.dev/article/agent-memory-mem0-vs-letta-vs-zep-vs-langmem-benchmark-2026)
(same workload, same machine, LLM-based extraction for all four) and [NiteAgent 2026 comparison](https://niteagent.com/blog/ai-agent-memory-comparison-2026/).

| Tool | Recall latency | LLM tokens / turn | Memory / infra | Self-host |
|------|---------------|-------------------|----------------|-----------|
| **luminary-memory** | **~77 ms @ 5k** | **0** | SQLite + local ONNX | ✅ native |
| Mem0 | ~120 ms | ~280 | Qdrant + LLM API | ⚠️ graph paywalled ($249/mo) |
| LangMem | ~140 ms | ~240 | LangGraph SDK | ✅ library |
| Zep | ~310 ms | ~620 | Temporal graph + GraphDB | ⚠️ GraphDB needed |
| Letta | ~520 ms | ~900 | Agent runtime (heavy) | ✅ OSS |

### Why luminary wins on cost

- **Zero LLM tokens per turn** — fact extraction is local (whitelist + ONNX embeddings), unlike every competitor above which calls an LLM on every `add()`.
- **No vector DB / GraphDB dependency** — SQLite FTS5 + local ONNX; optional pgvector for scale.
- **Graph included, not paywalled** — co-occurrence entity graph is free and local (Mem0 gates graph behind $249/mo Pro).

### Honest caveats

- Latency above is pipeline-only (deterministic fake embedding). With real `fastembed` ONNX models, end-to-end recall at 5k is higher (the ONNX model load is a one-time cost on first recall; embedding compute adds ~30-50 ms per query). Numbers above isolate the retrieval pipeline.
- Competitor numbers are third-party and use LLM extraction, so their token/latency figures are not directly apples-to-apples — that is exactly the point: they *require* an LLM, luminary does not.
- Hindsight `local_embedded` reference arm is documented but optional (multi-hundred-MB install) — see `benchmarks/README.md`.
