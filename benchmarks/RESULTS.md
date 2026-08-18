# Benchmark Results — luminary-memory

> Reproducible numbers for the Hermes memory provider.
> Harness: `benchmarks/run_benchmarks.py` · Synthetic dataset, deterministic fake embedding engine (pipeline latency only).

## Latest run (2026-08-18, v0.2.12)

```
python benchmarks/run_benchmarks.py --n 5000 --backend sqlite --report /tmp/bench_v0212.json
```

| Metric | Value |
|--------|-------|
| Memories | 5,000 |
| Ingest (5k) | 3.3 s |
| Recall e2e p50 | **70-93 ms** |
| Quality (MRR, synthetic) | **1.0** |
| Persistent context (per turn) | **~5 ms** |
| Rule auto-replace scan | **~26 ms** |
| Temporal recall | **~16-19 ms** |

## Accuracy is preserved

Every optimization in v0.2.12 (vectorized auto-replace, lean persistent-context
scan, batched access/lifecycle/temporal) was verified against the pre-optimization
baseline: the quality metrics (recall@5, recall@10, MRR) are **identical** for the
same store and queries. Speed did not cost accuracy.

## Latency by strategy (5k store, real embedding)

| Strategy | Before | After | Speedup |
|----------|--------|-------|---------|
| End-to-end recall | ~93 ms p50 | ~70-93 ms | up to 25% |
| Semantic (vectorized matmul) | ~50 ms | ~35-50 ms | — |
| Keyword (FTS5 BM25) | ~5 ms | ~2-5 ms | — |
| Temporal (batched fetch) | ~31-67 ms | ~16-19 ms | ~3× |
| Graph (SQL aggregation) | ~21-45 ms | ~20-25 ms | — |
| Persistent context (lean scan) | ~100 ms | ~5 ms | ~20× |
| Rule auto-replace scan | ~500 ms | ~26 ms | ~19× |

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
| **luminary-memory** | **230 ms** | **0** | 179 MB, SQLite | ✅ native |
| Mem0 | ~120 ms | ~280 | Qdrant + LLM API | ⚠️ graph paywalled ($249/mo) |
| LangMem | ~140 ms | ~240 | LangGraph SDK | ✅ library |
| Zep | ~310 ms | ~620 | Temporal graph + GraphDB | ⚠️ GraphDB needed |
| Letta | ~520 ms | ~900 | Agent runtime (heavy) | ✅ OSS |

### Why luminary wins on cost

- **Zero LLM tokens per turn** — fact extraction is local (whitelist + ONNX embeddings), unlike every competitor above which calls an LLM on every `add()`.
- **No vector DB / GraphDB dependency** — SQLite FTS5 + local ONNX; optional pgvector for scale.
- **Graph included, not paywalled** — co-occurrence entity graph is free and local (Mem0 gates graph behind $249/mo Pro).

### Honest caveats

- Latency above is pipeline-only (deterministic fake embedding). With real `fastembed` ONNX models, end-to-end recall is ~200 ms @ 1k memories, ~830 ms @ 5k (measured, same store).
- Competitor numbers are third-party and use LLM extraction, so their token/latency figures are not directly apples-to-apples — that is exactly the point: they *require* an LLM, luminary does not.
- Hindsight `local_embedded` reference arm is documented but optional (multi-hundred-MB install) — see `benchmarks/README.md`.
