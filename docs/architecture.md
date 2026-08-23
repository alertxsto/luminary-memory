# Architecture

## Pipelines

Memory is a **loop**, not a one-shot pipeline: recall happens before the
agent answers, ingest after, lifecycle in the background.

```
ingest(text) ──► whitelist ──► (LLM enrich, optional) ──► hash/evidence/claims ──► embed ──► backend + indexes
                                                                                         │
recall(query) ──► optional graph/content expansion ──► scoped candidates ──► RRF ──► confidence/abstention ──► cutoff ──► dedup/budget ──► results
                                                                                         │
core rules (DB, tag 'core', auto-loaded every session) ──► merged with recall, anti-duplicated
                                                                                         │
lifecycle() ──► cleanup (TTL) ──► consolidate ──► prune ──► max_memories cap + index repair state

Hermes completed-turn path:

sync_turn ──► exact-session episode ledger (continuity only)
          └─► serialized retain ──► evidence-backed summary ──► incremental review
                                      └──────────────► capture / supersede / retract / keep
                                                       (exact scope + current-turn evidence)
```

The episode ledger and durable-memory writer are separate by design. An
accepted automatic turn is recorded as an immutable, exact-session source
episode before curation. That episode can support a short follow-up in the
same session, but it is not a semantic memory, is not returned by normal
recall, and does not count as a durable fact. Only a grounded curated summary
or an explicit write enters the durable memory path.

## Ingest

1. **Whitelist filter**, rejects disallowed text before it reaches any index.
2. **LLM enrichment** (optional), extracts a summary, entities, tags, and
   structured claims. The Hermes provider drops a turn when curation produces
   no durable summary; it does not pollute the store with the raw transcript.
3. **Evidence and identity**, validates the quote, assigns ownership/time
   fields, status, confidence, source, and a normalized content hash.
4. **Claim safety**, exact active duplicates are suppressed within scope by a
   database unique invariant; same-key
   conflicting claims remain versioned until an explicit supersession.
5. **Embed and index**, local CPU embedding plus FTS, graph, evidence, claim,
   episode, and audit records.

## Recall

1. **Query expansion**, short queries are enriched with co-occurring graph entities before embedding (best-effort). When the graph yields nothing, content-token expansion may use a topically-related important memory. No language-specific alias list participates in retrieval.
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

The Hermes provider adds a second, serialized reconciliation pass after the
normal retain task when `ingest_llm` is enabled. It receives only the current
turn and a bounded exact-scope candidate window, then applies structured
decisions through the same writer queue. A correction must be explicit,
evidence-grounded, and claim-aware; similarity or language-specific keywords
never authorize an overwrite. The old row remains in the audit/version chain
after supersession. A failed or malformed review is skipped and cannot kill
the retain worker.

## Injection (Hermes provider)

The provider injects up to three context surfaces per turn (anti-duplicated by
id and content hash, so identical text never appears twice even under
different ids):

- **Core rules** (DB, tag `core`) auto-loaded every session like `MEMORY.md`.
- **Query recall** (retrieval-only) ranked by relevance.
- **Session continuity fallback**, a bounded untrusted reference block from
  recent exact-session episodes, used only when durable recall abstains or
  serializes no usable result. These episodes are not semantic memories and
  never widen the user/workspace/agent/session scope.

The provider also emits a continuity instruction in its system block: resolve
short follow-ups against the immediately active objective before broadening a
request to a history-wide operation. The current user request remains the
authority; recalled memory and quoted session text are reference data.

The importance-based persistent-context block (top-N pinned every turn) was
**removed in v0.2.18**; importance now drives retrieval and pruning only.

### Hermes boundary and upgrades

The integration is capability-based, not version-pinned. Luminary is discovered
through Hermes' `hermes_agent.memory_providers` entry-point group and implements
the public `MemoryProvider` lifecycle. It does not import Hermes' private agent
modules, patch its source tree, or branch on a Hermes version number.

Activation is a configuration decision: `memory.provider` selects Luminary and
the existing `memory.memory_enabled` / `memory.user_profile_enabled` switches
turn off the two native persistent surfaces. The installer edits only that
top-level `memory` block and preserves unrelated YAML. If a Hermes build does
not expose the provider entry point or the documented provider lifecycle, that
is an explicit compatibility failure; Luminary must report it instead of
silently combining two memory authorities.

## Backends

A `MemoryBackend` ABC defines CRUD, keyword/vector search, scope-aware recent
reads, and optional provenance helpers for events, evidence, claims, and
immutable source episodes. Bulk write/read helpers are used by lifecycle and
deduplication paths. Two implementations:

- **SQLite**, stdlib, FTS5 for keyword, in-process cosine for vector.
- **pgvector**, PostgreSQL + pgvector for HNSW vector search.

See [backends.md](backends.md).

## Authority and migration boundary

The Hermes provider is the only persistent authority when
`memory.provider: luminary` is active and the existing Hermes
`memory_enabled` and `user_profile_enabled` switches are false. Luminary does
not merge native files, import them implicitly, or patch Hermes source. For a
store that already contains imported authority snapshots or uncurated Hermes
transcripts, run the read-only repair plan first:

```bash
python scripts/repair_memory_authority.py --db-path ~/.hermes/luminary/memory.db
python scripts/repair_memory_authority.py --db-path ~/.hermes/luminary/memory.db --apply
```

`--apply` creates a SQLite backup and archives the selected rows with an audit
event; it does not delete them. The repair command is a migration aid, not a
new runtime memory authority.

## Lifecycle

Three maintenance passes, orchestrated by `run_lifecycle()`:

- **cleanup**, remove TTL-expired memories.
- **consolidate**, merge near-duplicates (Jaccard or embedding-cosine, semantic by default). Pinned rules (importance ≥ 0.9) are never deleted as duplicates.
- **prune**, drop low-importance or least-recently-used memories (importance auto-estimated from access, recency, centrality). Pinned rules are exempt. Prune and importance re-estimation are batched at the backend level.

Optional **LLM maintenance** (`run_maintenance()`, or provider `auto_maintain`)
reviews the whole store and keeps/updates/deletes facts semantically.
`health_score()` reports store quality (0-100) across five dimensions.

Incremental review and full maintenance are complementary: the former catches
turn-local corrections before a session boundary, while the latter performs a
broader bounded store sweep. Both are best-effort and fail closed on missing
evidence.

All provider-owned writes use strict recall/evidence settings and disable
destructive semantic rule replacement. The direct library client keeps its
legacy replacement default for backwards compatibility; use explicit
`claim_key` + `supersedes_id` when update history matters.
