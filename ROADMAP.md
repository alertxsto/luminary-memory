# Luminary Memory — Product Roadmap

> **Tagline:** A lightweight, self-hosted memory layer for AI agents.

**Current release:** v0.1.1 (bugfix) · **Tests:** 97 passing · **Coverage:** 91% · **License:** Apache-2.0

---

## Vision

Every AI agent deserves durable memory that lives on its own infrastructure. Luminary Memory is a self-hosted memory layer that gives agents cross-session persistence with four complementary retrieval strategies — semantic, keyword, temporal, and graph — fused into one ranked recall. Private by design, lightweight by construction, and scalable when you need it.

### Principles

1. **Private by default** — all data stays on the machine. No cloud, no telemetry, no per-token memory cost.
2. **Lightweight by construction** — SQLite + local CPU embeddings out of the box. No GPU required.
3. **Budget-aware** — memory injection never blows up an agent's context window.
4. **Self-maintaining** — the store keeps itself tidy via lifecycle passes.
5. **Pluggable** — swap backends without touching application code.

---

## Status Overview

| Area | Status |
|------|--------|
| Core library (ingest / recall / lifecycle) | ✅ v0.1.1 |
| Backends (SQLite default, pgvector optional) | ✅ v0.1.1 |
| Python API (`MemoryClient`) | ✅ v0.1.1 |
| CLI (`luminary-memory`) | ✅ v0.1.1 |
| Documentation (docs/, README, CONTRIBUTING, SECURITY) | ✅ v0.1.1 |
| CI (lint + test, Python 3.11/3.12) | ✅ v0.1.1 |
| Packaging (PyPI, GitHub release, tags) | ✅ v0.1.1 |
| Website (landing page) | ✅ v0.1.1 |
| Hermes integration skill | ✅ v0.1.1 |
| Test coverage | ✅ 91% total (pgvector 82%) |

---

## Release History

### v0.1.0 — MVP (2026-08-17)

First public release.

- Four-strategy recall: semantic (ONNX embeddings), keyword (FTS5 BM25), temporal (decay × access), graph (entity co-occurrence)
- RRF fusion + Jaccard dedup + token budget
- SQLite backend (zero-config) + pgvector backend (scale)
- Ingest pipeline: whitelist filter + optional LLM enrichment + local embeddings
- Lifecycle: TTL cleanup, consolidation, pruning
- Python API + CLI
- Full documentation + CI + Hermes skill

### v0.1.1 — Bugfix (2026-08-17)

Post-MVP audit hardening.

- **Fixed:** enricher crash when `ingest_llm=True`
- **Fixed:** timestamp parsing crash on corrupt data (lifecycle/temporal)
- **Fixed:** FTS5 query syntax injection (sanitized to plain terms)
- **Fixed:** `list()` performance (SQL-level pagination)
- **Fixed:** CLI raw tracebacks → clean errors; `--limit` clamped
- **Fixed:** whitelist regex crash on invalid patterns
- **Added:** pgvector test coverage 51% → 82%

---

## Roadmap

### v0.2.0 — Quality & Scale (next)

**Goal:** Production hardening — performance at scale, richer recall, real LLM enrichment.

#### Performance & Scale
- [ ] HNSW index for pgvector (scale beyond 100k memories)
- [ ] Benchmark suite: recall quality vs latency on realistic data
- [ ] Query planner: skip temporal/graph strategies when not needed
- [ ] Batch ingest API for bulk import

#### Recall & Ingest
- [ ] Real LLM enricher implementation (provider-agnostic; replaces `NotImplementedError`)
- [ ] Tag-scoped recall (`recall(query, tags=[...])`)
- [ ] `updated_at` auto-bump in `update()`
- [ ] Result highlights/snippets (matched fragment in keyword/semantic hits)

#### API & CLI
- [ ] JSON output for `search` and `list` (parity with `recall --json`)
- [ ] Export/import memories (backup & restore)
- [ ] `--limit 0` semantics (no limit) instead of error
- [ ] Python API docs generated from docstrings (mkdocstrings / pdoc)

#### Integrations
- [ ] GitHub Pages deployment for website (repo settings → /website)
- [ ] Publish `hermes/SKILL.md` as standalone installable skill
- [ ] PyPI auto-publish workflow (tag → build → upload)
- [ ] README badges (CI, PyPI version, license, Python versions)

---

### v0.3.0 — Intelligence (post-v0.2)

**Goal:** Smarter memory — structure, insight, and visualization.

- [ ] Knowledge graph visualization (entity relations browser)
- [ ] Memory health score (duplicate rate, staleness, importance distribution)
- [ ] Multi-user scoping (`user_id` per memory, per-user recall)
- [ ] Memory importance auto-estimation (recency + access + semantic centrality)
- [ ] Consolidation v2: semantic-aware merging (not just Jaccard token overlap)

---

### v1.0.0 — Stable (when ready)

**Goal:** Production-ready, API-stable, ecosystem-integrated.

- [ ] API freeze (semver 1.0 contract)
- [ ] Async API (`async def`) for agent loops
- [ ] Web dashboard (browse/query memories via UI)
- [ ] Plugin system for custom retrieval strategies
- [ ] Full benchmark report published

---

### v0.2.1 — Hermes Memory Provider ✅ released

**Goal:** Luminary becomes a first-class Hermes memory provider — auto-recall every turn, auto-save every session, matching (and beating) Hindsight's integration with a fraction of the resources.

- [x] Implement `MemoryProvider` ABC as a standalone pip entry-point provider (`luminary_memory.hermes`)
- [x] `prefetch()` / `queue_prefetch()` — auto-recall into agent context each turn
- [x] `on_session_end()` — auto-save conversation turns (buffered `sync_turn`, session-boundary flush)
- [x] `get_tool_schemas()` — expose `luminary_recall` / `luminary_ingest` / `luminary_list` tools
- [x] `system_prompt_block()` — provider context injection
- [x] Register provider: `memory.provider = luminary`
- [x] Benchmark — 230 ms recall p50 @ 5k, 179 MB RSS, **0 LLM tokens** (see `benchmarks/RESULTS.md`)
- [x] Performance: recall 4.1× faster, temporal 7.8×, graph store 3.5× smaller

---

## Completed Work Log (2026-08-17)

Full day-one build from scratch to public release.

| Milestone | Detail |
|-----------|--------|
| Plan | 26 tasks across 8 phases (TDD, exact file paths, verification) |
| Scaffolding | `pyproject.toml`, package structure, CI-ready |
| Schema | SQLite FTS5 + triggers + entities/relations tables |
| Backends | SQLite (zero-config) + pgvector (HNSW-ready) + factory |
| Embeddings | fastembed (BAAI/bge-small-en-v1.5, 384-dim, CPU/ONNX) |
| Ingest | whitelist filter + optional LLM enricher + graph indexing |
| Recall | semantic + keyword + temporal + graph → RRF → dedup → budget |
| Lifecycle | TTL cleanup, consolidation, pruning, runner |
| CLI | `add` / `recall` / `search` / `list` / `lifecycle` / `stats` |
| Docs | 9 pages + README + CONTRIBUTING + SECURITY + CHANGELOG + CODE_OF_CONDUCT |
| CI | lint (ruff) + test (pytest), matrix 3.11/3.12 |
| Website | moonlit editorial landing page (stats, use cases, backends, FAQ, CTA) |
| Publishing | PyPI 0.1.0 + 0.1.1, GitHub releases, tags, SOCIAL.md copy |
| Audit | full code/test/CLI/website/infra/security audit, all criticals fixed |
| History hygiene | `.commandcode/` + `SOCIAL.md` scrubbed from git history |

---

## Definition of Done (per release)

- [ ] All tests pass (`pytest -q`)
- [ ] `ruff check src tests` clean
- [ ] CLI smoke: `luminary-memory --help`
- [ ] Coverage maintained ≥ 90%
- [ ] CHANGELOG updated
- [ ] Version bumped (semver)
- [ ] Tag + GitHub release + PyPI upload
- [ ] Website badge updated (if version displayed)

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Linear vector scan slow >100k | pgvector backend + HNSW index (v0.2) |
| Google Fonts = external dependency | Self-host fonts (v0.2, aligns with "zero cloud" claim) |
| LLM enricher unimplemented | Noop default; real provider-agnostic enricher in v0.2 |
| Single-maintainer bus factor | Docs-first culture, CONTRIBUTING guide, issue templates |
| GitHub API instability (incidents observed) | Retry with backoff; PyPI as independent publish path |

---

*Implementation detail: see [PLAN.md](./PLAN.md). Changelog: see [CHANGELOG.md](./CHANGELOG.md).*
