# Quickstart

## Install

```bash
pip install luminary-memory
```

For development:

```bash
git clone <repo> && cd luminary-memory
pip install -e ".[dev]"
```

## First use (Python)

```python
from luminary_memory import MemoryClient

client = MemoryClient(db_path="memory.db")

# 1. store a fact
client.ingest("The deploy target is the staging cluster", tags=["deploy"])

# 2. recall context
result = client.recall("where do we deploy?", limit=5)
for memory, score in zip(result.memories, result.scores):
    print(f"{score:.3f}  {memory.content}")

# 3. maintain the store
client.run_lifecycle()

client.close()
```

## First use (CLI)

```bash
luminary-memory add "The deploy target is the staging cluster" --tags deploy
luminary-memory recall "where do we deploy?" --json
luminary-memory stats
```

## Configuration

All settings accept a `LUMINARY_*` env var:

| Setting | Env var | Default |
|---------|---------|---------|
| `backend` | `LUMINARY_BACKEND` | `sqlite` |
| `db_path` | `LUMINARY_DB_PATH` | `luminary_memory.db` |
| `pg_dsn` | `LUMINARY_PG_DSN` | `postgresql://localhost/luminary_memory` |
| `embedding_model` | `LUMINARY_EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` |
| `token_budget` | `LUMINARY_TOKEN_BUDGET` | `4096` |

See the [README](../README.md) for the full table.
