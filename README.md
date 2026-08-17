<div align="center">

# 🌙 luminary-memory

**A lightweight, self-hosted memory layer for AI agents.**

[![PyPI version](https://img.shields.io/pypi/v/luminary-memory?color=8ab4e8&label=PyPI&logo=pypi&logoColor=white)](https://pypi.org/project/luminary-memory)
[![Python](https://img.shields.io/pypi/pyversions/luminary-memory?color=8ab4e8&logo=python&logoColor=white)](https://pypi.org/project/luminary-memory)
[![License](https://img.shields.io/github/license/alertxsto/luminary-memory?color=8ab4e8)](https://github.com/alertxsto/luminary-memory/blob/main/LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/alertxsto/luminary-memory/ci.yml?color=8ab4e8&label=CI&logo=github)](https://github.com/alertxsto/luminary-memory/actions)
[![Tests](https://img.shields.io/badge/tests-101%20passing-8ab4e8)](https://github.com/alertxsto/luminary-memory/actions)
[![Coverage](https://img.shields.io/badge/coverage-89%25-8ab4e8)](https://github.com/alertxsto/luminary-memory)
[![Stars](https://img.shields.io/github/stars/alertxsto/luminary-memory?color=8ab4e8&logo=github)](https://github.com/alertxsto/luminary-memory)

**Self-hosted · Private · Budget-aware · Self-maintaining**

</div>

---

## Why luminary-memory

Agents are only as good as what they remember. A stateless agent re-learns the same context every session — paying the same tokens, making the same mistakes. luminary-memory closes that gap with a local memory store that persists between runs, retrieves the right context on demand, and keeps itself tidy over time.

**What your agent remembers is what it becomes.**

### Value proposition

- **Self-hosted and private** — all data stays on your machine. No cloud dependency, no API keys to leak, no per-token memory cost.
- **Four retrieval strategies in one recall** — semantic (embeddings), keyword (FTS5), temporal (recency × access), and graph (entity co-occurrence) run in parallel and fuse into a single ranked result via Reciprocal Rank Fusion.
- **Zero hard dependencies** — the default backend is SQLite + FTS5 (standard library). Embeddings run locally on CPU via ONNX. Ingesting and recalling memories in minutes.
- **Budget-aware by design** — results are deduplicated (Jaccard) and truncated to a configurable token budget, so memory injection never blows up your agent's context window.
- **Self-maintaining** — a built-in lifecycle handles TTL expiry, near-duplicate consolidation, and low-value pruning, so the store stays lean without manual cleanup.
- **Scales when you do** — a pluggable backend lets you move from SQLite to pgvector without changing your code.

---

## Quickstart

### Install

```bash
pip install luminary-memory
```

### Python API

```python
from luminary_memory import MemoryClient

client = MemoryClient(db_path="memory.db")

# store a durable fact
client.ingest("The deploy target is the staging cluster", tags=["deploy", "infra"])

# recall — four strategies fused into one ranked answer
result = client.recall("where do we deploy?")
for memory, score in zip(result.memories, result.scores):
    print(f"{score:.3f}  {memory.content}")
# → 0.942  The deploy target is the staging cluster

# maintain the store (TTL cleanup + consolidation + pruning)
client.run_lifecycle()

client.close()
```

### CLI

```bash
luminary-memory add "The deploy target is the staging cluster" --tags deploy
luminary-memory recall "where do we deploy?" --json
luminary-memory search "postgresql"
luminary-memory list
luminary-memory lifecycle
luminary-memory stats
```

---

## How recall works

Four retrieval strategies run in parallel, then fuse into one ranked result:

| Strategy | What it finds | Backend |
|----------|---------------|---------|
| **Semantic** | Meaning, paraphrase, synonyms | ONNX embeddings (384-dim, CPU) |
| **Keyword** | Exact names, APIs, identifiers | FTS5 BM25 (SQLite) / ILIKE (pgvector) |
| **Temporal** | Recent, frequently-accessed facts | Decay curve × access count |
| **Graph** | Entity co-occurrence, indirect links | `entities` / `relations` tables |

**Fusion pipeline:** `4 strategies → RRF fusion (k=60) → Jaccard dedup (0.85) → token budget (4096)`

---

## Backends

| | SQLite + FTS5 (default) | PostgreSQL + pgvector |
|---|---|---|
| **Dependencies** | stdlib + FTS5 | PostgreSQL + pgvector extension |
| **Vector search** | In-process cosine | HNSW-ready (`<=>` operator) |
| **Best for** | Single-user, edge, <100k memories | Scale, concurrent access |
| **Setup** | Zero-config | Running Postgres + `LUMINARY_PG_DSN` |

Switch backends with one setting:

```python
from luminary_memory import MemoryClient
from luminary_memory.config import Settings

client = MemoryClient(settings=Settings(
    backend="pgvector",
    pg_dsn="postgresql://user:pass@localhost/memdb",
))
```

---

## Configuration

Every setting can be set via a `LUMINARY_*` environment variable or passed as a `Settings` object.

| Setting | Env var | Default |
|---------|---------|---------|
| `backend` | `LUMINARY_BACKEND` | `sqlite` |
| `db_path` | `LUMINARY_DB_PATH` | `luminary_memory.db` |
| `pg_dsn` | `LUMINARY_PG_DSN` | `postgresql://localhost/luminary_memory` |
| `embedding_model` | `LUMINARY_EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` |
| `embedding_dim` | `LUMINARY_EMBEDDING_DIM` | `384` |
| `ingest_whitelist` | `LUMINARY_INGEST_WHITELIST` | `[]` (regex patterns) |
| `ingest_llm` | `LUMINARY_INGEST_LLM` | `false` |
| `rrf_k` | `LUMINARY_RRF_K` | `60` |
| `dedup_jaccard_threshold` | `LUMINARY_DEDUP_JACCARD_THRESHOLD` | `0.85` |
| `token_budget` | `LUMINARY_TOKEN_BUDGET` | `4096` |
| `ttl_default_seconds` | `LUMINARY_TTL_DEFAULT_SECONDS` | `null` |
| `prune_min_importance` | `LUMINARY_PRUNE_MIN_IMPORTANCE` | `0.2` |
| `consolidate_jaccard_threshold` | `LUMINARY_CONSOLIDATE_JACCARD_THRESHOLD` | `0.9` |

---

## Use cases

- **AI coding agents** — retain architecture decisions, API choices, and error fixes across sessions.
- **Chatbots & assistants** — remember user preferences, history, and conversation context.
- **Automation pipelines** — persist execution state, task outcomes, and learned parameters.
- **Personal knowledge & local RAG** — a private second brain with zero cloud involvement.

---

## Architecture

```
ingest(text) ──► whitelist filter ──► (LLM enrich, optional) ──► embed ──► backend
                                                                          │
recall(query) ──► 4 strategies (semantic·keyword·temporal·graph)
               ──► RRF fusion ──► Jaccard dedup ──► token budget ──► ranked results
                                                                          │
lifecycle() ──► cleanup (TTL) ──► consolidate (near-dupes) ──► prune (low-value)
```

---

## Hermes integration

A ready-to-use skill lives in [`hermes/SKILL.md`](hermes/SKILL.md): install it, then the agent can ingest durable facts on tool calls, recall context into its system prompt, and schedule lifecycle maintenance via cron. See [docs/hermes-integration.md](docs/hermes-integration.md).

---

## Development

```bash
git clone https://github.com/alertxsto/luminary-memory.git
cd luminary-memory
pip install -e ".[dev]"

python -m pytest          # run tests
python -m ruff check src tests   # lint
```

Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

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

## Roadmap

See [ROADMAP.md](ROADMAP.md) for the full product roadmap — v0.2.0 (quality & scale), v0.3.0 (intelligence), and v1.0.0 (stable).

---

## License

[Apache-2.0](LICENSE) © 2026 Dwiky Candra
