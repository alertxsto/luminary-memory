# Backends

## SQLite (default)

- Zero-configuration — stdlib `sqlite3` + FTS5.
- Keyword search via FTS5 `MATCH` with `bm25()` ranking.
- Vector search via in-process cosine similarity (linear scan).
- Best for single-user, edge, and stores under ~100k memories.

## pgvector

- Requires a running PostgreSQL with the `vector` extension.
- Keyword search via `ILIKE` with `ESCAPE` handling.
- Vector search via the `<=>` cosine distance operator (HNSW-ready).
- Best for scale and concurrent access.
- Integration tests run against a real Postgres service in CI
  (`.github/workflows/ci.yml`); run them locally with `LUMINARY_PG_DSN`
  (see [CONTRIBUTING.md](../CONTRIBUTING.md)).

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
