# Luminary Memory — Roadmap

> A lightweight, self-hosted memory layer for AI agents.

**Status:** v0.1.0 released · **Test:** 97 passed · **Coverage:** 91% · **Next:** v0.2.0

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
| 9 | Audit & Hardening (2026-08-17) | ✅ Done |

---

## Phase 9 — Audit & Hardening (Done)

Sumber: `analisa.md` (audit menyeluruh dari backend agent). Semua fix verified.

- [x] 🔴 Fix: enricher crash saat `ingest_llm=True` (api.py)
- [x] 🟠 Fix: `_parse_dt` crash di lifecycle (temporal.py)
- [x] 🟡 Fix: FTS5 SQL injection path (sqlite.py — sanitize query)
- [x] 🟡 Fix: `list()` O(N log N) → SQL-level pagination (`recent()`)
- [x] 🟡 Fix: CLI global error handler + limit validation
- [x] 🟡 Fix: whitelist regex crash (skip invalid pattern)
- [x] 🟡 Fix: pg_integration_smoke test kosong → round-trip beneran
- [x] 🟢 Fix: pgvector coverage 51% → **82%** (get/update/delete/count/row parsing)
- [x] ✅ CI: ruff check sudah ada (false positive di audit)
- [x] ✅ Prune sort key: sudah bener (by design)
- [x] ✅ Git history: dibersihkan dari file pribadi (`.commandcode/`, `SOCIAL.md`)
- [x] ✅ .gitignore: komprehensif (env, secrets, screenshots, internal docs)

---

## Definition of Done (v0.1.0) ✅

- [x] All pytest tests pass (97 passed, 1 skipped)
- [x] `ruff check src tests` clean
- [x] `luminary-memory --help` CLI runs
- [x] Recall works with all 4 strategies
- [x] Public Apache-2.0 repo + README + Hermes skill
- [x] Tag `v0.1.0` + GitHub release + PyPI publish

---

## v0.2.0 — Roadmap (Next)

### Polish & Quality
- [ ] HNSW index untuk pgvector (TODO di backend, scale >100k)
- [ ] Naikkan pgvector coverage ke 90%+ (test vector_search paths)
- [ ] Benchmark suite: recall quality vs latency (real data)
- [ ] CLI `search`/`list` output JSON (parity dengan `recall --json`)
- [ ] README badges (CI, PyPI version, license)

### Fitur Baru (kandidat)
- [ ] LLM enricher implementasi nyata (provider-agnostic, bukan NotImplementedError)
- [ ] `update()` bump `updated_at` otomatis
- [ ] Export/import memory (backup & restore)
- [ ] Tags filter di `recall()` (scope query per tag)
- [ ] `--limit 0` = no limit semantics (bukan error)

### Integrasi & Deploy
- [ ] GitHub Pages deploy (enable repo settings → /website)
- [ ] `hermes/SKILL.md` → publish sebagai standalone skill
- [ ] PyPI auto-publish workflow (tag → build → upload)

---

## Post-MVP Ideas (v0.3.0+)

- [ ] Knowledge graph visualisasi (entity relations)
- [ ] Memory health score (dupe rate, staleness, importance distribution)
- [ ] Multi-user scoping (user_id per memory)
- [ ] Async API (`async def`) untuk agent loop
- [ ] Web dashboard (browse/query memories via UI)

---

*Full implementation detail (code, TDD steps, verification) in [PLAN.md](./PLAN.md).*
