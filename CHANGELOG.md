# Changelog

All notable changes to this project are documented in this file. The format follows [Keep a Changelog](https://keepachangelog.com/), and the project adheres to [Semantic Versioning](https://semver.org/).

## [0.2.2] - 2026-08-18

### Added

- **LLM memory curation** — with `ingest_llm: true`, the provider's enricher evaluates every retained turn:
  - `worth_saving` — chit-chat, greetings, and trivial turns are **dropped** instead of polluting the store.
  - `summary` — kept turns are stored as concise factual summaries (e.g. `"Deploy target is the staging cluster."`) instead of raw `User: ... / Assistant: ...` transcripts.
  - `entities` / `tags` — attached for richer recall.
- **Transparency log** — provider writes `$HERMES_HOME/luminary/luminary.log` recording initialize/recall/retain/errors.
- **`OpenAICompatibleEnricher` User-Agent header** — required by some OpenAI-compatible gateways (e.g. Command Code 403s without it).

### Fixed

- **Shutdown SQLite thread-affinity crash** — the writer thread now closes its own client (closing from the main thread raised `sqlite3.ProgrammingError`).
- **Hermes installer** — `hermes/install.sh` gains `--llm` (enables memory curation), handles a missing `config.yaml`, and no longer warns about the missing `[hermes]` extra (now declared).

## [0.2.1] - 2026-08-18

### Added

- **Hermes Memory Provider** — `LuminaryMemoryProvider` plugging into Hermes via the `hermes_agent.memory_providers` entry-point group; registered as a standalone package.
  - **Auto-recall every turn** — warm background prefetch (`queue_prefetch` → cached `prefetch`) or synchronous recall (`recall_sync`), formatted as a deterministic context block.
  - **Auto-save every session** — buffered `sync_turn` on a single writer thread, batched by `retain_every_n_turns`, with session/parent/platform/agent lineage tags.
  - **Session-boundary handling** — `on_session_end` flush + `on_session_switch` rebind with reset guard.
  - **Explicit tools** — `luminary_recall`, `luminary_ingest`, `luminary_list` (OpenAI-format schemas, JSON dispatch, local error helper).
  - **Deterministic indicator** — `RecallStatus("Luminary", count, 🌙)` surfaced via `recall_status()`.
  - **Config layer** — `$HERMES_HOME/luminary/config.json` (0600, atomic write), `get_config_schema()`, dashboard `config_schema.py` (pure data).
  - **Lifecycle hooks** — `is_available`, `initialize`, `shutdown`, `system_prompt_block`, `on_memory_write`, `on_delegation`, `on_pre_compress`, `backup_paths`.
  - **Packaging** — entry point + `plugin.yaml` directory-install fallback.
  - **Test harness** — `tests/hermes_stubs/agent/memory_provider.py` ABC stub injected via `tests/conftest.py` so tests run without a hermes-agent install.
- **`MemoryClient.ingest(metadata=...)`** — optional metadata dict merged into stored memory metadata (backward compatible).

### Performance (identical results, no approximation)

- **Vectorized cosine similarity** — per-row numpy loop → single matmul; recall @ 5k memories **3,400 ms → 832 ms (4.1×)**.
- **SQL graph aggregation** — 210k relation rows → `SUM/COUNT ... GROUP BY` in the database.
- **`temporal_scan()`** — temporal recall fetches only `(id, created_at, access_count)`; **486 ms → 62 ms (7.8×)**.
- **Relation cap (8/memory) + indexes** — dense graph (280k rows) → sparse (80k); store 3.5× smaller; ingest 1.6× faster.

### Fixed

- `config_schema.py` import fallback — module now imports standalone (no hermes runtime) so CI is green on 3.11/3.12.
- Publish workflow — skill zip moved out of `dist/` (invalid distribution); dropped `generate_release_notes` (permission).

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
