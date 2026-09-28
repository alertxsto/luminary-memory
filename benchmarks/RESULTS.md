# Benchmark Results — luminary-memory

> Historical pipeline and controlled-gold measurements are retained below.
> A separate current-checkout smoke is shown first. None establishes
> superiority over Mem0, Hindsight, or another provider.

## Historical pipeline run (2026-08-18, v0.2.15)

The current checkout run was:

```bash
uv run --extra dev python -m benchmarks.run_benchmarks --n 40 --report /tmp/luminary-bench-doc-smoke.json
```

It used the deterministic fake embedding engine, strict recall, and evidence
requirements. The 12 independently labelled

| Metric | Value |
|--------|-------|
| Memories | 5,000 |
| Ingest (5k, batch) | 2.1 s (~2,400 mem/s) |
| Recall e2e p50 | **76.9 ms** (p95 76.9, mean 78.2) |
| Quality | See the independent gold-set run below |
The historical gold score below was recall@10 **0.95**. The current controlled
fixture is lower; the older figures **must not** be described as current
accuracy or assumed to survive changes in confidence or ranking. The real
default embedding model has a separate semantic smoke in
[`FIXES.md`](../FIXES.md), not a matched full gold-set run.
> queries, e2e recall ~32 ms p50. Adaptive-importance re-estimation and

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

## Historical synthetic quality (circular legacy proxy)

The following table is retained for historical comparability only. Its labels
were derived from keyword results on the same implementation, so it must not be
read as an independent accuracy score.

| Query | recall@5 | recall@10 | MRR |
|-------|----------|-----------|-----|
| `postgres vector search` | 0.25 | 0.5 | 1.0 |
| `deploy target staging` | 0.2 | 0.2 | 1.0 |
| `sanitize FTS` | 0.25 | 0.3 | 1.0 |

MRR 1.0 means the top-ranked result is always relevant; recall@k is lower
because the synthetic dataset is 5k near-identical rows (`id:N` noise), so the
top-20 keyword-relevant set is large and sparse — the numbers are not
representative of a real store.

## Historical per-turn bookkeeping (legacy Hermes provider, measured at 5k)

| Operation | Measured | Why it matters |
|-----------|----------|----------------|
| Legacy persistent context (top-8 by importance) | **4 ms** | Historical only; the v0.2.18 provider no longer injects this tier |
| Rule auto-replace scan | **31 ms** | Historical measured cost; this automatic replacement path has since been removed |
| Access bookkeeping (`touch_memories`) | batched | One `UPDATE ... WHERE id IN (...)` instead of N writes |
| Temporal recall | **28 ms** | Batch top-id fetch (`get_many`), no N+1 |

## Historical deep-audit run (2026-08-23, v0.2.18 working tree)

Command:

```bash
python3 -m benchmarks.run_benchmarks --n 40 --report /tmp/luminary-deep-audit-final-3.json
```

The run used SQLite, strict recall, evidence-required results, and the
deterministic fake embedding engine for repeatable timing. It measured batch
ingest at **18.51 ms** and end-to-end recall at **2.29 ms p50** (**2.59 ms
mean**). These are engineering smoke measurements, not a production capacity
claim; the report was generated from an uncommitted working tree.

The independent gold arm remained unchanged:

| Metric | Result |
|--------|--------|
| Gold cases | 12 (10 answer, 2 no-answer) |
| Recall@10 | 0.95 |
| MRR | 1.00 |
| Precision@10 | 1.00 |
| Abstention accuracy | 1.00 |
| Unsupported answer rate | 0.00 |
| Evidence support precision | 1.00 |
| Cross-scope leakage | 0 |

## Historical independent gold-set run

Command:

```bash
python3 -m benchmarks.run_benchmarks --n 40 --report /tmp/luminary-gold.json
```

The gold arm used `benchmarks/gold_micro.jsonl`, with fixed relevance labels and
no-answer cases authored outside the retriever. This earlier controlled run
reported (not current checkout results):

| Metric | Result |
|--------|--------|
| Gold cases | 12 (10 answer, 2 no-answer) |
| Recall@10 | 0.95 |
| MRR | 1.00 |
| Precision@10 | 1.00 |
| Abstention accuracy | 1.00 |
| Unsupported answer rate | 0.00 |
| Evidence support precision | 1.00 |
| Cross-scope leakage | 0 |

These historical results are a regression reference, not a competitor ranking.
A matched LongMemEval/competitor adapter would require identical embedding,
extraction, context, and answer settings.

## Historical v0.2.12 accuracy comparison

At that time, vectorized auto-replace, lean legacy persistent-context scans,
and batched access/lifecycle/temporal operations gave identical recall@k and
MRR for the same store and queries before and after those optimizations.
This is **not** a claim about the current checkout (see the smoke above).

## Historical optimized paths (some since removed)

1. **Vectorized cosine similarity** — per-row numpy loop became a matmul; current SQLite vector search uses bounded batches instead of a full-store matrix.
2. **`scan_embeddings_matrix`** — the historical automatic rule-replacement scan; the setting and helper have since been removed.
3. **`top_by_importance`** — persistent-context scan reads only id/content/importance/access_count, no embedding blobs.
4. **`touch_memories`** — access bookkeeping in one `UPDATE ... WHERE id IN (...)`.
5. **`delete_many` / `update_importances`** — lifecycle passes issue a handful of statements instead of one write per memory.
6. **`get_many`** — temporal recall fetches top ids in one `SELECT ... WHERE id IN (...)`.
7. **SQL graph aggregation** — 210k relation rows → `SUM/COUNT ... GROUP BY` in the database (`graph.py`).
8. **Single UNION query** for direct-entity memory ids — 5 queries → 1.
9. **`temporal_scan()`** — temporal recall fetches only `(id, created_at, access_count)`, no JSON/embedding parse.
10. **Relation cap (8/memory) + indexes** — dense graph (280k rows) → sparse (80k), storage 3.5× smaller.

## Comparison caveat

Latency and cost smoke numbers are useful engineering signals, but they are not
accuracy evidence. Third-party comparison figures use different datasets,
models, prompts, and extraction policies, so they are not apples-to-apples.
Luminary should only claim a quality lead after a reproducible matched run.

### Current caveats

- Latency above is pipeline-only (deterministic fake embedding). With real `fastembed` ONNX models, end-to-end recall at 5k is higher (the ONNX model load is a one-time cost on first recall; embedding compute adds ~30-50 ms per query). Numbers above isolate the retrieval pipeline.
- Competitor numbers are not included as evidence here because they are not
  measured under the same protocol.
- Hindsight `local_embedded` reference arm is documented but optional; it is a
  resource comparison, not an accuracy verdict.
