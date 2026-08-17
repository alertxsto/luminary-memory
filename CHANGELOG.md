# Changelog

All notable changes to this project are documented in this file. The format follows [Keep a Changelog](https://keepachangelog.com/), and the project adheres to [Semantic Versioning](https://semver.org/).

## [0.1.1] - 2026-08-17

### Fixed

- `MemoryClient.ingest` crashed when `ingest_llm=True` (enricher could be `None`). Now always falls back to a no-op enricher.
- `_parse_dt` crashed on corrupt/non-ISO timestamps in lifecycle and temporal recall. Now falls back safely.
- FTS5 keyword search accepted raw query syntax (`*`, `NEAR`, `OR`, quotes) which could alter query semantics or raise. Queries are now sanitized to plain terms.
- `list()` loaded and sorted all memories in memory; now uses SQL-level pagination (`recent()`).
- CLI commands could print raw tracebacks on backend errors; now caught with a clean error message. `--limit` values are clamped to `>= 1`.
- `WhitelistFilter` crashed on an invalid regex pattern; invalid patterns are now skipped.
- pgvector integration smoke test was a no-op; now a real add/get/search/delete round-trip.

### Added

- Test coverage for pgvector backend raised from 51% to 82% (get/update/delete/count/row parsing).

## [0.1.0] - 2026-08-17

### Added

- SQLite backend with FTS5 keyword search and in-process vector search.
- Optional pgvector backend (HNSW-ready).
- Four-strategy recall: semantic, keyword, temporal, graph.
- Reciprocal Rank Fusion (RRF) + Jaccard dedup + token budget.
- Ingest pipeline with whitelist filter and optional LLM enrichment.
- Lifecycle: TTL cleanup, near-duplicate consolidation, low-value pruning.
- Python API (`MemoryClient`) and CLI (`luminary-memory`).
- Environment-variable configuration (`LUMINARY_*`).
