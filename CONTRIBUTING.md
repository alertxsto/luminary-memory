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
4. Run the checks:

```bash
python -m pytest
python -m ruff check src tests
```

5. Commit with a conventional message.

## Branch model

- **`develop`**, integration branch. **All pull requests target `develop`.**
- **`main`**, stable release branch, protected. Only maintainers merge release
  commits into it (feature → develop → main → tag).

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
- Coverage must stay ≥ 90%.

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
python -m pytest          # ~200+ tests, green without any external service
python -m ruff check src tests
```

Coverage (must stay ≥ 90%):

```bash
python -m pytest --cov=luminary_memory --cov-report=term
```

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
