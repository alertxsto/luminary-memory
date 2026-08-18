# Changelog

## [0.2.12] - 2026-08-18

### Added

- **Vectorized rule auto-replace** — the anti-contradiction scan now uses a single numpy matmul over stored embeddings (`scan_embeddings_matrix`), ~40× faster than the per-memory Python cosine loop on a 5k store, with identical results.
- **Lean persistent-context scan** — the per-turn top-N-by-importance build (`top_by_importance`) reads only `id/content/importance/access_count` columns, never embedding blobs: ~100 ms → ~5 ms on a 5k store.
- **Batched access bookkeeping** — recalled memories are marked accessed in one `UPDATE ... WHERE id IN (...)` (`touch_memories`) instead of one write per result row.
- **Batched lifecycle passes** — prune uses `delete_many`, importance re-estimation uses `update_importances`; one statement per pass instead of one write per memory.
- **Batched temporal fetch** — temporal recall fetches top ids with one `SELECT ... WHERE id IN (...)` (`get_many`) instead of N per-id queries: ~30-67 ms → ~16-19 ms on 5k.

### Performance (5k store, real ONNX embeddings)

| Stage | Before | After |
|-------|--------|-------|
| Persistent context (per turn) | ~100 ms | ~5 ms (20×) |
| Rule auto-replace scan | ~500 ms | ~26 ms (19×) |
| Temporal recall | ~30-67 ms | ~16-19 ms |
| End-to-end recall | ~93 ms p50 | ~70-92 ms p50 |

Accuracy is unchanged: benchmark quality metrics (recall@5 / recall@10 / MRR) are byte-identical before and after optimization.

### Fixed

- No functional changes — all optimizations verified to preserve recall results exactly.

## [0.2.11] - 2026-08-18

### Added

- **Persistent context injection** — the system prompt injects top-N memories by importance (configurable `context_top_n` / `context_budget` / `context_min_importance`), so durable rules are always visible regardless of query.
- **Rule pinning** — memories at importance ≥ 0.9 are pinned: they survive lifecycle prune and consolidation (never deleted as duplicates or pruned by the max-count cap).
- **Rule auto-replace (anti-contradiction)** — ingesting a rule semantically similar to an existing one (cosine ≥ `rule_auto_replace_threshold`, default 0.85) replaces it in place instead of stacking conflicting rows.
- **Per-turn persistent context** — the persistent-context build runs on every prefetch (not just session-start system prompt), so memories ingested mid-session reach the model; merged with query recall under anti-duplication.
- **Recall hook notification** — Telegram hook (`luminary-activity`) surfaces stored/recalled memories to the chat.

### Fixed

- **Prefetch recall cross-thread crash** — SQLite thread-local connections; background recall no longer crashes with `ProgrammingError`, so recall actually triggers.
- **`max_tokens` sent in enricher LLM call** — Command Code returned empty content without it (issue #8); configurable via `LUMINARY_LLM_MAX_TOKENS`.
- **Raw transcripts pinned as rules** — rule keywords are now checked only against the LLM-curated summary, never the raw turn text; a transcript that merely mentions a keyword is no longer flagged importance 0.9.
- **Raw-transcript store pollution** — with `ingest_llm` on, turns whose curation yields no summary are dropped instead of stored verbatim.
- **Dashboard config save** — `save_config` accepts the `hermes_home` argument (dashboard contract).

## [0.2.10] - 2026-08-18

### Added

- **Smarter recall** — weighted RRF fusion (semantic 0.4, keyword 0.3, graph 0.2, temporal 0.1) so high-signal strategies dominate; query expansion appends co-occurring graph entities to short queries before embedding.
- **`max_memories` store cap** — hard limit on store size (default 1000); oldest/lowest-importance memories pruned when exceeded. Configurable via dashboard (21 settings).

### Fixed

- **Memory store overflow** — the LLM curation prompt is now selective (no duplicates, one fact per entry, skip meta-talk), so work-log turns no longer bloat the store (139 → 46 memories after cleanup).
- **`import_memories` dedup guard** — bulk imports (e.g. MEMORY.md/USER.md merges) skip content that already exists, reporting `skipped_duplicates`.
- **SQLite cross-thread close crash** — `close()` no longer raises when the connection is owned by another thread (provider writer-thread shutdown).

### Website

- Redesigned benchmarks (line table in panel), architecture (turn-loop flow), use cases (narrative list) — moonlit editorial preserved, contrast fixed (text-faint 3.9:1 → 7:1), zero em-dashes.

## [0.2.9] - 2026-08-18

### Added

- **pgvector integration tests in CI** — real Postgres service (HNSW index, JSONB round-trips, update, by_tags, delete) — contribution from @qtjg (PR #2).
- **`add_many` rollback fix** — pgvector batch insert now rolls back and re-raises on failure (mirrors the SQLite backend). Contribution from @qtjg (PR #2).
- **Three new CI workflows:**
  - **Triage** — auto-labels issues/PRs, welcomes first-time contributors.
  - **Stale** — auto-closes inactive issues/PRs (exempts `help wanted` / `good first issue`).
  - **Contributor check** — soft account + language triage hint for maintainers on every PR.
- **Branch protection on `main`** — required status checks + PR review; `develop` is the integration branch.
- **`CONTRIBUTING.md`** — AI assistance notice, branch model, automated checks section, updated pgvector instructions.

## [0.2.8] - 2026-08-18

### Fixed

- **Dashboard save bug** — `consolidate_semantic` and `importance_auto` were missing from `_DEFAULTS`, so the Hermes dashboard rendered them but silently dropped the values on save. Now persisted correctly.

### Docs

- `docs/hermes-integration.md` — config table now covers all **20 provider settings** (added `retain_user_prefix`, `retain_assistant_prefix`, `consolidate_semantic`, `importance_auto`).

### Website

- New use-case card **"A Graph You Can See"** (showcases `luminary-memory graph`).
- New FAQ: **"Can I see how my memories connect?"**.

## [0.2.7] - 2026-08-18

### Added

- **`MemoryClient.graph()`** — returns the knowledge graph as `{entities: [{name, degree, memories}], relations: [{source, target, weight}]}`. Empty-store and non-SQLite safe.
- **`luminary-memory graph` CLI** — top entities as a table (degree + memory count), `--relations` for edges, `--json` for raw output, `--limit`.
- **`luminary-memory version`** — prints installed version + Python runtime.

### Changed

- Roadmap v0.3.0: graph visualization (CLI phase) ticked.

All notable changes to this project are documented in this file. The format follows [Keep a Changelog](https://keepachangelog.com/), and the project adheres to [Semantic Versioning](https://semver.org/).

## [0.2.6] - 2026-08-18

### Polish & hardening

- **Lifecycle logging** — `cleanup`, `consolidate` (mode + merged count), `prune`, and `run_lifecycle` (result + duration) now log their activity; `estimate_importance` logs via the runner.
- **SQLite batch errors logged** — `add_many` failures log the exception before rollback/re-raise (was silent).
- **CLI recall JSON richer** — each memory now includes `source`, `created_at`, and `importance`.
- **Env var warnings** — invalid `LUMINARY_*` int/float values warn instead of silently falling back.
- **Dashboard schema 20 fields** — `consolidate_semantic` (Semantic consolidation) and `importance_auto` (Auto importance estimation) added to the Hermes provider config.
- **`recall(limit=0)` truly unlimited** — passes `None` to backends instead of a 10k magic cap.
- **Dedup capped window** — `dedup_jaccard(max_pairs=500)` keeps recall O(n·k) instead of O(n²) on large result sets.
- **`import_memories` error logging** — failures log the path before re-raise.
- **pgvector JSON columns safe** — `metadata`/`tags` parse via a `_json_load` helper (corrupt data falls back instead of crashing); HNSW index failure now logged.
- **Prefetch thread join** — `queue_prefetch` joins any in-flight worker before spawning a new one (no thread leak / stale-cache overwrite).
- **Degenerate embedding guard** — semantic consolidation falls back to Jaccard when embeddings are all-equal (no false merges of unrelated memories).
- **`CONTRIBUTING.md`** — new Testing section (Postgres/pgvector setup, coverage ≥ 90%) pointing at [issue #1](https://github.com/alertxsto/luminary-memory/issues/1) (add Postgres to CI).

## [0.2.5] - 2026-08-18

### Added

- **Semantic consolidation** — `consolidate(semantic=True)` merges memories by embedding-cosine similarity (default `LUMINARY_CONSOLIDATE_SEMANTIC=true`), catching paraphrases that token-overlap misses; falls back to Jaccard when embeddings are missing. CLI: `luminary-memory lifecycle --semantic/--no-semantic`.
- **Auto importance estimation** — `lifecycle/importance.py:estimate_importance()` scores each memory from access (`log1p`), recency (24h decay), and graph centrality; applied on ingest and re-estimated before every prune (`LUMINARY_IMPORTANCE_AUTO=true`). Pruning and the health score's importance dimension now use live values.

### Changed

- `run_lifecycle()` now also re-estimates importances (returns `reestimated` count).

## [0.2.4] - 2026-08-18

### Added

- **`MemoryClient.health_score()`** — store health report (0-100) across five dimensions: duplicate rate, staleness, importance, graph density, and size — plus actionable recommendations. Empty store scores 100.
- **`luminary-memory health` CLI** — human-readable bar + `--json` output.
- **Test coverage raised 82% → 90%** (roadmap DoD): config_schema standalone shim, enricher `_call_llm`/`review_memories` paths, maintenance CRUD edges, provider lifecycle/maintenance/shutdown, CLI whitelist/limit errors, recall strategy failure fallbacks.

### Fixed

- **`run_maintenance` bad-response detection** — `data.get("actions") or []` masked non-list responses as "no actions"; now correctly reports `{"error": "bad LLM response"}`.

## [0.2.3] - 2026-08-18

### Added

- **Hermes dashboard config schema** — exposes 18 luminary settings (mode, backend, recall limit, token budget, auto-recall/retain, **LLM memory curation**, **auto-maintain**, LLM endpoint, indicators) in the Hermes dashboard Provider panel. `auto_maintain` added; `ingest_llm` label corrected to "LLM memory curation".

### Changed

- **Balanced LLM curation** — the enricher now rejects work/task logs and meta-talk about the memory system itself, while still keeping durable facts (not over-strict). Verified: work logs → `worth_saving: false`; facts → stored.

## [0.2.2] - 2026-08-18

### Added

- **LLM memory curation** — with `ingest_llm: true`, the provider's enricher evaluates every retained turn:
  - `worth_saving` — chit-chat, greetings, and trivial turns are **dropped** instead of polluting the store.
  - `summary` — kept turns are stored as concise factual summaries (e.g. `"Deploy target is the staging cluster."`) instead of raw `User: ... / Assistant: ...` transcripts.
  - `entities` / `tags` — attached for richer recall.
- **LLM store maintenance** — `MemoryClient.run_maintenance()` + provider `auto_maintain` (session-end): the LLM reviews the store and **deletes obsolete/contradicted/duplicate facts**, **updates changed ones**, and **keeps** current ones (verified: stale deploy target auto-removed).
- **Transparency log** — provider writes `$HERMES_HOME/luminary/luminary.log` recording initialize/recall/retain/maintenance/errors.
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
