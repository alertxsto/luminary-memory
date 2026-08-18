# 🌙 luminary-memory

**A lightweight, self-hosted memory layer for AI agents.**

[![PyPI version](https://img.shields.io/pypi/v/luminary-memory?color=8ab4e8&label=PyPI)](https://pypi.org/project/luminary-memory)
[![Python](https://img.shields.io/pypi/pyversions/luminary-memory?color=8ab4e8)](https://pypi.org/project/luminary-memory)
[![License](https://img.shields.io/github/license/alertxsto/luminary-memory?color=8ab4e8)](LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/alertxsto/luminary-memory/ci.yml?color=8ab4e8&label=CI)](https://github.com/alertxsto/luminary-memory/actions)
[![Tests](https://img.shields.io/badge/tests-200%2B%20passing-8ab4e8)](https://github.com/alertxsto/luminary-memory/actions)
[![Coverage](https://img.shields.io/badge/coverage-91%25-8ab4e8)](https://github.com/alertxsto/luminary-memory)
[![Stars](https://img.shields.io/github/stars/alertxsto/luminary-memory?color=8ab4e8)](https://github.com/alertxsto/luminary-memory)

**Self-hosted · Private · Budget-aware · Self-maintaining**

---

## What your agent remembers is what it becomes.

Agents are only as good as what they remember. A stateless agent re-learns the same context every session, paying the same tokens, making the same mistakes. luminary-memory closes that gap with a local memory store that persists between runs, retrieves the right context on demand, and keeps itself tidy over time.

**Four retrieval strategies. One fused answer. Zero cloud.**

- **Semantic**, ONNX embeddings (384-dim, CPU, no GPU needed)
- **Keyword**, FTS5 BM25 (SQLite, zero config)
- **Temporal**, recency decay × access count
- **Graph**, entity co-occurrence with automatic curation

Strategies run in parallel and fuse via **weighted RRF (semantic 0.4, keyword 0.3, graph 0.2, temporal 0.1)** → **adaptive cutoff (cliff detection)** → **Jaccard deduplication (0.85)** → **token budget (4096)**. Short queries are expanded with graph entities before embedding, so "deploy?" still finds "production cluster".

---

## Quickstart

```bash
pip install luminary-memory
```

```python
from luminary_memory import MemoryClient

client = MemoryClient(db_path="memory.db")

# store a durable fact
client.ingest("The deploy target is the staging cluster", tags=["deploy", "infra"])

# recall, four strategies fused into one ranked answer
result = client.recall("where do we deploy?")
for memory, score in zip(result.memories, result.scores):
    print(f"{score:.3f}  {memory.content}")
# → 0.942  The deploy target is the staging cluster
```

```bash
# CLI
luminary-memory add "deploy target is staging" --tags deploy
luminary-memory recall "where do we deploy?" --json
luminary-memory list
luminary-memory lifecycle
luminary-memory stats
```

---

## Hermes Agent, first-class memory provider

Drop-in. Install the provider with `pip install "luminary-memory[hermes]"`, then add
`memory.provider: luminary` to your Hermes config. That's it.

From the next session: **auto-recall** injects relevant memories every turn,
**auto-save** persists completed turns, and the model can call
`luminary_recall` / `luminary_ingest` / `luminary_list` on demand.

Two optional LLM-powered features keep the store sharp:

- **`ingest_llm`**, evaluates every turn before saving: drops chit-chat, stores factual summaries instead of raw transcripts.
- **`auto_maintain`**, reviews the store at session end: keeps current facts, updates changed ones, deletes stale or duplicate ones.

22 settings are exposed in the [Hermes dashboard](https://alertxsto.github.io/luminary-memory) for zero-hassle tuning. See
[hermes/README.md](hermes/README.md) for the one-shot installer and full configuration.

---

## Configuration

Every setting has a `LUMINARY_*` env var or a `Settings` object.

| Setting | Env var | Default |
|---------|---------|---------|
| `backend` | `LUMINARY_BACKEND` | `sqlite` |
| `db_path` | `LUMINARY_DB_PATH` | `luminary_memory.db` |
| `pg_dsn` | `LUMINARY_PG_DSN` |, (pgvector only) |
| `embedding_model` | `LUMINARY_EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` |
| `embedding_dim` | `LUMINARY_EMBEDDING_DIM` | `384` |
| `ingest_llm` | `LUMINARY_INGEST_LLM` | `false` |
| `rrf_k` | `LUMINARY_RRF_K` | `60` |
| `strategy_weights` | `LUMINARY_WEIGHT_{SEMANTIC,KEYWORD,GRAPH,TEMPORAL}` | `0.4 / 0.3 / 0.2 / 0.1` |
| `recall_cliff_threshold` | `LUMINARY_RECALL_CLIFF_THRESHOLD` | `0.45` |
| `dedup_jaccard_threshold` | `LUMINARY_DEDUP_JACCARD_THRESHOLD` | `0.85` |
| `token_budget` | `LUMINARY_TOKEN_BUDGET` | `4096` |
| `max_memories` | `LUMINARY_MAX_MEMORIES` | `1000` |
| `ttl_default_seconds` | `LUMINARY_TTL_DEFAULT_SECONDS` | `null` |
| `prune_min_importance` | `LUMINARY_PRUNE_MIN_IMPORTANCE` | `0.2` |
| `consolidate_jaccard_threshold` | `LUMINARY_CONSOLIDATE_JACCARD_THRESHOLD` | `0.9` |
| `consolidate_semantic` | `LUMINARY_CONSOLIDATE_SEMANTIC` | `true` |
| `importance_auto` | `LUMINARY_IMPORTANCE_AUTO` | `true` |

See [hermes/SKILL.md](hermes/SKILL.md) for the full provider config table (22 settings).

---

## Architecture

Memory is a **loop**, not a pipeline you run once. Every turn, luminary
recalls what is relevant before the agent answers, then ingests what mattered
after, and a background lifecycle keeps the store lean.

```
        ┌───────────────────────────── LOOP ─────────────────────────────┐
        │                                                               │
   recall(query) ──► 4 strategies in parallel ──► weighted RRF ──► adaptive cutoff ──► ranked results
        ▲            semantic │ keyword │ temporal │ graph   (per-strategy weights)   (cliff detection)
        │                                                               │
        └── inject into agent context ◄── token budget (4096) ◄── dedup (Jaccard 0.85)
                                                                        │
   ingest(text) ──► whitelist ──► (LLM curation) ──► embed (ONNX 384-d) ─┘
                                                                        │
   lifecycle() ──► cleanup (TTL) ──► consolidate (semantic + Jaccard) ──► prune (importance)
   maintenance() ──► LLM reviews store ──► keep │ update │ delete stale facts
```

**Why it is accurate:**

| Stage | Mechanism |
|-------|-----------|
| **4 strategies** | Semantic (ONNX cosine) + keyword (FTS5 BM25) + temporal (recency × access) + graph (entity co-occurrence), all in parallel |
| **Weighted fusion** | Each strategy carries a tunable weight (semantic 0.4, keyword 0.3, graph 0.2, temporal 0.1), so high-signal strategies dominate the ranking |
| **Query expansion** | Short queries are expanded with co-occurring graph entities before embedding, so a bare "deploy?" still finds "production cluster" |
| **Adaptive cutoff** | Cliff detection keeps only the relevant cluster: a sparse store returns 3 strong matches instead of padding to 20, while a dense relevant store keeps everything (no over-filtering) |
| **Token budget** | Hard cap so memory injection never blows up the context window |

**Why it stays clean:**

| Stage | Mechanism |
|-------|-----------|
| **Lifecycle** | TTL cleanup, semantic consolidation (embedding cosine, fallback Jaccard), importance-based pruning |
| **Auto importance** | Every memory is scored by recency + access + graph centrality; prune and health use live values |
| **Max memories cap** | `max_memories` (default 1000) prunes the oldest/lowest-importance when the store exceeds it |
| **LLM maintenance** | Optional `auto_maintain` reviews the store at session end: keep, update, or delete stale facts |
| **Health score** | `health_score()` gives a 0-100 checkup with actionable recommendations |

`health_score()` gives you a 0-100 checkup with actionable recommendations.

---

## Documentation

| Section | |
|---------|-----|
| [Quickstart](docs/quickstart.md) | Install and first use |
| [Architecture](docs/architecture.md) | Pipelines and data flow |
| [Python API](docs/api.md) | `MemoryClient` reference |
| [CLI](docs/cli.md) | All subcommands |
| [Recall](docs/recall.md) | Four strategies + fusion |
| [Lifecycle](docs/lifecycle.md) | Cleanup, consolidation, pruning, LLM maintenance |
| [Backends](docs/backends.md) | SQLite vs pgvector |
| [Hermes integration](docs/hermes-integration.md) | Provider, config, installer |
| [Roadmap](ROADMAP.md) | v0.2.10 → v1.0.0 |
| [Benchmarks](benchmarks/RESULTS.md) | 230 ms recall @ 5k, 0 LLM tokens |

---

## License

[Apache-2.0](LICENSE) © 2026 Dwiky Candra
