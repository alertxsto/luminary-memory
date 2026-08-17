# PLAN v0.2.4 — Coverage 90% + Health Score

**Version:** 0.2.4 · **Milestone:** Quality hardening + health introspection
**Goal:** Raise test coverage from 82% → ≥90% (roadmap DoD) and ship
`MemoryClient.health_score()` for store quality monitoring.

---

## Phase 1 — Coverage: test the untested (T1–T5)

Targets identified by `pytest --cov --cov-report=term-missing`:

| Module | Current | Target | Missing lines to cover |
|--------|---------|--------|------------------------|
| `hermes/config_schema.py` | 11% | ≥90% | Standalone fallback shim (no hermes runtime) |
| `ingest/llm.py` | 68% | ≥90% | `review_memories`, `_call_llm` error/empty paths, enrich failures |
| `api.py` | 75% | ≥90% | `run_maintenance` actions, `delete`/`update` edges, error handling |
| `hermes/provider.py` | 81% | ≥90% | maintenance trigger, shutdown, prefetch guards, error paths |

### T1 — config_schema standalone coverage
- Test: import `config_schema.py` **without** hermes-agent runtime (simulate CI)
- Assert `CONFIG_SCHEMA` shim exposes `name`, `label`, `storage`, 18 fields
- Assert `auto_maintain` and `ingest_llm` fields present

### T2 — llm.py enricher paths
- Test `OpenAICompatibleEnricher.review_memories` with mocked `_call_llm`
  - returns valid actions JSON → parsed
  - returns `{}` → `{"skipped": ...}` handled by caller
  - raises (network) → returns `{}` (best-effort, no crash)
- Test `_call_llm` with mocked `urlopen`:
  - 200 with choices → content returned
  - 200 empty choices → `""`
  - HTTPError → propagates to caller fallback
- Test `enrich()` fallback when `base_url` empty → `EnrichedContent(content=text)`

### T3 — api.py maintenance + CRUD edges
- Test `run_maintenance`:
  - no enricher → `{"skipped": ...}`
  - empty store → `{"reviewed": 0, ...}`
  - enricher returns delete/update/keep actions → applied correctly
  - enricher returns malformed actions (not a list) → `{"error": "bad LLM response"}`
  - enricher returns action for unknown id → skipped
- Test `update()` with changed content → `updated_at` bumped, embedding recomputed
- Test `delete()` on non-existent id → graceful (no raise)

### T4 — provider.py lifecycle paths
- Test `on_session_end` with `auto_maintain=true` + `ingest_llm=true` → `run_maintenance` called, logged
- Test `on_session_end` with maintenance raising → exception logged, not propagated
- Test `shutdown` writer-thread close (regression: no SQLite thread-affinity crash)
- Test prefetch guards: `auto_recall=false`, `mode=tools`, shutdown flag → no prefetch

### T5 — coverage gate
- Add `--cov-fail-under=90` to CI workflow + `Makefile`/`pyproject` pytest config
- Verify `pytest -q --cov=luminary_memory` ≥ 90% locally

---

## Phase 2 — Health score (T6–T8)

### T6 — `health_score()` API in `api.py`

```python
def health_score(self) -> dict:
    """Store health report: overall 0-100 + per-dimension breakdown."""
```

Dimensions (computed from existing store data — no new schema):

| Dimension | Weight | Signal |
|-----------|--------|--------|
| `duplicate_rate` | 25% | % memories with a near-dupe (Jaccard > 0.85) — lower better |
| `staleness` | 25% | % memories not accessed in 30d (decayed) — lower better |
| `importance` | 20% | % memories above `prune_min_importance` — higher better |
| `density` | 15% | memories with graph relations / total — higher better |
| `size` | 15% | store size vs `token_budget` scale (0 = empty, 100 = healthy volume) |

Score = weighted sum. Returns:

```python
{
  "score": 87.5,
  "dimensions": {
    "duplicate_rate": {"value": 0.02, "weight": 0.25, "health": 98.0},
    "staleness": {...}, "importance": {...}, "density": {...}, "size": {...}
  },
  "recommendations": ["2 stale memories older than 30d — run lifecycle prune"]
}
```

`recommendations` — generated from low-scoring dimensions (≤70):
- duplicates → "run lifecycle consolidate"
- stale → "run lifecycle prune or LLM maintenance"
- low importance → "raise prune_min_importance or review store"

### T7 — CLI `health` subcommand

```bash
luminary-memory health --json
luminary-memory health
# 📊 Memory Health: 87.5/100
#   • Duplicates: 2.0% ✅
#   • Stale (>30d): 4.0% ✅
#   • Importance: 92% ✅
#   • Graph density: 33% ⚠️
#   • Size: 60% ✅
#   → 2 stale memories — run `luminary-memory lifecycle`
```

### T8 — health score tests + docs

- Test: empty store → score 0? or 100? (decide: empty store = 100 "nothing wrong" — document)
- Test: all duplicates → low duplicate_rate dimension
- Test: all stale → low staleness dimension
- Test: healthy mixed store → score ≥ 80
- Test CLI `health` output shape (`--json` parseable)
- Docs: `docs/lifecycle.md` + README (health section), CHANGELOG entry

---

## Definition of Done (v0.2.4)

- [ ] `pytest -q` green (≥90% coverage, CI gate)
- [ ] `ruff check src tests` clean
- [ ] CLI smoke: `luminary-memory health` + `--json`
- [ ] Health score verified against real store (`~/.hermes/luminary/memory.db`)
- [ ] CHANGELOG 0.2.4 entry
- [ ] Version bumped to 0.2.4
- [ ] Tag + GitHub release + PyPI upload (auto-publish)
