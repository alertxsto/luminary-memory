# Luminary Memory — Roadmap

> A lightweight, self-hosted memory layer for AI agents.

**Status:** v0.1.0 released · **Next:** v0.2.0 (post-MVP polish)

---

## Progress Tracker

| Phase | Description | Status |
|-------|-------------|--------|
| 0 | Scaffolding & CI | ✅ Done |
| 1 | Schema & SQLite FTS5 Backend | ✅ Done |
| 2 | Embeddings & Ingest | ✅ Done |
| 3 | Four Retrieval Strategies | ✅ Done |
| 4 | RRF Fusion + Dedup + Budget | ✅ Done |
| 5 | Lifecycle | ✅ Done |
| 6 | pgvector Backend | ✅ Done |
| 7 | CLI + Python API + Docs | ✅ Done |
| 8 | Website (landing page) | ✅ Done |

---

## Roadmap

### Phase 0 — Scaffolding & CI (Day 1, morning) ✅
- [x] Task 0.1: Initialize project skeleton (`pyproject.toml`, `.gitignore`, package init)
- [x] Task 0.2: Configuration & core types (`config.py`, `types.py`)

### Phase 1 — Schema & SQLite FTS5 Backend (Day 1, afternoon) ✅
- [x] Task 1.1: Schema DDL + migration runner (`schema.py` — memories + FTS5 + triggers + entities/relations)
- [x] Task 1.2: Backend ABC + SQLite backend (`backends/base.py`, `backends/sqlite.py`)

### Phase 2 — Embeddings & Ingest (Day 1 evening → Day 2 morning) ✅
- [x] Task 2.1: Fastembed wrapper (CPU, bge-small-en-v1.5, 384d)
- [x] Task 2.2: Whitelist regex filter (strong-signal fact extraction)
- [x] Task 2.3: Ingest pipeline (whitelist → embed → store) + optional LLM enrichment

### Phase 3 — Four Retrieval Strategies (Day 2) ✅
- [x] Task 3.1: Semantic recall (vector similarity)
- [x] Task 3.2: Keyword recall (FTS5 BM25)
- [x] Task 3.3: Temporal recall (recency/access patterns)
- [x] Task 3.4: Graph-lite recall (entity co-occurrence)

### Phase 4 — RRF Fusion + Dedup + Budget (Day 3, morning) ✅
- [x] Task 4.1: RRF fusion (combine strategy rankings)
- [x] Task 4.2: Jaccard dedup (remove near-duplicates)
- [x] Task 4.3: Token budget manager (context window safety)
- [x] Task 4.4: Recall orchestrator (4 strategies → RRF → dedup → budget)

### Phase 5 — Lifecycle (Day 3, afternoon) ✅
- [x] Task 5.1: Cleanup (TTL expiry)
- [x] Task 5.2: Consolidate (merge near-duplicates)
- [x] Task 5.3: Prune (low-importance / LRU)
- [x] Task 5.4: Lifecycle runner + CLI command

### Phase 6 — pgvector Backend (Day 4) ✅
- [x] Task 6.1: pgvector backend implementation
- [x] Task 6.2: Backend factory & config wiring

### Phase 7 — CLI + Python API polish + Docs (Day 4 evening → Day 5) ✅
- [x] Task 7.1: Complete CLI (typer + rich)
- [x] Task 7.2: Final Python API (`MemoryClient`)
- [x] Task 7.3: README + LICENSE + Hermes skill
- [x] Task 7.4: Documentation structure (CONTRIBUTING, CHANGELOG, SECURITY, docs/, .github/)
- [x] Task 7.5: Final verification & release prep

### Phase 8 — Website (post-MVP, Day 5) ✅
- [x] Task 8.1: Landing page (moonlit editorial design)
- [x] Task 8.2: Stats, use cases, backends, FAQ, final CTA sections
- [x] Task 8.3: Reveal animation fix (progressive enhancement)
- [x] Task 8.4: Deploy readiness (`.nojekyll`, GitHub Pages structure)

---

## Definition of Done (MVP v0.1.0) ✅

- [x] All pytest tests pass (89 passed, 1 skipped)
- [x] `ruff check src tests` clean
- [x] `luminary-memory --help` CLI runs
- [x] Recall works with all 4 strategies
- [x] Public Apache-2.0 repo + README + Hermes skill

---

## Release & Publishing Checklist ✅

- [x] Tag `v0.1.0` + GitHub release
- [x] PyPI publish (https://pypi.org/project/luminary-memory)
- [x] Social announcement copy (SOCIAL.md)
- [x] Screenshot demo: add + recall in terminal
- [ ] README badges: license, CI, PyPI, Python versions

---

## Post-MVP Ideas (v0.2.0+)

- [ ] README badges (CI status, PyPI version)
- [ ] GitHub Pages deploy (enable in repo settings)
- [ ] HNSW index for pgvector (noted TODO in backend)
- [ ] CLI `--json` polish + exit codes docs
- [ ] Benchmark suite (recall quality vs latency)
- [ ] `hermes/SKILL.md` → published as standalone skill

---

*Full implementation detail (code, TDD steps, verification) in [PLAN.md](./PLAN.md).*
