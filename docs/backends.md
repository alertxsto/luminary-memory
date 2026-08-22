# Backends

## SQLite (default)

- Zero-configuration, stdlib `sqlite3` + FTS5.
- Keyword search via FTS5 `MATCH` with `bm25()` ranking. Queries are
  injection-safe: raw text is sanitized, each term quoted, and joined with
  `OR` so a natural multi-term query matches any of its terms (plus `bm25`
  lifts the ones that match several).
- **External-content FTS5**: `memories_fts` does not duplicate the data; it is
  kept in sync by `AFTER INSERT/UPDATE/DELETE` triggers on `memories`. When a
  database created by an older schema is opened (predating the FTS virtual
  table), `init_schema` detects it and runs a one-time FTS `rebuild` so
  pre-existing rows become keyword-searchable.
- Vector search via in-process cosine similarity (vectorized matmul over a
  float32 embedding matrix — no per-row Python loop).
- **Thread-local connections**: each thread owns its own SQLite connection, so
  a background recall thread and the writer thread never trip
  `sqlite3.ProgrammingError`. `close()` only touches the caller's thread-local
  connection.
- **Lean scans** power the per-turn core/recall blocks and avoid
  decoding the (large) embedding blobs for every row:
  `top_by_importance`, `by_tag_top`, `temporal_scan`, `scan_embeddings`,
  `scan_embeddings_matrix`. Writes are batched (`touch_memories`,
  `update_importances`, `add_many`, `delete_many`).
- Best for single-user, edge, and stores under ~100k memories (vector search
  is a linear scan). Each thread uses its own connection and the backend
  enables SQLite WAL with a busy timeout on writable file stores, so Hermes'
  background reader/writer paths can coexist. WAL setup is best-effort for
  in-memory, read-only, or otherwise restricted paths.
- Accuracy filters (`scope`, `status`, validity windows, and tags) are applied
  in backend queries where supported and defensively again in the orchestrator
  before fusion/fallback. Scope-aware indexes cover ownership, status, claim
  keys, and content hashes.
- Exact active deduplication is a database invariant, not only an API
  pre-check: `uq_memories_active_scope_hash` covers the normalized ownership
  tuple plus `content_hash`. Concurrent writers resolve the winning row and
  the API avoids writing duplicate episode/evidence/graph lineage.

## pgvector

- Requires a running PostgreSQL with the `vector` extension.
- Keyword search via `ILIKE` with `ESCAPE` handling.
- Vector search via the `<=>` cosine distance operator (HNSW-ready).
- Best for scale and concurrent access.
- The same ownership, status, evidence, claim, and supersession fields are
  stored so switching backends does not change the public accuracy contract.
- Integration tests run against a real Postgres service in CI
  (`.github/workflows/ci.yml`); run them locally with `LUMINARY_PG_DSN`
  (see [CONTRIBUTING.md](../CONTRIBUTING.md)).
- Schema initialization backfills legacy hashes, collapses exact active
  duplicates while rehoming derived references, and installs the same scoped
  unique invariant as SQLite. Unique-conflict recovery rolls back the failed
  transaction and closes its lookup snapshot, which matters for long-lived
  writer connections.

## Choosing

| Need | Backend |
|------|---------|
| Zero setup, one agent | SQLite |
| Large store, many queries | pgvector |
| Concurrent agents | pgvector |

## Migrating from SQLite to pgvector

1. Set `LUMINARY_BACKEND=pgvector` and `LUMINARY_PG_DSN`.
2. Re-ingest your memories (the schemas differ in column types).
3. Optionally add an HNSW index on the `embedding` column for scale.

## Adding a new backend

Implement the `MemoryBackend` ABC (`add`, `get`, `update`, `delete`, `all`, `keyword_search`, `vector_search`, `count`) and register it in `backends/__init__.py`.
