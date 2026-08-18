# Architecture

## Pipelines

Memory is a **loop**, not a one-shot pipeline: recall happens before the
agent answers, ingest after, lifecycle in the background.

```
ingest(text) ──► whitelist filter ──► (LLM enrich, optional) ──► embed ──► backend
                                                                          │
recall(query) ──► query expansion ──► 4 strategies ──► weighted RRF ──► adaptive cutoff ──► dedup ──► budget ──► results
                                        │
lifecycle() ──► cleanup (TTL) ──► consolidate (semantic) ──► prune (importance) ──► max_memories cap
```

## Ingest

1. **Whitelist filter**, drops noise and non-durable text (configurable regex).
2. **LLM enrichment** (optional), extracts a summary, entities, and tags. Provider-agnostic; a no-op by default so ingest works offline.
3. **Embed**, local CPU embedding (fastembed / ONNX).
4. **Store**, persists content, metadata, tags, timestamps, and the embedding to the backend.

## Recall

1. **Query expansion**, short queries are enriched with co-occurring graph entities before embedding (best-effort).
2. **Four strategies run in parallel:**
   - *semantic*, embedding similarity.
   - *keyword*, FTS5 / BM25 term match.
   - *temporal*, recency decay × access popularity.
   - *graph*, entity co-occurrence traversal.
3. **Weighted RRF fusion**, reciprocal-rank fusion with per-strategy weights (semantic 0.4, keyword 0.3, graph 0.2, temporal 0.1) combines the four ranked lists into one.
4. **Adaptive cutoff** (cliff detection), cuts at the first steep score drop (default 45%) so a sparse store returns only the relevant cluster instead of padding to the limit.
5. **Dedup**, Jaccard similarity removes near-duplicates.
6. **Budget**, results truncated to a token budget so the context window stays safe.

## Backends

A `MemoryBackend` ABC defines CRUD + `keyword_search` + `vector_search`. Two implementations:

- **SQLite**, stdlib, FTS5 for keyword, in-process cosine for vector.
- **pgvector**, PostgreSQL + pgvector for HNSW vector search.

See [backends.md](backends.md).

## Lifecycle

Three maintenance passes, orchestrated by `run_lifecycle()`:

- **cleanup**, remove TTL-expired memories.
- **consolidate**, merge near-duplicates (Jaccard or embedding-cosine, semantic by default).
- **prune**, drop low-importance or least-recently-used memories (importance auto-estimated from access, recency, centrality).

Optional **LLM maintenance** (`run_maintenance()`, or provider `auto_maintain`)
reviews the whole store and keeps/updates/deletes facts semantically.
`health_score()` reports store quality (0-100) across five dimensions.
