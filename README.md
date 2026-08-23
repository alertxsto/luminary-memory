# 🌙 luminary-memory

**A lightweight, self-hosted memory layer for AI agents.**

[![PyPI version](https://img.shields.io/pypi/v/luminary-memory?color=8ab4e8&label=PyPI)](https://pypi.org/project/luminary-memory)
[![Python](https://img.shields.io/pypi/pyversions/luminary-memory?color=8ab4e8)](https://pypi.org/project/luminary-memory)
[![License](https://img.shields.io/github/license/alertxsto/luminary-memory?color=8ab4e8)](LICENSE)
[![CI](https://github.com/alertxsto/luminary-memory/actions/workflows/ci.yml/badge.svg)](https://github.com/alertxsto/luminary-memory/actions)
[![Tests](https://img.shields.io/badge/tests-505%2B%20passing-8ab4e8)](https://github.com/alertxsto/luminary-memory/actions)
[![Coverage](https://img.shields.io/badge/coverage-83%25-8ab4e8)](https://github.com/alertxsto/luminary-memory)
[![Stars](https://img.shields.io/github/stars/alertxsto/luminary-memory?color=8ab4e8)](https://github.com/alertxsto/luminary-memory)

**Self-hosted · Private · Budget-aware · Self-maintaining**

---

## What your agent remembers is what it becomes.

Agents are only as good as what they remember. A stateless agent re-learns the same context every session, paying the same tokens, making the same mistakes. luminary-memory closes that gap with a local memory store that persists between runs, retrieves the right context on demand, and keeps itself tidy over time.

**Four retrieval strategies. One fused result. Local by default.**

- **Semantic**, ONNX embeddings (384-dim, CPU, no GPU needed)
- **Keyword**, FTS5 BM25 (SQLite, zero config)
- **Temporal**, recency decay × access count
- **Graph**, entity co-occurrence with automatic curation
- **Active-task session continuity**, exact-session episodes preserve short-term context when durable recall abstains without promoting raw turns into semantic memory or widening scope across users, agents, or sessions.

Strategies fuse via **weighted RRF (semantic 0.4, keyword 0.3, graph 0.2, temporal 0.1)** → **scope/status/time filtering** → **conservative confidence and abstention** → **adaptive cutoff** → **Jaccard deduplication** → **token budget**. Short queries may be expanded with graph entities or stored content tokens before embedding; there is no language-specific alias classifier.

**Important rules always in context.** Durable rules tagged `core` are auto-loaded into the system prompt every session (the DB-backed `MEMORY.md`). All other memories are surfaced through query retrieval: relevant facts are recalled on demand (ranked by query relevance) and merged with the core block under anti-duplication. When durable recall abstains, the Hermes provider can also expose a bounded exact-session continuity block so an ambiguous follow-up stays attached to its active task without turning raw conversation into durable memory.

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
luminary-memory activity --limit 5
luminary-memory list
luminary-memory lifecycle
luminary-memory stats
```

---

## Hermes Agent, first-class memory provider

Luminary integrates through Hermes' public `MemoryProvider` entry point. The
installer selects Luminary and disables Hermes' two native persistent-memory
surfaces (`MEMORY.md` and `USER.md`) using their existing config switches, so
the agent has one durable memory authority without a Hermes source patch or a
version-specific fork.

For a new install, use `bash hermes/install.sh`. If configuring Hermes
manually, set the provider and the two native switches together:

```yaml
memory:
  provider: luminary
  memory_enabled: false
  user_profile_enabled: false
```

This is capability-based integration, not a version pin. Hermes must expose the
`MemoryProvider` entry-point contract and lifecycle; when it does not, setup
should stop with a visible diagnostic rather than silently running two memory
systems. No Hermes version number is embedded in Luminary's runtime path.

From the next session: **auto-recall** injects relevant memories every turn,
the **auto-retain** hook evaluates completed turns for durable storage and
serialized self-improvement review, and the model can call
`luminary_recall` / `luminary_ingest` / `luminary_list` on demand.

Two optional LLM-powered features keep the store sharp:

- **`ingest_llm`**, curates automatic turn batches before storage, then reconciles the current turn against exact-scope candidates. It can save a grounded new fact or explicitly version/retract a claim; it cannot mutate from similarity alone. Without curation, automatic transcript batches are not promoted into durable memory, but remain available in the exact-session continuity ledger; explicit memory/core writes remain available.
- **`auto_maintain`**, reviews the store at session end: keeps current facts, updates changed ones, deletes stale or duplicate ones.

Provider settings are exposed in the [Hermes dashboard](https://alertxsto.github.io/luminary-memory) for tuning. See
[docs/config-reference.md](docs/config-reference.md) for the complete reference and
[hermes/README.md](hermes/README.md) for the one-shot installer.

### Audit-grade behavior

Exact active-memory deduplication is enforced by the database for the full
`user/workspace/agent/session` scope, so concurrent writers converge on one
row instead of racing through a read-then-insert check. Evidence-required
recall fails closed when a quote is not grounded in the stored content, and
`MemoryClient.count()` reports the same active, scope-visible view as
`list()`.

Hermes writes scoped JSONL troubleshooting events to
`~/.hermes/luminary/luminary.log`. Events include `trace_id`, operation,
status/reason, counts, confidence, and latency; prompt text, memory content,
Telegram tokens, and API keys are omitted. Inspect it with:

```bash
tail -f ~/.hermes/luminary/luminary.log | jq
```

The documentation map below is the public source of truth for the library,
provider, operator, and integration guides. The benchmark notes keep the
boundary around Mem0/Hindsight comparisons explicit: matched local
measurements, not a universal superiority claim.

---

## Configuration

Every setting has a `LUMINARY_*` env var or a `Settings` object.

| Setting | Env var | Default |
|---------|---------|---------|
| `backend` | `LUMINARY_BACKEND` | `sqlite` |
| `db_path` | `LUMINARY_DB_PATH` | `luminary_memory.db` |
| `pg_dsn` | `LUMINARY_PG_DSN` | `postgresql://localhost/luminary_memory` (pgvector only) |
| `pg_hnsw_index` | `LUMINARY_PG_HNSW_INDEX` | `false` |
| `pg_hnsw_m` | `LUMINARY_PG_HNSW_M` | `16` |
| `pg_hnsw_ef_construction` | `LUMINARY_PG_HNSW_EF_CONSTRUCTION` | `64` |
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
| `importance_recall_boost` | `LUMINARY_IMPORTANCE_RECALL_BOOST` | `1.0` |
| `rule_auto_replace` | `LUMINARY_RULE_AUTO_REPLACE` | `true` (legacy library default; requires explicit supersession) |
| `rule_auto_replace_threshold` | `LUMINARY_RULE_AUTO_REPLACE_THRESHOLD` | `0.85` |
| `rule_importance` | `LUMINARY_RULE_IMPORTANCE` | `0.9` |
| `core_tag` | `LUMINARY_CORE_TAG` | `core` |
| `core_top_n` | `LUMINARY_CORE_TOP_N` | `12` |
| `core_budget` | `LUMINARY_CORE_BUDGET` | `8000` |
| `query_planner` | `LUMINARY_QUERY_PLANNER` | `true` |
| `query_planner_keyword_threshold` | `LUMINARY_QUERY_PLANNER_KEYWORD_THRESHOLD` | `0.9` |
| `ingest_whitelist` | `LUMINARY_INGEST_WHITELIST` | `[]` |
| `llm_base_url` | `LUMINARY_LLM_BASE_URL` | `""` |
| `llm_api_key` | `LUMINARY_LLM_API_KEY` | `""` |
| `llm_model` | `LUMINARY_LLM_MODEL` | `gpt-4o-mini` |
| `llm_timeout` | `LUMINARY_LLM_TIMEOUT` | `10` |
| `llm_max_tokens` | `LUMINARY_LLM_MAX_TOKENS` | `512` |
| `rule_keywords` | `LUMINARY_RULE_KEYWORDS` | `""` (compatibility only; not used for durability classification) |

> The direct library client keeps `rule_auto_replace=true` for compatibility,
> but replacement still requires an explicit `supersedes_id`. The accuracy-facing
> CLI and Hermes provider disable replacement unless that relationship is supplied
> and preserve conflicting claims for auditability. `rule_keywords` is retained
> only for callers that already depend on the compatibility matcher; it does not
> classify memory by language or vocabulary.

> Provider-specific settings (Hermes dashboard): `max_memories`,
> `mode`, `recall_limit`, `auto_recall`, `recall_sync`, `auto_retain`,
> `retain_every_n_turns`, `retain_user_prefix` / `retain_assistant_prefix`,
> `ingest_llm`, `auto_maintain`, `consolidate_semantic`, `importance_auto`,
> `recall_indicator`, `retain_indicator` (live in `~/.hermes/luminary/config.json`).
> See [hermes/SKILL.md](hermes/SKILL.md) for the full provider config table.

---

## Architecture

Memory is a **loop**, not a pipeline you run once. Every turn, luminary
recalls what is relevant before the agent answers, then ingests what mattered
after, and a background lifecycle keeps the store lean.

```
        ┌───────────────────────────── LOOP ─────────────────────────────┐
        │                                                               │
   recall(query) ──► scoped strategy candidates ──► weighted RRF ──► confidence/abstention ──► ranked results
        ▲            semantic │ keyword │ temporal │ graph   (per-strategy weights)   (cliff detection)
        │                                                               │
        └── inject into agent context ◄── token budget (4096) ◄── dedup (Jaccard 0.85)
                                                            │            │
   core memory ──► auto-loaded every session (tag 'core') ─┘ (merged, anti-duplicated)
                                                            │
   ingest(text) ──► whitelist ──► (LLM curation) ──► embed (ONNX 384-d) ─┘
   Hermes sync_turn ──► serialized retain ──► incremental review ──► capture / supersede / retract
                                                            │
   lifecycle() ──► cleanup (TTL) ──► consolidate (semantic + Jaccard, pinned exempt) ──► prune (importance, pinned exempt)
   maintenance() ──► LLM reviews store ──► keep │ update │ delete stale facts
```

**Accuracy safeguards:**

| Stage | Mechanism |
|-------|-----------|
| **4 strategies** | Semantic (ONNX cosine, vectorized matmul) + keyword (FTS5 BM25) + temporal (recency × access, batched fetch) + graph (entity co-occurrence, SQL aggregation) |
| **Scope isolation** | User/workspace/agent/session predicates are applied before fusion and fallback |
| **Abstention** | Strict provider/CLI paths can return `abstain` when support is weak or ambiguous |
| **Evidence** | Stored claims retain evidence quote, source, validity time, and audit provenance |
| **Conflict safety** | Conflicting claim keys remain versioned/conflicted until explicit supersession or resolution |
| **Core memory** | Rules tagged `core` are auto-loaded into the system prompt every session (the DB-backed MEMORY.md), independent of query match |
| **Weighted fusion** | Each strategy carries a tunable weight (semantic 0.4, keyword 0.3, graph 0.2, temporal 0.1), so high-signal strategies dominate the ranking |
| **Query expansion** | Short queries are expanded with co-occurring graph entities before embedding; when the graph is empty, content tokens from a topically related important memory may be appended (v0.2.15). No language-specific alias list is used. |
| **Importance boost** | Memories at importance ≥ 0.8 get a ranking bonus, lifting durable rules above weak-but-recent noise |
| **Adaptive cutoff** | Cliff detection keeps only the relevant cluster: a sparse store returns 3 strong matches instead of padding to 20, while a dense relevant store keeps everything (no over-filtering) |
| **Token budget** | Hard cap so memory injection never blows up the context window |

**Why it stays clean:**

| Stage | Mechanism |
|-------|-----------|
| **Lifecycle** | TTL cleanup, semantic consolidation (embedding cosine, fallback Jaccard), importance-based pruning (all batched at the backend level) |
| **Rule pinning** | Memories at importance ≥ 0.9 are pinned: never pruned, never deleted by consolidation |
| **Rule replacement** | Hermes/CLI disable destructive replacement by default; legacy direct-client behavior remains compatibility-controlled |
| **Store hygiene** | Automatic transcript batches require a curated summary before entering durable memory; malformed or uncurated batches stay only in the exact-session ledger, while explicit writes preserve their supplied provenance. Durability is not inferred from language-specific keywords. |
| **Auto importance** | Every memory is scored by recency + access + graph centrality; prune and health use live values. On recall, frequently-used memories are re-estimated immediately so they rank higher in the next turn's query recall (v0.2.15, `LUMINARY_IMPORTANCE_AUTO`) |
| **Max memories cap** | `max_memories` (default 1000) prunes the oldest/lowest-importance when the store exceeds it |
| **LLM maintenance** | `ingest_llm` adds a grounded post-turn review; optional `auto_maintain` reviews the store at session end: keep, update, or delete stale facts |
| **Health score** | `health_score()` gives a 0-100 checkup with actionable recommendations; core-tagged rows are recognized as always-loaded prompt data rather than false “never accessed” recall rows |
| **Content-level anti-dup** | Core and recall share one dedup set (ids + content hashes), so a rule stored both as `core` and as a plain memory appears exactly once per turn (v0.2.15) |

`health_score()` gives you a 0-100 checkup with actionable recommendations.

---

## Documentation

| Section | |
|---------|-----|
| [Quickstart](docs/quickstart.md) | Install and first use |
| [Architecture](docs/architecture.md) | Pipelines and data flow |
| [Python API](docs/api.md) | `MemoryClient` reference |
| [Agent Tools](docs/agent-tools.md) | 6 tools reference + parameter schema |
| [CLI](docs/cli.md) | All subcommands |
| [Recall](docs/recall.md) | Four strategies + fusion |
| [Lifecycle](docs/lifecycle.md) | Cleanup, consolidation, pruning, LLM maintenance |
| [Backends](docs/backends.md) | SQLite vs pgvector |
| [Configuration reference](docs/config-reference.md) | Library env vars + provider config |
| [Hermes integration](docs/hermes-integration.md) | Provider, config, installer |
| [Debugging Guide](docs/debugging-v0.2.17.md) | Gateway envelopes, hook internals, verification |
| [Benchmarks](benchmarks/RESULTS.md) | Pipeline smoke + independent gold-set metrics (not a competitor proof) |

---

## License

[Apache-2.0](LICENSE) © 2026 Dwiky Candra
