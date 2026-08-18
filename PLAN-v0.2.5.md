# PLAN v0.2.5 — Semantic Consolidation + Auto Importance

**Version:** 0.2.5 · **Milestone:** Smarter self-maintenance (roadmap v0.3.0 items #4 + #5)
**Goal:** Replace token-overlap consolidation with semantic (embedding) merging, and auto-estimate memory importance so pruning and health scores reflect real value.

---

## Background (verified from code)

- `lifecycle/consolidate.py` uses **Jaccard token overlap only** (`recall/dedup.py:jaccard_similarity`). Two memories with the same meaning but different wording ("deploy target is staging" vs "deploy target is production cluster") are **not** merged → semantic duplicates accumulate.
- `lifecycle/prune.py` uses **static `m.importance`** (default `0.2`), never estimated from behavior → pruning is blunt.
- `MemoryClient` has `self.engine.embed()` (fastembed) available — can compute embeddings for consolidation without new deps.
- `types.py:Memory` has `importance`, `access_count`, `created_at`, `last_accessed_at`, `metadata`.

---

## Phase 1 — Semantic Consolidation (T1–T4)

### T1 — cosine helper in `recall/dedup.py`

Add `cosine_similarity(a: list[float], b: list[float]) -> float` (pure math, no deps). Reuse in consolidation; keep `jaccard_similarity` for dedup.

- Test: identical vectors → 1.0; orthogonal → 0.0; empty → 0.0; negative → clamped.

### T2 — semantic merge in `lifecycle/consolidate.py`

Extend `consolidate(backend, threshold=0.9, semantic=True)`:

- `semantic=True` (default): cluster by `cosine_similarity(embedding_a, embedding_b) >= semantic_threshold` (default 0.85), **falling back to Jaccard** when embeddings are missing (legacy rows, pgvector without vectors).
- `semantic=False`: current Jaccard behavior (back-compat).
- Keep existing merge logic (longest content as master, sum access, union tags).

- Tests: two memories same meaning different words → merged (embedding similarity high); two unrelated → kept; missing embeddings → falls back to Jaccard; `semantic=False` → Jaccard only.

### T3 — CLI flag

`luminary-memory lifecycle --semantic/--no-semantic` (default semantic on). Wire through `run_lifecycle()` → `consolidate(semantic=...)`.

- Test: CLI flag parse + passes through.

### T4 — runner integration

`lifecycle/runner.py:run_lifecycle()` passes `semantic` from settings (`LUMINARY_CONSOLIDATE_SEMANTIC`, default `true`). New env var documented.

- Test: runner respects env var.

---

## Phase 2 — Auto Importance Estimation (T5–T8)

### T5 — estimator module `lifecycle/importance.py`

```python
def estimate_importance(
    memory, now=None,
    half_life_hours: float = 24.0,       # recency decay
    access_weight: float = 0.4,
    recency_weight: float = 0.3,
    centrality_weight: float = 0.3,
) -> float:
```

`importance = access_norm * access_weight + recency_norm * recency_weight + centrality_norm * centrality_weight`

- `access_norm` — `log1p(access_count) / log1p(max_access_in_store)`.
- `recency_norm` — `exp(-age_hours / half_life_hours)` (same decay shape as temporal recall).
- `centrality_norm` — graph degree / max degree (relations count; 0 when no graph table).
- Clamp 0.0–1.0.

- Tests: new memory → low importance; accessed many times → high; recent → high; old+never-accessed → low; clamp bounds.

### T6 — call estimator on ingest + lifecycle

- `api.py:ingest()` — after insert, if importance not explicitly set, `estimate_importance(memory)` and persist (needs backend update — cheap, one row).
- `run_lifecycle()` — re-estimate all importances before prune so pruning reflects current value.
- Guard: only when `LUMINARY_IMPORTANCE_AUTO` (default `true`).

- Tests: ingest sets importance > 0; lifecycle re-estimates (old memory importance drops); disabled flag keeps static.

### T7 — prune uses estimated importance (already does, but now fed live values)

No structural change — prune already reads `m.importance`. Add test proving a low-importance memory gets pruned after re-estimation.

### T8 — health score uses importance dimension (already reads it)

`health_score()` `importance` dimension already uses `m.importance >= prune_min`. With auto-estimation the dimension becomes meaningful. Add test: fresh store → importance high → score contribution healthy.

---

## Phase 3 — Docs + Release (T9–T10)

### T9 — Documentation sweep (REQUIRED before release — user rule)

- `docs/lifecycle.md` — semantic consolidation section + importance auto-estimation + new env vars.
- `docs/recall.md` — note cosine in consolidation (dedup still Jaccard).
- `docs/architecture.md` — update lifecycle pipeline (importance estimation step).
- `docs/cli.md` — `lifecycle --semantic/--no-semantic`.
- `README.md` — badges if tests/coverage change; roadmap line v0.2.5.
- `CHANGELOG.md` — 0.2.5 entry.
- `ROADMAP.md` — header v0.2.5, tick items #4 (importance) + #5 (consolidation v2).
- Website badge → v0.2.5.
- Grep for stale versions across all docs before release.

### T10 — Release v0.2.5

- Bump `pyproject.toml` + `__init__.py` → 0.2.5.
- `pytest -q` green, `ruff check` clean, coverage ≥ 90% (DoD).
- Tag `v0.2.5` → push → GitHub release (Trusted Publisher auto-publishes PyPI).
- Verify PyPI version + website redeploy.

---

## Definition of Done

- [ ] Consolidation merges semantic near-duplicates (verified with same-meaning-different-words test)
- [ ] Importance auto-estimated on ingest + lifecycle (verified with behavior tests)
- [ ] Coverage ≥ 90%, ruff clean, all tests green
- [ ] CLI `--semantic/--no-semantic` works
- [ ] Docs sweep complete & versions consistent (user rule)
- [ ] v0.2.5 released via Trusted Publisher (no twine)
