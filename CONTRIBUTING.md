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
