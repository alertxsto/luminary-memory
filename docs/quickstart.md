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

# 4. check store health (0-100 score + recommendations)
print(client.health_score())

client.close()
```

## First use (CLI)

```bash
luminary-memory add "The deploy target is the staging cluster" --tags deploy
luminary-memory recall "where do we deploy?" --json
luminary-memory stats
luminary-memory health
```

## Backup & restore

```bash
luminary-memory export --path backup.json
luminary-memory import --path backup.json
```

`export` writes all memories to a JSON file (migration/backup); `import`
restores them (recomputing embeddings when absent).

## Optional: LLM memory curation

By default every ingest is stored verbatim (zero LLM cost). To have an LLM
evaluate each turn, dropping chit-chat and storing concise factual summaries
instead of raw transcripts, enable `ingest_llm` and `auto_maintain`:

```bash
pip install "luminary-memory[hermes]"
```

```json
// ~/.hermes/luminary/config.json (Hermes provider)
{
  "ingest_llm": true,
  "auto_maintain": true,
  "llm_base_url": "https://api.commandcode.ai/provider/v1",
  "llm_model": "deepseek/deepseek-v4-flash",
  "llm_api_key": "your-key"
}
```

Any OpenAI-compatible endpoint works. `auto_maintain` reviews the store at
session end, keeping current facts, updating changed ones, deleting stale or
duplicate memories.

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
