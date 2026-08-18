# PLAN — Multi-User Scoping

**Target:** v0.3.0 (multi-user = roadmap item terakhir)

> Status: **Phase A active** · Phases B (dashboard explore) and C (website polish)
> shipped in v0.2.8.

---

## Phase A — Multi-User Scoping (`user_id` per memory)

### A1 — Schema migration (`schema.py` + backends)

- Add `user_id TEXT` column to `memories` (SQLite + pgvector).
- `init_schema` — `ALTER TABLE ... ADD COLUMN IF NOT EXISTS user_id TEXT` (idempotent; existing stores upgrade cleanly).
- Backends: `add`/`update` persist `user_id`; `_row_to_memory` reads it.

### A2 — `MemoryClient` API (`api.py`)

- `ingest(..., user_id: str | None = None)` — store user_id.
- `recall(query, ..., user_id: str | None = None)` — filter results by user_id when set.
- `graph(user_id=...)`, `list(user_id=...)`, `by_tags(tags, user_id=...)` — scoped variants.
- `count(user_id=...)`.
- Default `user_id=None` = shared/global (back-compat — existing stores behave identically).

### A3 — Recall filtering (`recall/` + `api.py`)

- After fusion/dedup, filter `scored` by `user_id` (post-filter is fine at this scale; optimize with SQL WHERE later if needed).
- Tag-scoped recall combines `tags` + `user_id`.

### A4 — Lifecycle & health scoping

- `run_lifecycle(user_id=...)`, `health_score(user_id=...)` — optional scope; None = whole store.

### A5 — Tests

- ingest with user_id → recall with same user_id returns it; different user_id doesn't.
- recall without user_id (global) sees everything (back-compat).
- Existing stores (no user_id) work unchanged.
- pgvector column migration test (if Postgres available).

---

## Phase B — Dashboard Settings Explore (v0.2.6 polish, live)

### B1 — Verify all 20 fields appear in dashboard

- `hermes memory status` + dashboard UI (9119) — confirm `consolidate_semantic`, `importance_auto`, `llm_*` all render and save.
- Fix any field that fails to save/load.

### B2 — Config round-trip test

- Change a setting via dashboard (e.g. `recall_limit` 10→5), verify it persists to `~/.hermes/luminary/config.json` and provider picks it up after restart.

### B3 — Docs

- `docs/hermes-integration.md` — table already documents 20 fields; verify matches schema exactly.

---

## Phase C — Website/Landing Polish

### C1 — Audit current site

- `website/index.html` (585 lines) — review hero, use-cases, features, FAQ.
- Screenshot + vision review (moonlit editorial style — user's approved aesthetic).

### C2 — Polish targets

- **Graph section** — showcase `luminary-memory graph` (new CLI feature) with an example output block.
- **Multi-user** — add to features list (after Phase A ships).
- **Version badge** — stays consistent (bump-version.sh handles).
- **Performance numbers** — 230ms recall @5k, 0 LLM tokens (already in README; ensure site matches).
- Any stale copy / broken links.

### C3 — Verify

- Playwright full-page screenshot + vision_analyze before ACC (user's rule: review visual via screenshot).
- Auto-deploy on push (Pages).

---

## Release plan

- **v0.3.0** (after Phase A) — multi-user scoping. Bump via `bump-version.sh`, docs sweep, tag, GitHub release first, Trusted Publisher.
- Phases B & C can ship in v0.2.8 (before v0.3.0) since they're independent.

## Definition of Done

- [ ] `user_id` column exists (SQLite + pgvector), existing stores migrate cleanly
- [ ] ingest/recall/graph/list/count accept `user_id`; global default back-compat
- [ ] Tests green, coverage ≥ 90%, ruff clean
- [ ] Dashboard 20 fields verified live (save/load round-trip)
- [ ] Website polished (graph showcase + consistent version), screenshot-verified
- [ ] Docs sweep complete; single consistent version
- [ ] Release: v0.2.8 (B+C) then v0.3.0 (A)
