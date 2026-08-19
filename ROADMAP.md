# Luminary Memory, Product Roadmap

> **Tagline:** A lightweight, self-hosted memory layer for AI agents.

**Current release:** v0.2.17 (gateway envelope unwrap & resilience) · **Tests:** 375+ passing · **Coverage:** 93% · **License:** Apache-2.0

---

## Vision

Every AI agent deserves durable memory that lives on its own infrastructure. Luminary Memory is a self-hosted memory layer that gives agents cross-session persistence with four complementary retrieval strategies (semantic, keyword, temporal, graph) fused into one ranked recall. Private by design, lightweight by construction, scalable when you need it.

### Principles

1. **Private by default**, all data stays on the machine. No cloud, no telemetry, no per-token memory cost.
2. **Lightweight by construction**, SQLite + local CPU embeddings out of the box. No GPU required.
3. **Budget-aware**, memory injection never blows up an agent's context window.
4. **Self-maintaining**, the store keeps itself tidy via lifecycle passes.
5. **Pluggable**, swap backends without touching application code.

---

## Status

| Area | Status |
|------|--------|
| Core library (ingest / recall / lifecycle) | ✅ Done (v0.2.17) |
| Backends (SQLite default, pgvector optional) | ✅ Done (v0.2.14) |
| Python API (`MemoryClient`) | ✅ Done (v0.2.17) |
| CLI (`luminary-memory`) | ✅ Done (v0.2.7) |
| Hermes memory provider | ✅ Done (v0.2.17, 29 dashboard fields) |
| Dashboard settings | ✅ Done (v0.2.16, 100% schema coverage) |
| Recall quality (weighted fusion + query expansion) | ✅ Done (v0.2.15, rule-aware expansion) |
| Persistent context (per-turn importance pinning) | ⛔ Removed (v0.2.18). Importance is retrieval-only now; durable rules live in core memory |
| Core memory (DB-backed, auto-loaded every session) | ✅ Done (v0.2.13, integrity v0.2.15) |
| Adaptive memory (importance on recall, content-level anti-dup) | ✅ Done (v0.2.15) |
| Rule hygiene (pinning, auto-replace, summary-only) | ✅ Done (v0.2.11) |
| Performance (vectorized scans, batched writes) | ✅ Done (v0.2.12) |
| Store hardening (max cap, dedup, selective curation) | ✅ Done (v0.2.12) |
| Gateway resilience (data envelope unwrapping) | ✅ Done (v0.2.17) |
| Website | ✅ Done (v0.2.17) |
| Documentation | ✅ Done (v0.2.17, config-ref + agent-tools) |
| Test coverage | ✅ 93% total |

---

## Release History

| Version | Date | Highlights |
|---------|------|------------|
| v0.1.0 | 2026-08-17 | MVP: 4-strategy recall, SQLite + pgvector, lifecycle, CLI, docs |
| v0.1.1 | 2026-08-17 | Bugfix: enricher crash, FTS5 injection, list() perf, pgvector 82% |
| v0.2.0 | 2026-08-17 | Real LLM enricher, tag-scoped recall, export/import, query planner |
| v0.2.1 | 2026-08-17 | Hermes memory provider (auto-recall/auto-save, 230 ms @5k, 0 tokens) |
| v0.2.2 | 2026-08-18 | (dashboard schema + balanced curation) |
| v0.2.3 | 2026-08-18 | Dashboard schema 18 fields, balanced curation |
| v0.2.4 | 2026-08-18 | Health score, coverage 90% |
| v0.2.5 | 2026-08-18 | Semantic consolidation, auto importance |
| v0.2.6 | 2026-08-18 | Polish: lifecycle logging, CLI metadata, schema 20 fields |
| v0.2.7 | 2026-08-18 | Graph CLI + version command |
| v0.2.8 | 2026-08-18 | Dashboard save fix, docs 20/20, website polish |
| v0.2.9 | 2026-08-18 | pgvector CI (PR #2), contributor tooling (triage/stale/check) |
| v0.2.10 | 2026-08-18 | Smarter recall (weighted fusion + query expansion), store cap, memory fixes |
| v0.2.11 | 2026-08-18 | Persistent context injection, rule pinning + auto-replace, thread-safe recall, store hygiene |
| v0.2.12 | 2026-08-18 | Performance: vectorized rule auto-replace, lean persistent-context scan, batched access bookkeeping, batched lifecycle passes, batched temporal fetch |
| v0.2.13 | 2026-08-18 | Core memory (DB-backed MEMORY.md, auto-loaded every session), keyword recall OR join, prefetch core block |
| v0.2.14 | 2026-08-18 | SQLite backend hardening: FTS5 rebuild migration, dead-code cleanup, 12 new backend tests, backends.md rewrite |
| v0.2.15 | 2026-08-18 | Adaptive memory: importance on recall, rule-aware query expansion, content-level anti-dup, core integrity tests |
| v0.2.16 | 2026-08-19 | Complete dashboard config coverage (29 fields), importance_recall_boost dual config+env, docs/config-reference.md & docs/agent-tools.md, website v0.2.16 |
| v0.2.17 | 2026-08-19 | Gateway resilience: enricher unwrap data envelope (fixes Cline Pass / proxy gateway silent memory curation drops) |
| v0.2.18 | 2026-08-20 | Importance repurposing: removed persistent-context pinning, importance is retrieval-only, core = MEMORY.md rules, recall noise filter + destructive-imperative suppression |

---

## Roadmap

### v0.2.18 — Importance Repurposing: Retrieval-Only (✅ in progress)

- [x] Remove the persistent-context family (`context_top_n`, `context_budget`, `context_min_importance`) from `_DEFAULTS`, `config_schema` (dashboard), and `Settings`.
- [x] Decouple the provider: importance no longer pins memory into the system prompt per turn.
- [x] Core = DB-backed `MEMORY.md`: tagged `core` rules auto-load every session, subordinate label to live instructions.
- [x] Recall noise filter (shell/terminal artifacts) + destructive-imperative suppression (delete/remove/stop).
- [ ] Regression tests, docs sync, skill version bump, release.

### v0.2.17 — Gateway Resilience & Bugfix (✅ released)

- [x] Enricher envelope unwrap — automatic unwrapping of `{"data": {"choices": [...]}}` responses from Cline Pass and OpenAI-compatible proxy gateways.
- [x] Regression tests added (`test_unwrap_data_envelope` & `test_unwrap_data_envelope_plain_shape`).

### v0.2.16 — Complete Dashboard Coverage & Config Reference (✅ released)

- [x] Complete dashboard coverage — 7 missing runtime keys exposed in `CONFIG_SCHEMA` (29 fields total).
- [x] `importance_recall_boost` in provider config & dashboard.
- [x] Authoritative configuration reference (`docs/config-reference.md`).
- [x] Dedicated agent tools reference (`docs/agent-tools.md`).
- [x] Website v0.2.16 update & Agent Tools stat card restructuring.

### v0.2.15 — Adaptive Memory & Core Integrity (✅ released)

- [x] Adaptive importance on recall — frequently-used memories climb into persistent context; pinned rules never downgrade.
- [x] Rule-aware query expansion — rule keywords appended when the graph yields nothing (lossless).
- [x] Content-level anti-duplication — core / persistent / recall dedup by id + content hash.
- [x] Core memory integrity — core sourced only from the DB `core` tag, tested.

### v0.3.0, Multi-User (next)

**Goal:** scoped memory with `user_id` per memory, per-user recall.

- [ ] `user_id` column + schema migration
- [ ] Per-user ingest / recall / list
- [ ] CLI flag + API parameter
- [ ] Dashboard scoping

Details: [docs/PLAN-multi-user.md](./docs/PLAN-multi-user.md)

### v1.0.0, Stable (when ready)

**Goal:** production-ready, API-stable, ecosystem-integrated.

- [ ] API freeze (semver 1.0 contract)
- [ ] Async API (`async def`) for agent loops
- [ ] Web dashboard (browse/query memories via UI)
- [ ] Plugin system for custom retrieval strategies
- [ ] Full benchmark report published (SQLite vs pgvector, issue #6)

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
- [ ] Docs consistent (README / docs/ / skill / website)

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Linear vector scan slow >100k | pgvector backend + HNSW index |
| Google Fonts = external dependency | Self-host fonts (aligns with zero-cloud claim) |
| Store bloat (work-log accumulation) | Selective LLM curation + `max_memories` cap |
| Single-maintainer bus factor | Docs-first culture, CONTRIBUTING guide, issue templates |
| GitHub API instability | Retry with backoff; PyPI as independent publish path |

*Changelog: see [CHANGELOG.md](./CHANGELOG.md).*
