# Contributing

Thanks for helping build luminary-memory.

## Setup

```bash
git clone <repo> && cd luminary-memory
pip install -e ".[dev]"
```

## Development workflow

1. Create a branch from `develop`: `git checkout develop && git checkout -b feat/your-change`.
2. Write a failing test first (`tests/`).
3. Implement the minimal change.
4. Update the tracked guide that owns the changed contract and the matching
   static website guide in `website/js/docs-guides.js`. Keep ignored planning
   notes under `docs/` out of the public source.
5. Run the checks:

```bash
python -m pytest
python -m ruff check src tests hermes/hooks
node --check website/js/docs-guides.js
```

5. Commit with a conventional message.

## Branch model

- **`develop`**, integration branch. **All pull requests target `develop`.**
- **`main`**, stable release branch, protected. Only maintainers merge release
  commits into it (feature → develop → main → tag).

## Release gate

Tagging `v*` publishes to PyPI through `.github/workflows/publish.yml`, and
`pypi` has a hard prerequisite: the `real-model` job. It runs

```bash
python scripts/smoke-real-model.py --report real-model-gate.json
```

which drives public `MemoryClient.recall` end to end on an isolated SQLite store
with the real default embedding model and asserts **which facts come back**:

- the current scoped deploy fact for both an exact and a paraphrased question;
- an off-topic but graph-linked documentation row is not returned;
- an expired row, another tenant's row and a scoped query stay inside their
  boundaries;
- unanswerable queries abstain.

It fails closed — a wrong model, a failed download or a failed inference aborts
the job — and the JSON report is uploaded as an artifact even when it fails.
Run it locally before tagging; it is not part of the unit suite because it needs
the real ONNX model.

A gate that passes on a confident wrong answer is worse than no gate. When the
gate fails, fix the retrieval defect; never relax the gate or swap in a stub
embedder.

## Commit conventions

- `feat:`, new feature
- `fix:`, bug fix
- `docs:`, documentation only
- `improve:`, refactor or enhancement without behavior change
- `chore:`, build/tooling

## Coding standards

- Python 3.11+, type-hinted.
- `ruff` clean, `pytest` green.
- TDD where feasible, test first, then implement.
- Keep the public API (`MemoryClient`) stable; add rather than break.
- Full-source coverage is reported and must not regress from the current
  evidence-backed baseline (`83%`, 5,092 statements, 876 missed). Every changed
  behavior needs a targeted regression or invariant test; do not inflate
  coverage with tests that only execute lines without checking outcomes.
  PostgreSQL-only branches are verified separately by the pgvector integration
  job.

### Long-run checks

Changes to ingest, recall, lifecycle or retention must also survive a soak run,
because those defects only appear across cycles:

```bash
python scripts/soak-test.py --cycles 400 --per-cycle 5 --report /tmp/soak.json
```

It fails on a lost control fact, a no-answer query that starts returning rows,
or recall p50 growing more than `3x` between the first and last fifth of the
run. See [Lifecycle](docs/lifecycle.md#long-run-behaviour) for what it measures
and the current observed numbers.

## AI assistance notice

If you use **any kind of AI assistance** to contribute to luminary-memory, please
disclose it in the pull request together with the extent of the usage. For
example:

> This PR was written primarily by Claude Code.
>
> I consulted ChatGPT to understand the codebase, but the solution was fully
> authored manually.

This helps reviewers apply the right level of scrutiny. AI assistance isn't
always perfect, even when used with the utmost care, a quick disclosure goes a
long way. Please don't use AI to write the pull request description or
contributor communication; keep it concise and in your own voice.

## Pull requests

- One logical change per PR.
- Target the **`develop`** branch.
- Link the issue if applicable.
- CI must pass before merge.
- Automated checks run on every PR:
  - **CI**, unit tests (Python 3.11 & 3.12) + lint.
  - **pgvector integration**, real Postgres round-trips (HNSW, JSONB, rollback).
  - **Triage**, auto-labels the PR and welcomes first-time contributors.
  - **Contributor check**, a soft account/language triage hint for maintainers.

## Testing

Run the full suite (SQLite + unit tests) locally:

```bash
python -m pytest          # 541 passed, 3 skipped at the current baseline
python -m ruff check src tests hermes/hooks
```

Coverage (full-source baseline):

```bash
python -m pytest --cov=luminary_memory --cov-report=term
```

The current local baseline is `541 passed, 3 skipped` at `83%` (`5,092`
statements, `876` missed). The
number is intentionally reported honestly while the defensive PostgreSQL and
failure branches continue to receive integration coverage; the quality gate
is the invariant-focused test suite plus the CI/verification coverage gate
`--fail-under=82`.

### Postgres / pgvector integration tests

`tests/test_backend_pgvector.py` contains real-Postgres round-trips that are
**skipped unless `LUMINARY_PG_DSN` is set**. CI provides a Postgres service for
these (see `.github/workflows/ci.yml`). To run them locally:

```bash
# spin up a throwaway Postgres with the pgvector extension
docker run -d --name luminary-pg -p 5432:5432 \
  -e POSTGRES_USER=luminary -e POSTGRES_PASSWORD=luminary -e POSTGRES_DB=luminary \
  pgvector/pgvector:pg16

# point the tests at it
export LUMINARY_PG_DSN=postgresql://luminary:***@localhost:5432/luminary
python -m pytest tests/test_backend_pgvector.py -v
```
