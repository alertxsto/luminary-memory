# Architecture

## Pipelines

Memory is a **loop**, not a one-shot pipeline: recall happens before the
agent answers, ingest after, lifecycle in the background.

```
ingest(text) ──► whitelist filter ──► (LLM enrich, optional) ──► embed ──► backend
                                                                           │
recall(query) ──► query expansion ──► 4 strategies ──► weighted RRF ──► adaptive cutoff ──► dedup ──► budget ──► results
                                         │
persistent context (provider) ──► top-N by importance every turn ──► merged with recall, anti-duplicated
                                         │
lifecycle() ──► cleanup (TTL) ──► consolidate (semantic) ──► prune (importance + pinned-rules exempt) ──► max_memories cap
```

## Ingest

1. **Whitelist filter**, drops noise and non-durable text (configurable regex).
2. **LLM enrichment** (optional), extracts a summary, entities, and tags. Provider-agnostic; a no-op by default so ingest works offline.
3. **Embed**, local CPU embedding (fastembed / ONNX).
4. **Store**, persists content, metadata, tags, timestamps, and the embedding to the backend.

## Recall

1. **Query expansion**, short queries are enriched with co-occurring graph entities before embedding (best-effort).
2. **Four strategies run in parallel:**
   - *semantic*, embedding similarity (vectorized cosine matmul).
   - *keyword*, FTS5 / BM25 term match.
   - *temporal*, recency decay × access popularity (batched top-id fetch, no N+1).
   - *graph*, entity co-occurrence traversal (SQL aggregation).
3. **Weighted RRF fusion**, reciprocal-rank fusion with per-strategy weights (semantic 0.4, keyword 0.3, graph 0.2, temporal 0.1) combines the four ranked lists into one.
4. **Importance boost**, memories at importance ≥ 0.8 get a ranking bonus (`importance_recall_boost`), lifting durable rules above weak-but-recent noise.
5. **Adaptive cutoff** (cliff detection), cuts at the first steep score drop (default 45%) so a sparse store returns only the relevant cluster instead of padding to the limit.
6. **Dedup**, Jaccard similarity removes near-duplicates.
7. **Budget**, results truncated to a token budget so the context window stays safe.
8. **Batched access bookkeeping**, recalled memories are marked accessed with one batched UPDATE (not N writes).

## Persistent context (Hermes provider)

The system prompt is byte-stable for prompt caching, so mid-session memories
never reach the model through it. The provider therefore builds the top-N
by-importance block **every turn** in `prefetch()` (lean backend scan, no
embedding decode), merges it with the query-recall block, and deduplicates so
nothing appears twice in one turn.

## Backends

A `MemoryBackend` ABC defines CRUD + `keyword_search` + `vector_search`. Two implementations:

- **SQLite**, stdlib, FTS5 for keyword, in-process cosine for vector.
- **pgvector**, PostgreSQL + pgvector for HNSW vector search.

See [backends.md](backends.md).

## Lifecycle

Three maintenance passes, orchestrated by `run_lifecycle()`:

- **cleanup**, remove TTL-expired memories.
- **consolidate**, merge near-duplicates (Jaccard or embedding-cosine, semantic by default). Pinned rules (importance ≥ 0.9) are never deleted as duplicates.
- **prune**, drop low-importance or least-recently-used memories (importance auto-estimated from access, recency, centrality). Pinned rules are exempt. Prune and importance re-estimation are batched at the backend level.

Optional **LLM maintenance** (`run_maintenance()`, or provider `auto_maintain`)
reviews the whole store and keeps/updates/deletes facts semantically.
`health_score()` reports store quality (0-100) across five dimensions.
