# Contributing

Thanks for helping build luminary-memory.

## Setup

```bash
git clone <repo> && cd luminary-memory
pip install -e ".[dev]"
```

## Development workflow

1. Create a branch: `git checkout -b feat/your-change`.
2. Write a failing test first (`tests/`).
3. Implement the minimal change.
4. Run the checks:

```bash
python -m pytest
python -m ruff check src tests
```

5. Commit with a conventional message.

## Commit conventions

- `feat:` — new feature
- `fix:` — bug fix
- `docs:` — documentation only
- `improve:` — refactor or enhancement without behavior change
- `chore:` — build/tooling

## Coding standards

- Python 3.11+, type-hinted.
- `ruff` clean, `pytest` green.
- TDD where feasible — test first, then implement.
- Keep the public API (`MemoryClient`) stable; add rather than break.

## Pull requests

- One logical change per PR.
- Link the issue if applicable.
- CI must pass before merge.

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
**skipped unless `LUMINARY_PG_DSN` is set** — CI currently does not provide
Postgres, so the pgvector path is the least-covered module (59%). If you're
working on the pgvector backend, run them locally with:

```bash
# spin up a throwaway Postgres with the pgvector extension
docker run -d --name luminary-pg -p 5432:5432 \
  -e POSTGRES_USER=luminary -e POSTGRES_PASSWORD=luminary -e POSTGRES_DB=luminary \
  pgvector/pgvector:pg16

# point the tests at it
export LUMINARY_PG_DSN=postgresql://luminary:luminary@localhost:5432/luminary
python -m pytest tests/test_backend_pgvector.py -v
```

See [issue #1](https://github.com/alertxsto/luminary-memory/issues/1) for
adding a Postgres service to CI so these tests run automatically.
