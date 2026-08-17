# luminary-memory

> A lightweight, self-hosted memory layer for AI agents.

**luminary-memory** gives AI agents durable, cross-session memory without shipping data to a third party. It runs entirely on your infrastructure, embeds and retrieves memories locally, and exposes a clean Python API and CLI that drop into any agent workflow. No external services required — SQLite out of the box, optional pgvector when you need scale.

---

## Why luminary-memory

Agents are only as good as what they remember. Stateless agents re-learn the same context every session; luminary-memory closes that gap with a local memory store that persists between runs, retrieves the right context on demand, and keeps itself tidy over time.

### Value proposition

- **Self-hosted and private** — all data stays on your machine. No cloud dependency, no API keys to leak, no per-token memory cost.
- **Four retrieval strategies in one recall** — semantic (embeddings), keyword (FTS5), temporal (recency/access), and graph (entity co-occurrence) run in parallel and fuse into a single ranked result.
- **Zero hard dependencies** — the default backend is SQLite + FTS5 (standard library). Embeddings run locally on CPU via ONNX. You can be ingesting and recalling memories in minutes.
- **Budget-aware by design** — results are deduplicated and truncated to a configurable token budget, so memory injection never blows up your agent's context window.
- **Self-maintaining** — a built-in lifecycle handles TTL expiry, near-duplicate consolidation, and low-value pruning, so the store stays lean without manual cleanup.
- **Scales when you do** — a pluggable backend lets you move from SQLite to pgvector without changing your code.

---

## Quickstart

### Install

```bash
pip install luminary-memory        # or, for development:
git clone <repo> && cd luminary-memory && pip install -e ".[dev]"
```

### Python API

```python
from luminary_memory import MemoryClient

client = MemoryClient(db_path="memory.db")

# store
mid = client.ingest("The deploy target is the staging cluster", tags=["deploy"])

# recall (four strategies, fused)
result = client.recall("where do we deploy?")
for memory, score in zip(result.memories, result.scores):
    print(f"{score:.3f}  {memory.content}")

# maintenance
client.run_lifecycle()   # cleanup + consolidate + prune

client.close()
```

### CLI

```bash
luminary-memory add "The deploy target is the staging cluster" --tags deploy
luminary-memory recall "where do we deploy?" --limit 5 --json
luminary-memory search "postgresql"
luminary-memory list
luminary-memory lifecycle
luminary-memory stats
```

---

## Architecture

```
                 ┌──────────────────────────────────────────┐
                 │                ingest()                   │
                 │  whitelist → (LLM enrich) → embed → store │
                 └──────────────┬───────────────────────────┘
                                ▼
                 ┌──────────────────────────────────────────┐
                 │           backend (pluggable)            │
                 │     SQLite + FTS5   |   pgvector         │
                 └──────────────┬───────────────────────────┘
                                ▼
                 ┌──────────────────────────────────────────┐
                 │                recall()                   │
                 │  semantic + keyword + temporal + graph    │
                 │        → RRF fusion → dedup → budget      │
                 └──────────────┬───────────────────────────┘
                                ▼
                 ┌──────────────────────────────────────────┐
                 │              lifecycle()                  │
                 │    TTL cleanup · consolidate · prune      │
                 └──────────────────────────────────────────┘
```

## Configuration

Every setting can be set via a `LUMINARY_*` environment variable or through `Settings` directly.

| Setting | Env var | Default |
|---------|---------|---------|
| `backend` | `LUMINARY_BACKEND` | `sqlite` |
| `db_path` | `LUMINARY_DB_PATH` | `luminary_memory.db` |
| `pg_dsn` | `LUMINARY_PG_DSN` | `postgresql://localhost/luminary_memory` |
| `embedding_model` | `LUMINARY_EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` |
| `embedding_dim` | `LUMINARY_EMBEDDING_DIM` | `384` |
| `rrf_k` | `LUMINARY_RRF_K` | `60` |
| `dedup_jaccard_threshold` | `LUMINARY_DEDUP_JACCARD_THRESHOLD` | `0.85` |
| `token_budget` | `LUMINARY_TOKEN_BUDGET` | `4096` |

---

## Backends

| | SQLite (default) | pgvector |
|---|---|---|
| **Dependencies** | stdlib + FTS5 | PostgreSQL + pgvector |
| **Vector search** | in-process cosine | HNSW index |
| **Best for** | single-user, edge, <100k memories | scale, concurrent access |
| **Setup** | zero-config | needs a running Postgres |

See [docs/backends.md](docs/backends.md) for a migration guide.

---

## Documentation

- [Quickstart](docs/quickstart.md) — install and first use
- [Architecture](docs/architecture.md) — pipelines and data flow
- [Python API](docs/api.md) — `MemoryClient` reference
- [CLI](docs/cli.md) — all subcommands and flags
- [Recall](docs/recall.md) — how the four strategies + fusion work
- [Lifecycle](docs/lifecycle.md) — cleanup, consolidation, pruning
- [Backends](docs/backends.md) — SQLite vs pgvector
- [Hermes integration](docs/hermes-integration.md) — use with Hermes Agent

## License

Apache-2.0 © 2026 Dwiky Candra
