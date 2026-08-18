# PLAN v0.2.7 — Graph CLI + Version Command

**Version:** 0.2.7 · **Milestone:** Graph visibility (roadmap v0.3.0 item #1, CLI phase)
**Goal:** Surface the knowledge graph (entities + relations) through the CLI, and add a `version` command. Both are small, data already exists in the store.

---

## Background (verified from code)

- `schema.py` already has `entities` + `relations` tables (with indexes).
- `recall/graph.py` has `extract_entities()` but no public graph *read* API.
- CLI has 9 commands; no graph/version command.
- `MemoryClient` has `self.backend` — SQLite exposes `conn` for direct queries.

---

## T1 — `MemoryClient.graph()` API (`api.py`)

```python
def graph(self, limit: int = 20) -> dict:
    """Return the knowledge graph: top entities and their co-occurrence edges."""
```

Shape:
```json
{
  "entities": [{"name": "deploy", "degree": 4, "memories": 3}, ...],
  "relations": [{"source": "deploy", "target": "production", "weight": 2.0}, ...]
}
```

- Query `entities` + `relations` via backend `conn` (SQLite path; pgvector path via `_exec`-style helper or graceful fallback `{"entities": [], "relations": []}`).
- Sort entities by degree desc, cap at `limit`.
- Test: ingest 2 memories with shared entities → graph returns entities + edge; empty store → empty dict.

## T2 — `luminary-memory graph` CLI (`cli.py`)

```bash
luminary-memory graph                 # table: entity | degree | memories
luminary-memory graph --json          # raw JSON
```

- Human mode: `rich` table of top entities; optional `--relations` flag to also print edges.
- `--limit N` (default 20).
- Test: CLI smoke on seeded store (table + JSON output).

## T3 — `luminary-memory version` CLI

```bash
luminary-memory version     # luminary-memory 0.2.7 (Python 3.11)
```

- Print `__version__` + Python version.
- Test: exit 0, contains "0.2.7".

## T4 — Docs sweep (REQUIRED before release — user rule)

- `docs/cli.md` — add `graph` + `version` commands.
- `README.md` — CLI section mention (if present).
- `CHANGELOG.md` — 0.2.7 entry.
- `ROADMAP.md` — tick graph visualization (CLI phase), header v0.2.7.
- Website badge → v0.2.7 (via `scripts/bump-version.sh`).
- Grep stale versions (bump-version.sh does this).

## T5 — Release v0.2.7

1. `./scripts/bump-version.sh 0.2.7` (first real use — proves the tool).
2. `pytest -q` green, `ruff check src tests` clean, coverage ≥ 90%.
3. Commit + push, `git tag v0.2.7`, push tag.
4. `gh release create v0.2.7` FIRST (so the publish workflow's skill-asset step finds the release — the 403 fix), then Trusted Publisher auto-publishes PyPI.
5. Verify PyPI 0.2.7 + website redeploy.

## T6 — Import to Hermes provider (live)

After release:
1. `pip install -qe ".[hermes]"` (or `pip install "luminary-memory[hermes]>=0.2.7"`) in the Hermes venv — brings the new provider code + 20-field config schema.
2. Verify provider loads: `hermes memory status` → provider `luminary` available.
3. Restart gateway: `bash ~/.hermes/scripts/restart-bots.sh`.
4. Verify `~/.hermes/luminary/` store intact (no data loss on upgrade) + dashboard shows the new settings (`consolidate_semantic`, `importance_auto`).

---

## Definition of Done

- [ ] `MemoryClient.graph()` returns entities + relations (empty-store safe)
- [ ] `luminary-memory graph` (table + `--json`) and `version` work
- [ ] Coverage ≥ 90%, ruff clean, all tests green
- [ ] Docs sweep complete; single consistent version 0.2.7 everywhere
- [ ] v0.2.7 released; publish workflow skill-asset step passes (403 fix verified)
- [ ] Hermes provider upgraded to 0.2.7, gateway restarted, store intact
