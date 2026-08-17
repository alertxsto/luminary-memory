# Benchmark Results — luminary-memory

> Reproducible numbers for the Hermes memory provider (v0.2.1+).
> Harness: `benchmarks/hermes_provider_bench.py` · Synthetic dataset, deterministic fake embedding engine (pipeline latency only).

## Latest run (2026-08-18, commit `ed550bf`)

```
python benchmarks/hermes_provider_bench.py --n 5000 --backend sqlite --report /tmp/lum_vs_comp.json
```

| Metric | Value |
|--------|-------|
| Memories | 5,000 |
| Ingest (5k) | 6.9 s |
| Recall p50 | **230 ms** |
| Recall p95 | **245 ms** |
| Peak RSS | **179 MB** |
| Lifecycle (5k) | 118 s |

## Latency after optimizations (real embedding, same 5k store)

| Scenario | Before | After | Speedup |
|----------|--------|-------|---------|
| Recall @ 5k memories | 3,400 ms | **832 ms** | 4.1× |
| Recall @ 1k memories (typical) | — | **~200 ms** | — |
| Ingest 5k | 360 s | 224 s | 1.6× |
| Relations store | 280,000 | 80,000 | 3.5× smaller |
| Temporal recall | 486 ms | 62 ms | 7.8× |

### What was optimized (identical results, no approximation)

1. **Vectorized cosine similarity** — per-row numpy loop → single matmul (`sqlite.py`).
2. **SQL graph aggregation** — 210k relation rows → `SUM/COUNT ... GROUP BY` in the database (`graph.py`).
3. **Single UNION query** for direct-entity memory ids — 5 queries → 1.
4. **`temporal_scan()`** — temporal recall fetches only `(id, created_at, access_count)`, no JSON/embedding parse (7.8×).
5. **Relation cap (8/memory) + indexes** — dense graph (280k rows) → sparse (80k), storage 3.5× smaller.

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
