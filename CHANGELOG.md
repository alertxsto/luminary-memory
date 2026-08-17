# Changelog

All notable changes to this project are documented in this file. The format follows [Keep a Changelog](https://keepachangelog.com/), and the project adheres to [Semantic Versioning](https://semver.org/).

## [0.2.1] - Unreleased

### Added

- **Hermes Memory Provider** — `LuminaryMemoryProvider` plugging into Hermes via the `hermes_agent.memory_providers` entry-point group; registered as a standalone package (see PLAN-v0.2.1.md).

## [0.2.0] - 2026-08-18

### Added

- **Query planner** — skips graph/temporal strategies when not needed (conservative v1; semantic + keyword never skipped).
- **Batch ingest** — `ingest_batch()` with single `embed_batch` call and per-item whitelist/enrichment.
- **Export / import** — versioned JSON backup/restore (`export`, `import_memories`, `--include-embeddings`).
- **LLM enricher (provider-agnostic)** — `OpenAICompatibleEnricher` over any OpenAI-compatible endpoint; stdlib-only, passthrough on failure.
- **Result snippets** — matched-fragment highlights attached to recall results.
- **Tag-scoped recall** — `recall(query, tags=[...])`.
- **HNSW index** for pgvector (`pg_hnsw_*` settings, idempotent `build_index()`).
- **Benchmark suite** — `benchmarks/` (latency p50/p95 per strategy + recall@k/MRR, deterministic).
- **CLI JSON output** for `search` and `list` (parity with `recall --json`).
- **`--limit 0` semantics** — unlimited; negative values raise.
- **`updated_at` auto-bump** in `update()`.
- **API docs** generated from docstrings (pdoc → `docs/api/`).
- **GitHub Pages workflow** (`pages.yml` → `/website`).
- **PyPI auto-publish workflow** (`publish.yml`, trusted publishing/OIDC, tag `v*`) + Hermes skill zip release asset.

### Fixed

- Ruff lint: unused-variable in HNSW tests, missing `noqa` on intentional defensive excepts (CI now green).

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
