# Luminary Memory, Product Roadmap

> **Tagline:** A lightweight, self-hosted memory layer for AI agents.

**Current release:** v0.2.11 (smarter recall + memory fixes) · **Tests:** 200+ passing · **Coverage:** 91% · **License:** Apache-2.0

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
| Core library (ingest / recall / lifecycle) | ✅ Done (v0.2.10) |
| Backends (SQLite default, pgvector optional) | ✅ Done (v0.2.9) |
| Python API (`MemoryClient`) | ✅ Done (v0.2.10) |
| CLI (`luminary-memory`) | ✅ Done (v0.2.7) |
| Hermes memory provider | ✅ Done (v0.2.1, enhanced v0.2.10) |
| Dashboard settings (22 fields) | ✅ Done (v0.2.10) |
| Recall quality (weighted fusion + query expansion) | ✅ Done (v0.2.10) |
| Store hardening (max cap, dedup, selective curation) | ✅ Done (v0.2.10) |
| Website | ✅ Done (v0.2.10 redesign) |
| Documentation | ✅ Done (v0.2.10) |
| Test coverage | ✅ 91% total |

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

---

## Roadmap

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
