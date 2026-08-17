# Luminary Memory — Roadmap

> A lightweight, self-hosted memory layer for AI agents.

**Status:** MVP in development · **Target:** v0.1.0 (5 days)

---

## Progress Tracker

| Phase | Description | Status |
|-------|-------------|--------|
| 0 | Scaffolding & CI | ✅ Done |
| 1 | Schema & SQLite FTS5 Backend | ✅ Done |
| 2 | Embeddings & Ingest | ⬜ Pending |
| 3 | Four Retrieval Strategies | ⬜ Pending |
| 4 | RRF Fusion + Dedup + Budget | ⬜ Pending |
| 5 | Lifecycle | ⬜ Pending |
| 6 | pgvector Backend | ⬜ Pending |
| 7 | CLI + Python API + Docs | ⬜ Pending |

---

## Roadmap

### Phase 0 — Scaffolding & CI (Day 1, morning) ✅
- [x] Task 0.1: Initialize project skeleton (`pyproject.toml`, `.gitignore`, package init)
- [x] Task 0.2: Configuration & core types (`config.py`, `types.py`)

### Phase 1 — Schema & SQLite FTS5 Backend (Day 1, afternoon) ✅
- [x] Task 1.1: Schema DDL + migration runner (`schema.py` — memories + FTS5 + triggers + entities/relations)
- [x] Task 1.2: Backend ABC + SQLite backend (`backends/base.py`, `backends/sqlite.py`)

### Phase 2 — Embeddings & Ingest (Day 1 evening → Day 2 morning)
- [ ] Task 2.1: Fastembed wrapper (CPU, bge-small-en-v1.5, 384d)
- [ ] Task 2.2: Whitelist regex filter (strong-signal fact extraction)
- [ ] Task 2.3: Ingest pipeline (whitelist → embed → store) + optional LLM enrichment

### Phase 3 — Four Retrieval Strategies (Day 2)
- [ ] Task 3.1: Semantic recall (vector similarity)
- [ ] Task 3.2: Keyword recall (FTS5 BM25)
- [ ] Task 3.3: Temporal recall (recency/access patterns)
- [ ] Task 3.4: Graph-lite recall (entity co-occurrence)

### Phase 4 — RRF Fusion + Dedup + Budget (Day 3, morning)
- [ ] Task 4.1: RRF fusion (combine strategy rankings)
- [ ] Task 4.2: Jaccard dedup (remove near-duplicates)
- [ ] Task 4.3: Token budget manager (context window safety)
- [ ] Task 4.4: Recall orchestrator (4 strategies → RRF → dedup → budget)

### Phase 5 — Lifecycle (Day 3, afternoon)
- [ ] Task 5.1: Cleanup (TTL expiry)
- [ ] Task 5.2: Consolidate (merge near-duplicates)
- [ ] Task 5.3: Prune (low-importance / LRU)
- [ ] Task 5.4: Lifecycle runner + CLI command

### Phase 6 — pgvector Backend (Day 4)
- [ ] Task 6.1: pgvector backend implementation
- [ ] Task 6.2: Backend factory & config wiring

### Phase 7 — CLI + Python API polish + Docs (Day 4 evening → Day 5)
- [ ] Task 7.1: Complete CLI (typer + rich)
- [ ] Task 7.2: Final Python API (`MemoryClient`)
- [ ] Task 7.3: README + LICENSE + Hermes skill
- [ ] Task 7.4: Documentation structure (CONTRIBUTING, CHANGELOG, SECURITY, docs/, .github/)
- [ ] Task 7.5: Final verification & release prep

---

## Definition of Done (MVP v0.1.0)

- [ ] All pytest tests pass
- [ ] `ruff check src tests` clean
- [ ] `luminary-memory --help` CLI runs
- [ ] Recall works with all 4 strategies
- [ ] Public Apache-2.0 repo + README + Hermes skill

---

## Release & Publishing Checklist (post-MVP)

- [ ] Tag `v0.1.0` + GitHub release
- [ ] PyPI publish (optional)
- [ ] Social announcement copy (product-first)
- [ ] Screenshot demo: add + recall in terminal
- [ ] README badges: license, CI, PyPI, Python versions

---

*Full implementation detail (code, TDD steps, verification) in [PLAN.md](./PLAN.md).*
