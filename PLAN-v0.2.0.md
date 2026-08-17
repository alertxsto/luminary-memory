# Luminary Memory — v0.2.0 Implementation Plan

> **Release:** v0.2.0 "Quality & Scale" · **Base:** v0.1.1 (97 tests, 91% coverage) · **License:** Apache-2.0
>
> This plan is the authoritative implementation guide for the v0.2.0 roadmap. It is derived from
> `ROADMAP.md` (v0.2.0 section) and supersedes the MVP sections of `PLAN.md` for this release.

---

## 1. Goal

Production hardening. v0.1.1 proved the core pipeline (four-strategy recall, RRF fusion, Jaccard
dedup, token budget, lifecycle) works at small scale. v0.2.0 makes the product credible at scale and
production-grade in four dimensions:

1. **Performance & Scale** — pgvector HNSW indexing, a measurable benchmark suite, a query planner
   that avoids wasted work, and a batch ingest path.
2. **Recall & Ingest** — a real provider-agnostic LLM enricher (replacing the `NotImplementedError`
   stub), tag-scoped recall, `updated_at` auto-bump, and result highlights.
3. **API & CLI** — JSON output parity across commands, export/import, correct `--limit 0`
   semantics, and API documentation generated from docstrings.
4. **Integrations** — GitHub Pages deployment, a standalone-installable Hermes skill, and an
   automated PyPI publish pipeline.

The product principle throughout: **private by default, lightweight by construction, budget-aware,
self-maintaining, pluggable.** Every task must preserve the zero-hard-dependency default (SQLite +
FTS5 + local ONNX embeddings) and degrade gracefully when optional components are absent.

---

## 2. Architecture Notes

These notes constrain how the tasks below are implemented. They reflect the current codebase as
verified at planning time (paths under `src/luminary_memory/`).

### 2.1 Current shape

```
src/luminary_memory/
├── __init__.py            # exports MemoryClient, __version__
├── api.py                 # MemoryClient — public API surface
├── cli.py                 # typer CLI (add/recall/search/list/lifecycle/stats)
├── config.py              # Settings dataclass + LUMINARY_* env loader
├── schema.py              # SQLite DDL (FTS5 + triggers + entities/relations)
├── types.py               # Memory, ScoredMemory, RecallResult
├── budget.py              # token-budget truncation
├── backends/              # base.py ABC · sqlite.py · pgvector.py · factory
├── embeddings/            # fastembed.py (EmbeddingEngine wrapper)
├── ingest/                # whitelist.py · llm.py (LLMEnricher stub)
├── recall/                # semantic/keyword/temporal/graph + fusion.py + dedup.py
└── lifecycle/             # cleanup/consolidate/prune/runner
```

### 2.2 Key design decisions

- **Backend abstraction is the seam.** `MemoryBackend` (ABC) is the only place database dialects
  meet. HNSW indexing and batch insert both land behind this interface; SQLite and pgvector each
  implement the same method signatures, so `MemoryClient` never branches on backend type.
- **Enrichment is already wired as a strategy.** `MemoryClient.ingest()` calls
  `self.enricher.enrich(text)` unconditionally and falls back to `NoopEnricher` when none is
  supplied. The v0.2.0 enricher must therefore be a *drop-in* `LLMEnricher` subclass — the ingest
  path does not change, only the enricher's internals do.
- **Recall isolates per-strategy failure.** `api.py` already wraps each strategy in try/except and
  appends `[]` on failure. The query planner must preserve this isolation: a skipped strategy is
  the same as a failed one (contributes no ranked list), never an exception.
- **`update()` is the correct home for `updated_at`.** Recall bumps `access_count` and
  `last_accessed_at` via `backend.update()` internally; that path must *not* bump `updated_at`
  (access is not a semantic edit). Only the public `MemoryClient.update()` should touch
  `updated_at`.
- **`--limit 0` = unlimited.** Current `_clamp_limit` floors at 1. This is inverted: 0 must mean
  "no limit," negative values must still be rejected, and the API's `list(limit=0)` must return
  everything.
- **Zero new hard dependencies.** The enricher uses stdlib HTTP (`urllib.request`). Docs generation
  and benchmark tooling are dev-only optional dependencies. Runtime `dependencies` in
  `pyproject.toml` stay unchanged unless a task explicitly justifies an addition.

### 2.3 Definition of Done (applies to every task)

1. New behavior is covered by a failing-then-passing test (TDD), or a documented verification
   command for infra tasks (CI workflows, docs, deploy).
2. `pytest -q` is green (target: ≥ 91% coverage, no regression).
3. `ruff check src tests` is clean.
4. Commit message follows the existing `feat:` / `fix:` / `chore:` convention.
5. Public API/docstrings stay accurate (docs regenerate where relevant).

---

## 3. Tasks

Tasks are numbered `T1`–`T16`. Each is independent enough to be a single branch + PR; the only
hard ordering constraint is that **T4 (batch ingest) must land before T10 (export/import)**,
because import reuses the batch path. Recommended execution order follows the numbering.

---

### 3.1 Performance & Scale

#### T1 — HNSW index for pgvector

**Objective:** Add an optional HNSW index so vector search stays fast beyond ~100k memories.
Currently `PGVectorBackend._ensure_schema()` creates tables but no index, so `vector_search()` runs
a full `<=>` scan.

**Files:**
- `src/luminary_memory/backends/pgvector.py` — create index, idempotent
- `src/luminary_memory/config.py` — new settings
- `tests/test_backend_pgvector.py` — new unit tests

**New settings (config.py):**
- `pg_hnsw_index: bool` (default `False`, env `LUMINARY_PG_HNSW_INDEX`)
- `pg_hnsw_m: int` (default `16`, env `LUMINARY_PG_HNSW_M`)
- `pg_hnsw_ef_construction: int` (default `64`, env `LUMINARY_PG_HNSW_EF_CONSTRUCTION`)

**TDD steps:**
1. **Failing test** (mock `psycopg.connect`, assert SQL): create backend with `pg_hnsw_index=True`
   and assert an executed SQL statement contains `USING hnsw` and `vector_cosine_ops`; create with
   `False` and assert no `hnsw` statement is issued.
2. **Implement:** add `_ensure_hnsw_index()` called from `__init__` (or a public `build_index()`)
   gated on the setting. SQL form:
   ```sql
   CREATE INDEX IF NOT EXISTS memories_embedding_hnsw
   ON memories USING hnsw (embedding vector_cosine_ops)
   WITH (m = {m}, ef_construction = {ef});
   ```
   Guard against empty tables/extension absence with a try/except that logs and continues (indexing
   must not hard-fail schema creation).
3. **Pass:** both tests green.
4. **Commit:** `feat: optional HNSW index for pgvector backend`

**Verification:**
```bash
pytest tests/test_backend_pgvector.py -q
ruff check src/luminary_memory/backends/pgvector.py src/luminary_memory/config.py
```

**Risks:** pgvector versions < 0.5.0 use different operator-class naming; keep the index statement
behind the feature flag so default installs are unaffected. Real-index verification requires a live
Postgres — covered by the existing opt-in integration smoke test (`LUMINARY_PG_DSN`).

---

#### T2 — Benchmark suite: recall quality vs latency

**Objective:** A reproducible harness that measures, on realistic synthetic data, (a) recall
quality (recall@k, MRR) and (b) per-strategy and end-to-end latency (p50/p95). This becomes the
evidence base for the query planner (T3) and future tuning.

**Files (all new, under `benchmarks/`):**
- `benchmarks/__init__.py`
- `benchmarks/synthetic.py` — deterministic generator of realistic memories (project decisions,
  user preferences, error fixes) with known relevance labels
- `benchmarks/metrics.py` — recall@k, MRR, latency percentiles
- `benchmarks/run_benchmarks.py` — CLI entrypoint (`python -m benchmarks.run_benchmarks`)
- `benchmarks/README.md` — how to run, what the numbers mean

**Design constraints:**
- Deterministic (fixed seed), runs on SQLite by default, pgvector optional via `--backend`.
- Emits a JSON report plus a Markdown summary; never committed results, only the runner.
- Uses a fake/deterministic embedding engine for pure-latency runs and the real `FastembedEngine`
  for quality runs (env-gated to avoid a slow default).

**Verification:**
```bash
python -m benchmarks.run_benchmarks --n 2000 --backend sqlite --report /tmp/bench.json
# assert: exit 0, report JSON parses, contains recall@k, mrr, latency p50/p95 per strategy
```

**Commit:** `feat: recall quality vs latency benchmark suite`

**Risks:** embedding latency dominates small-N runs; the harness must report strategy latency
*separately* from embedding time so the planner's savings are measurable.

---

#### T3 — Query planner: skip strategies when not needed

**Objective:** Avoid running temporal/graph (and, when safe, semantic) strategies on queries that
won't benefit, cutting recall latency without harming quality. The planner decides the active
strategy set per query, then `api.py` runs only those.

**Files:**
- `src/luminary_memory/recall/planner.py` (new) — pure function, easily unit-tested
- `src/luminary_memory/api.py` — wire planner into `recall()`
- `src/luminary_memory/config.py` — `query_planner: bool` (default `True`)
- `tests/test_recall_planner.py` (new)

**Heuristics (v1, conservative — skip only when clearly safe):**
- **Skip graph** when the query yields no entity tokens (empty `_query_entities(query)`), since
  `graph_recall` already returns `[]` in that case.
- **Skip temporal** when a keyword strategy produces a strong match (top BM25 score above a
  threshold), since pure-recency results add noise to an exact-term query.
- **Never skip semantic or keyword** in v1 — they anchor meaning and exact terms respectively.
- **Never skip anything** when the planner is disabled (`query_planner=False`).

**TDD steps:**
1. **Failing test** for `plan_strategies(query, keyword_top_score=None, planner=True)`:
   - query `"deploy target"` (has entities) → all four enabled.
   - query `"!!!"` (no entities) → graph disabled.
   - keyword top score `0.95` → temporal disabled.
   - `planner=False` → all four enabled regardless.
2. **Implement** `plan_strategies()` returning a frozenset of enabled strategy names.
3. **Wire into `api.py`:** replace the fixed four-lambda tuple with a planner-driven list; skipped
   strategies contribute nothing (mirrors the existing failure-isolation behavior).
4. **Pass:** planner tests + existing `test_recall_orchestrator.py` still green (skip must not
   change results for queries that do hit all strategies).
5. **Commit:** `feat: query planner skips low-value strategies`

**Verification:**
```bash
pytest tests/test_recall_planner.py tests/test_recall_orchestrator.py -q
```

**Risks:** over-aggressive skipping degrades recall quality. v1 skips are deliberately
conservative and must be validated against the T2 benchmark before tightening.

---

#### T4 — Batch ingest API

**Objective:** A `ingest_batch()` path that ingests many memories with a single embedding pass
(reuses `FastembedEngine.embed_batch`) and efficient backend writes, for bulk import and T10.

**Files:**
- `src/luminary_memory/backends/base.py` — add abstract `add_many(memories: list[Memory]) -> list[int]`
- `src/luminary_memory/backends/sqlite.py` — `executemany` implementation
- `src/luminary_memory/backends/pgvector.py` — batched insert implementation
- `src/luminary_memory/api.py` — `ingest_batch(texts, tags=None, source=None) -> list[int | None]`
- `tests/test_api.py` (or new `tests/test_batch.py`)

**Semantics:** mirrors `ingest()` exactly per item — whitelist rejection yields `None` at that
index, enrichment applies per item, embeddings computed in one `embed_batch` call.

**TDD steps:**
1. **Failing test:** ingest 3 texts where one is whitelist-rejected; assert returned list is
   `[id, id, None]`, `count() == 2`, and each accepted memory has a non-None embedding.
2. **Implement** `add_many` on both backends + `ingest_batch` on `MemoryClient`.
3. **Pass:** batch tests + existing ingest tests green.
4. **Commit:** `feat: batch ingest API`

**Verification:**
```bash
pytest tests/test_batch.py tests/test_api.py -q
```

---

### 3.2 Recall & Ingest

#### T5 — Real LLM enricher (provider-agnostic)

**Objective:** Replace the `LLMEnricher.enrich()` `NotImplementedError` with a working,
provider-agnostic implementation that calls any OpenAI-compatible chat-completions endpoint and
returns structured enrichment (summary, entities, tags). Must degrade to passthrough on any failure.

**Files:**
- `src/luminary_memory/ingest/llm.py` — implement `OpenAICompatibleEnricher`
- `src/luminary_memory/config.py` — new settings
- `tests/test_enricher.py` (new)

**New settings (config.py):**
- `llm_base_url: str | None` (env `LUMINARY_LLM_BASE_URL`)
- `llm_api_key: str | None` (env `LUMINARY_LLM_API_KEY`)
- `llm_model: str` (default `"gpt-4o-mini"`, env `LUMINARY_LLM_MODEL`)
- `llm_timeout: int` (default `10`, env `LUMINARY_LLM_TIMEOUT`)

**Design:**
- Stdlib `urllib.request` POST to `{base_url}/chat/completions`; no new runtime dependency.
- Prompt instructs the model to return **strict JSON** `{"summary": str, "entities": [...],
  "tags": [...]}`; response parsed defensively (tolerate markdown fences, partial JSON).
- Any exception / timeout / malformed body → return `EnrichedContent(content=text)` (passthrough);
  never let enrichment abort ingest.
- Keep `NoopEnricher` as the default; the enricher is only used when explicitly constructed or
  when `ingest_llm=True` is wired in a follow-up convenience path.

**TDD steps:**
1. **Failing test:** monkeypatch `urllib.request.urlopen` to return a fake JSON response; assert
   `enrich("text")` returns summary/entities/tags correctly.
2. **Failing test:** urlopen raises → `enrich()` returns passthrough with original content.
3. **Implement** `OpenAICompatibleEnricher` and pass both.
4. **Commit:** `feat: provider-agnostic LLM enricher`

**Verification:**
```bash
pytest tests/test_enricher.py -q
```

**Risks:** provider response-format drift. Mitigate with defensive parsing + the passthrough
fallback. No live API call in CI (all mocked).

---

#### T6 — Tag-scoped recall

**Objective:** `recall(query, tags=[...])` restricts the candidate set to memories carrying the
given tags before fusion, so recall can be scoped to a domain (e.g. `tags=["infra"]`).

**Files:**
- `src/luminary_memory/backends/base.py` — optional `by_tags(tags) -> list[Memory]`
- `src/luminary_memory/backends/sqlite.py` — SQL implementation
- `src/luminary_memory/backends/pgvector.py` — SQL implementation
- `src/luminary_memory/api.py` — `recall(..., tags: list[str] | None = None)`
- `tests/test_recall_orchestrator.py` (extend)

**Design:** when `tags` is provided, `recall()` first computes the allowed id set via `by_tags`,
then filters each strategy's ranked list to those ids before fusion. This preserves per-strategy
ranking and only removes out-of-scope memories.

**TDD steps:**
1. **Failing test:** ingest three memories tagged `["a"]`, `["b"]`, `["a","b"]`; `recall(..., tags=["a"])`
   returns only the two carrying `a`.
2. **Implement** `by_tags` on both backends (tag JSON containment / `LIKE` for SQLite JSON, `@>`
   for pgvector JSONB) and wire the filter into `recall()`.
3. **Pass:** new test + existing recall tests.
4. **Commit:** `feat: tag-scoped recall`

**Verification:**
```bash
pytest tests/test_recall_orchestrator.py -q
```

---

#### T7 — `updated_at` auto-bump in `update()`

**Objective:** `MemoryClient.update()` sets `updated_at` to the current UTC time before persisting,
so semantic edits are distinguishable from access bumps (which already update `last_accessed_at`).

**Files:**
- `src/luminary_memory/api.py` — modify `update()`
- `tests/test_api_extended.py` (extend `test_update`)

**TDD steps:**
1. **Failing test:** ingest, sleep briefly or inject a known `updated_at`, call `update()`, assert
   the stored `updated_at` is newer than the pre-update value.
2. **Implement:** in `update()`, set `memory.updated_at = datetime.now(UTC).isoformat()` before
   `self.backend.update(memory)`.
3. **Pass.** Confirm recall's internal access-bump still does *not* change `updated_at`.
4. **Commit:** `fix: auto-bump updated_at on update()`

**Verification:**
```bash
pytest tests/test_api_extended.py -q
```

---

#### T8 — Result highlights/snippets

**Objective:** Each recalled memory carries a `snippet` — the matched fragment for keyword hits, or
a leading-context excerpt for semantic/temporal/graph hits — so consumers can show *why* a memory
matched without reading the full content.

**Files:**
- `src/luminary_memory/types.py` — add `snippet: str | None = None` to `Memory`
- `src/luminary_memory/recall/snippets.py` (new) — `extract_snippet(content, query, width=...)`
- `src/luminary_memory/api.py` — attach snippets to recalled memories
- `tests/test_snippets.py` (new)

**Design:** case-insensitive term-window extraction: find the first query term in content, return a
`width`-character window centered on it with ellipses; fall back to a plain leading excerpt when no
term matches.

**TDD steps:**
1. **Failing test:** `extract_snippet("the database uses postgresql fts5", "postgresql", width=30)`
   contains `"postgresql"` and is shorter than the full content.
2. **Implement** `extract_snippet` + attach in `recall()` (do not persist; compute at recall time).
3. **Pass.**
4. **Commit:** `feat: result snippets/highlights`

**Verification:**
```bash
pytest tests/test_snippets.py -q
```

---

### 3.3 API & CLI

#### T9 — JSON output for `search` and `list`

**Objective:** Parity with `recall --json`: add `--json` to `search` and `list` emitting stable,
parseable JSON.

**Files:**
- `src/luminary_memory/cli.py`
- `tests/test_cli.py` (extend)

**TDD steps:**
1. **Failing test:** `list --json` returns exit 0 and `json.loads(output)` yields a list of dicts
   with `id`/`content`/`tags`; `search "x" --json` likewise yields a list with `score`.
2. **Implement:** add `json_out: bool = typer.Option(False, "--json", ...)` to both commands and
   serialize via the same shape as `recall --json` (list of objects, no rich table).
3. **Pass.**
4. **Commit:** `feat: JSON output for search and list`

**Verification:**
```bash
pytest tests/test_cli.py -q
```

---

#### T10 — Export / import memories

**Objective:** Backup & restore: `export` writes all memories to a versioned JSON file; `import`
reads it back (reusing T4 batch ingest), enabling migration and disaster recovery.

**Files:**
- `src/luminary_memory/export.py` (new) — `export_memories(backend, path)`, `import_memories(...)`
- `src/luminary_memory/api.py` — thin wrappers
- `src/luminary_memory/cli.py` — `export` and `import` commands
- `tests/test_export.py` (new)

**Format:** `{"format": "luminary-memory-export", "version": 1, "memories": [...]}` with each
memory's content/tags/metadata/source/importance/ttl/timestamps. Embeddings are optional on export
(`--include-embeddings`) and recomputed on import when absent.

**TDD steps:**
1. **Failing test:** ingest 3 memories → export to tmp file → new empty store → import → `count()==3`,
   contents and tags round-trip exactly.
2. **Implement** export/import + CLI commands.
3. **Pass.**
4. **Commit:** `feat: export and import memories`

**Verification:**
```bash
pytest tests/test_export.py -q
luminary-memory export --path /tmp/backup.json && luminary-memory import --path /tmp/backup.json
```

---

#### T11 — `--limit 0` semantics (unlimited)

**Objective:** `--limit 0` means "return all", not "clamp to 1" and not "empty list." Negative
limits remain rejected.

**Files:**
- `src/luminary_memory/cli.py` — fix `_clamp_limit`
- `src/luminary_memory/api.py` — fix `list(limit=0)` (currently `max(0, limit)` truncates to empty)
- `tests/test_cli.py`, `tests/test_api_extended.py`

**TDD steps:**
1. **Failing test:** `list --limit 0` returns all rows; `recall --limit 0` returns results (not
   clamped to 1); `list --limit -1` still errors.
2. **Implement:** `_clamp_limit` returns `limit if limit > 0 else None` (None = no LIMIT); API
   `list()` treats `limit=0` as unlimited and backend `recent()` handles `None`.
3. **Pass.**
4. **Commit:** `fix: --limit 0 means unlimited`

**Verification:**
```bash
pytest tests/test_cli.py tests/test_api_extended.py -q
```

---

#### T12 — API docs generated from docstrings

**Objective:** Replace the hand-written `docs/api.md` with a generated reference from docstrings,
so the public API docs can never drift from the code.

**Files:**
- `pyproject.toml` — add `pdoc` to `dev` optional deps
- `docs/api.md` — regenerate (or redirect to a generated artifact)
- `docs/README.md` or a `Makefile`/script — document the build command

**Design:** `pdoc` (zero-config, no mkdocs dependency) generating `docs/api` HTML + a Markdown
dump. CI optionally checks freshness.

**Verification:**
```bash
pdoc --output-dir docs/api --docformat markdown src/luminary_memory
# assert: exit 0, docs/api/index.html non-empty, MemoryClient methods listed
```

**Commit:** `docs: generate API reference from docstrings`

---

### 3.4 Integrations

#### T13 — GitHub Pages deployment for the website

**Objective:** Publish `website/` to GitHub Pages automatically on merge to `main`.

**Files:**
- `.github/workflows/pages.yml` (new)

**Design:** standard Pages flow — `actions/configure-pages` → `actions/upload-pages-artifact`
(`path: website`) → `actions/deploy-pages`. Requires enabling Pages (source: GitHub Actions) in
repo settings once (documented manual step).

**Verification:**
```bash
# After enabling Pages + pushing to main:
# assert: https://alertxsto.github.io/luminary-memory/ serves website/index.html (HTTP 200)
curl -s -o /dev/null -w "%{http_code}" https://alertxsto.github.io/luminary-memory/
```

**Commit:** `ci: deploy website to GitHub Pages`

**Risks:** Pages must be enabled in repo settings before the workflow deploys; note this in the
workflow comment.

---

#### T14 — Publish Hermes skill as standalone installable

**Objective:** Package `hermes/SKILL.md` so it installs independently of the Python package (a
Hermes user shouldn't need the whole repo to add the skill).

**Files:**
- `hermes/SKILL.md` — already exists (verify frontmatter is complete/valid)
- `hermes/README.md` (new) — install instructions (`cp SKILL.md ~/.hermes/skills/…` or
  `hermes skill install`)
- `.github/workflows/release.yml` or the publish workflow — attach `hermes/SKILL.md` (and a zipped
  skill dir) as a release asset on tag

**Design:** keep the skill self-contained (frontmatter + usage). The release workflow attaches
`luminary-memory-skill.zip` as an asset so the skill is installable without cloning.

**Verification:**
```bash
# assert SKILL.md frontmatter parses (name/description/version/author/license present)
# assert release asset exists on the next tag
```

**Commit:** `feat: standalone-installable Hermes skill`

---

#### T15 — PyPI auto-publish workflow

**Objective:** Pushing a `v*` tag builds sdist + wheel and publishes to PyPI with no manual steps.

**Files:**
- `.github/workflows/publish.yml` (new)

**Design:** trigger on `push: tags: ['v*']` → `actions/checkout` → `actions/setup-python` →
`python -m build` → `pypa/gh-action-pypi-publish` using **trusted publishing (OIDC)**. One-time
manual prerequisite: configure the PyPI project as a trusted publisher for this repo (documented in
the workflow comment). Add `build` to dev deps.

**Verification:**
```bash
# After trusted publisher is configured:
git tag v0.2.0 && git push origin v0.2.0
# assert: PyPI shows luminary-memory 0.2.0 published; workflow run green
```

**Commit:** `ci: automated PyPI publish on tag`

**Risks:** trusted publishing must be enabled on PyPI first; without it the workflow fails at
upload. Keep the old manual path (`python -m build && twine upload`) documented as fallback.

---

#### T16 — README badges

**Status: ✅ already complete** (verified in `README.md` at planning time: PyPI version, Python
versions, license, CI, test count, coverage, stars).

No work required. Confirm nothing regresses when `test count` / `coverage` change in v0.2.0
(update the static `tests-97 passing` and `coverage-91%` badge URLs/text to the new numbers as part
of the release commit).

---

## 4. Verification Matrix (release gate)

Run all before tagging v0.2.0:

```bash
# Unit + integration suite (SQLite; pgvector integration opt-in via LUMINARY_PG_DSN)
pytest -q

# Coverage gate
coverage run -m pytest && coverage report   # ≥ 91% total

# Lint
ruff check src tests

# CLI smoke
luminary-memory --help
luminary-memory add "deploy target is staging" --tags deploy
luminary-memory recall "where do we deploy" --json
luminary-memory search "staging" --json
luminary-memory list --json --limit 0
luminary-memory export --path /tmp/lm-backup.json && luminary-memory import --path /tmp/lm-backup.json
luminary-memory lifecycle && luminary-memory stats

# Benchmark (informational)
python -m benchmarks.run_benchmarks --n 2000 --backend sqlite

# Docs
pdoc --output-dir docs/api src/luminary_memory

# Build artifacts
python -m build
```

Release checklist (mirrors ROADMAP.md Definition of Done):
- [ ] `pytest -q` green, coverage ≥ 91%
- [ ] `ruff check src tests` clean
- [ ] CHANGELOG updated
- [ ] Version bumped to `0.2.0` in `pyproject.toml` and `src/luminary_memory/__init__.py`
- [ ] README badges updated (test count / coverage numbers)
- [ ] Tag `v0.2.0` + GitHub release + PyPI publish (T15)
- [ ] GitHub Pages updated (T13)

---

## 5. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| HNSW index breaks on older pgvector | Feature-flagged off by default; try/except so indexing never hard-fails schema creation |
| Over-aggressive query planner degrades recall | v1 skips conservative (graph on no-entities, temporal on strong keyword); validate against T2 benchmark before tightening |
| LLM enricher response drift / provider variance | Defensive JSON parsing + passthrough fallback on any failure; fully mocked in CI |
| `--limit 0` semantics conflict with existing `list()` truncation | Change both CLI and API in the same task; explicit negative-limit rejection test |
| Batch ingest divergence from single-ingest semantics | `ingest_batch` reuses whitelist/enrich/embed per item; one shared code path where possible |
| Export/import embedding drift | Embeddings optional on export, recomputed on import; versioned format field |
| Pages / PyPI workflows fail on missing one-time config | Document the manual prerequisite (enable Pages; PyPI trusted publisher) inside each workflow |
| Coverage regression from new modules | Every new module ships with its own test file; release gate enforces ≥ 91% |

---

## 6. Suggested Execution Order

1. **T7** (small, isolates `updated_at` semantics) → **T11** (small, unblocks CLI/API consistency)
2. **T4** (batch) → **T10** (export/import, depends on T4)
3. **T5** (enricher) → **T8** (snippets) → **T6** (tag-scoped recall)
4. **T9** (CLI JSON) → **T3** (planner, after benchmark) 
5. **T1** (HNSW) → **T2** (benchmark — validates planner decisions)
6. **T12** (docs) → **T13/T14/T15** (integrations) → **T16** (release badge refresh)
7. Final: version bump, CHANGELOG, release.

Each numbered item is an independent branch + PR except the T4→T10 dependency. TDD on every code
task; infra tasks verified via the documented command and a green CI run.
