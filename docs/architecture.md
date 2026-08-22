# Architecture

## Pipelines

Memory is a **loop**, not a one-shot pipeline: recall happens before the
agent answers, ingest after, lifecycle in the background.

```
ingest(text) ──► whitelist ──► (LLM enrich, optional) ──► hash/evidence/claims ──► embed ──► backend + indexes
                                                                                         │
recall(query) ──► aliases ──► scoped candidates ──► RRF ──► confidence/abstention ──► cutoff ──► dedup/budget ──► results
                                                                                         │
core rules (DB, tag 'core', auto-loaded every session) ──► merged with recall, anti-duplicated
                                                                                         │
lifecycle() ──► cleanup (TTL) ──► consolidate ──► prune ──► max_memories cap + index repair state
```

## Ingest

1. **Whitelist filter**, rejects disallowed text before it reaches any index.
2. **LLM enrichment** (optional), extracts a summary, entities, tags, and
   structured claims. The Hermes provider drops a turn when curation produces
   no durable summary; it does not pollute the store with the raw transcript.
3. **Evidence and identity**, validates the quote, assigns ownership/time
   fields, status, confidence, source, and a normalized content hash.
4. **Claim safety**, exact duplicates are suppressed within scope; same-key
   conflicting claims remain versioned until an explicit supersession.
5. **Embed and index**, local CPU embedding plus FTS, graph, evidence, claim,
   episode, and audit records.

## Recall

1. **Query expansion**, short queries are enriched with co-occurring graph entities before embedding (best-effort). When the graph yields nothing, rule-aware query expansion adds keywords from a topically-related durable rule.
2. **Four scoped strategy candidates:**
   - *semantic*, embedding similarity (vectorized cosine matmul).
   - *keyword*, FTS5 / BM25 term match.
   - *temporal*, recency decay × access popularity (batched top-id fetch, no N+1).
   - *graph*, entity co-occurrence traversal (SQL aggregation).
3. **Weighted RRF fusion**, reciprocal-rank fusion with per-strategy weights (semantic 0.4, keyword 0.3, graph 0.2, temporal 0.1) combines the available ranked lists into one.
4. **Accuracy gate**, current status/validity/scope/tag filters, evidence-aware
   confidence, and strict abstention run before fallback serialization.
5. **Importance boost**, memories at importance ≥ 0.8 get a ranking bonus
   (`importance_recall_boost`) without becoming an always-injected prompt tier.
6. **Adaptive cutoff** (cliff detection), cuts at the first steep score drop
   so a sparse store returns only the relevant cluster instead of padding.
7. **Dedup and budget**, Jaccard similarity removes near-duplicates and the
   token budget caps serialized context.
8. **Batched access bookkeeping**, recalled memories are marked accessed with
   one batched update and importance is re-estimated for the next query.

## Injection (Hermes provider)

The provider injects two things per turn (anti-duplicated by id and content
hash, so identical text never appears twice even under different ids):

- **Core rules** (DB, tag `core`) auto-loaded every session like `MEMORY.md`.
- **Query recall** (retrieval-only) ranked by relevance.

The importance-based persistent-context block (top-N pinned every turn) was
**removed in v0.2.18**; importance now drives retrieval and pruning only.

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

All provider-owned writes use strict recall/evidence settings and disable
destructive semantic rule replacement. The direct library client keeps its
legacy replacement default for backwards compatibility; use explicit
`claim_key` + `supersedes_id` when update history matters.
