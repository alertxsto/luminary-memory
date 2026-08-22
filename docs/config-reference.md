# Configuration reference

This page documents **every** configuration input for luminary-memory, where it
can be set, its default, and what changing it actually does. It is the single
authoritative list, generated from the two real sources of truth:

- `src/luminary_memory/config.py` → `Settings` dataclass (library-level, read
  from `LUMINARY_*` environment variables).
- `src/luminary_memory/hermes/config.py` → `_DEFAULTS` (Hermes provider config,
  persisted to `$HERMES_HOME/luminary/config.json` and surfaced in the
  dashboard).

There are two layers by design:

1. **Library settings** (`Settings` + `LUMINARY_*` env vars) control the core
   engine: recall, embeddings, consolidation, pruning, LLM enrichment.
2. **Provider config** (`config.json` + dashboard) controls how the provider
   hooks into Hermes: which AI agent session triggers auto-recall/auto-save,
   what gets injected into the system prompt, and LLM endpoint settings.

---

## Tables of contents

| Layer | Where set | Link |
|-------|-----------|------|
| Library settings (`Settings`) | `LUMINARY_*` env vars | [section below](#library-settings-settings) |
| Provider config (`_DEFAULTS`) | `$HERMES_HOME/luminary/config.json` + dashboard | [section below](#provider-config-defaults) |
| Dashboard-only secrets | `LUMINARY_LLM_API_KEY` | [section below](#secrets) |

---

# Library settings (`Settings`)

Read once at startup from environment variables. No file, no dashboard, just
env. Every field is documented with:

- field name, env var, default, allowed values, and what it controls.

> Tip: values set here are engine-level and shared everywhere. If you only use
> the Hermes provider, most of these have a `config.json` counterpart that
> overrides them per agent profile.

## Storage backends

| Field | Env var | Default | Meaning |
|-------|---------|---------|---------|
| `backend` | `LUMINARY_BACKEND` | `sqlite` | Which store to use: `sqlite` (zero-config, stdlib) or `pgvector` (Postgres + vector index). |
| `db_path` | `LUMINARY_DB_PATH` | `luminary_memory.db` | Filesystem path of the SQLite DB (used when `backend=sqlite`). |
| `pg_dsn` | `LUMINARY_PG_DSN` | `postgresql://localhost/luminary_memory` | Postgres connection string (used when `backend=pgvector`). |
| `pg_hnsw_index` | `LUMINARY_PG_HNSW_INDEX` | `false` | Build an HNSW vector index on the embeddings table (faster ANN search on large stores). |
| `pg_hnsw_m` | `LUMINARY_PG_HNSW_M` | `16` | HNSW graph degree (higher = more accurate, slower build). |
| `pg_hnsw_ef_construction` | `LUMINARY_PG_HNSW_EF_CONSTRUCTION` | `64` | HNSW build-time exploration factor (higher = better recall at build cost). |

## Embeddings

| Field | Env var | Default | Meaning |
|-------|---------|---------|---------|
| `embedding_model` | `LUMINARY_EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | HF sentence-transformer used for semantic similarity. English-focused; mixed Indonesian/English queries match better with keyword-heavy weights. |
| `embedding_dim` | `LUMINARY_EMBEDDING_DIM` | `384` | Embedding vector dimension, must match the model output and the pgvector column. |

## Recall

Controls how stored memories are matched and ranked against a query.

| Field | Env var | Default | Meaning |
|-------|---------|---------|---------|
| `rrf_k` | `LUMINARY_RRF_K` | `60` | Recursive Rank Fusion constant. Higher smooths score differences across the fusion strategies. |
| `strategy_weights.semantic` | `LUMINARY_WEIGHT_SEMANTIC` | `0.4` | Fusion weight for embedding similarity. |
| `strategy_weights.keyword` | `LUMINARY_WEIGHT_KEYWORD` | `0.3` | Fusion weight for lexical/FTS keyword match. |
| `strategy_weights.graph` | `LUMINARY_WEIGHT_GRAPH` | `0.2` | Fusion weight for entity-graph relationships. |
| `strategy_weights.temporal` | `LUMINARY_WEIGHT_TEMPORAL` | `0.1` | Fusion weight for recency. |
| `recall_cliff_threshold` | `LUMINARY_RECALL_CLIFF_THRESHOLD` | `0.45` | Adaptive cutoff: results that drop more than 45% below the top score are trimmed. Higher = more aggressive trimming. |
| `dedup_jaccard_threshold` | `LUMINARY_DEDUP_JACCARD_THRESHOLD` | `0.85` | Near-duplicates (token-overlap Jaccard ≥ this) are removed before ranking. Lower = more aggressive dedup. |
| `token_budget` | `LUMINARY_TOKEN_BUDGET` | `4096` | Hard cap on total tokens injected by a recall, so memory never overflows the agent context. |
| `importance_recall_boost` | `LUMINARY_IMPORTANCE_RECALL_BOOST` | `1.0` | Ranking multiplier applied to memories at importance ≥ 0.8, so durable rules surface before chit-chat in recall. |
| `recall_min_score` | `LUMINARY_RECALL_MIN_SCORE` | `0.0` | Score floor for recall results; memory below this is dropped (0 = off). Provider/CLI may return an empty result when no evidence survives. |
| `query_planner` | `LUMINARY_QUERY_PLANNER` | `true` | Route the query among strategies (skip semantic if low confidence, etc.). |
| `query_planner_keyword_threshold` | `LUMINARY_QUERY_PLANNER_KEYWORD_THRESHOLD` | `0.9` | Score above which a keyword match is trusted so the planner skips semantic/graph passes. |

> ### Persistent context (removed in v0.2.18)
>
> The importance-based persistent-context family (`context_top_n`,
> `context_budget`, `context_min_importance`) was removed. Importance is now
> used **only** for query retrieval/recall and pruning — it no longer pins
> memory into the system prompt as rules that could override a live user
> instruction. Durable rules that must always be present belong in **core
> memory** (below).

## Accuracy and isolation safety

| Field | Env var | Default | Meaning |
|-------|-----------|---------|---------|
| `strict_recall` | `LUMINARY_STRICT_RECALL` | `false` for legacy library clients | Enables abstention when support is weak or ambiguous. Hermes and CLI enable it explicitly. |
| `scope_include_global` | `LUMINARY_SCOPE_INCLUDE_GLOBAL` | `true` | Allows intentionally global rows to remain visible to a scoped caller; set `false` for strict tenant isolation. |
| `abstention_min_confidence` | `LUMINARY_ABSTENTION_MIN_CONFIDENCE` | `0.34` | Minimum conservative confidence for strict recall. |
| `abstention_min_margin` | `LUMINARY_ABSTENTION_MIN_MARGIN` | `0.04` | Minimum top-vs-second margin for ambiguous strict results. |
| `evidence_required` | `LUMINARY_EVIDENCE_REQUIRED` | `false` for legacy library clients | Requires evidence/source provenance for strict results and maintenance mutations. Hermes and CLI enable it explicitly. |

Provider and CLI also disable destructive semantic rule replacement. Direct
library clients retain the historical default for compatibility; use
`rule_auto_replace=False` when correctness is more important than legacy
behavior.

## Runtime scope identity

Scope is an API/provider concern rather than a `Settings` field. The library
accepts a `scope` mapping or explicit ownership arguments on ingest; the CLI
reads these environment variables for the current process:

| Environment variable | Memory field |
|---|---|
| `LUMINARY_USER_ID` | `user_id` |
| `LUMINARY_WORKSPACE_ID` | `workspace_id` |
| `LUMINARY_AGENT_ID` | `agent_id` |
| `LUMINARY_SESSION_ID` | `session_id` |

Each configured identity is applied before semantic, keyword, graph, temporal,
tag, and fallback candidate generation. `scope_include_global=true` keeps
legacy rows with `NULL` ownership visible during migration; set it to `false`
for strict tenant isolation.

## Core memory (DB-backed, auto-loaded system prompt)

The Luminary equivalent of Hermes `MEMORY.md`, stored in the DB.

| Field | Env var | Default | Meaning |
|-------|---------|---------|---------|
| `core_tag` | `LUMINARY_CORE_TAG` | `core` | Tag marking DB-backed core memories. Everything carrying this tag is auto-loaded into the system prompt every session. |
| `core_top_n` | `LUMINARY_CORE_TOP_N` | `12` | Max core memories injected into the system prompt. |
| `core_budget` | `LUMINARY_CORE_BUDGET` | `8000` | Max character budget for the core-memory block. |

## Store lifecycle

| Field | Env var | Default | Meaning |
|-------|---------|---------|---------|
| `max_memories` | `LUMINARY_MAX_MEMORIES` | `1000` | Hard cap on store size; oldest/lowest importance pruned when exceeded (pinned at ≥ 0.9 are exempt). |
| `ttl_default_seconds` | `LUMINARY_TTL_DEFAULT_SECONDS` | `0` (none) | Default TTL for memories without an explicit expiry; after this they are candidates for pruning. |
| `prune_min_importance` | `LUMINARY_PRUNE_MIN_IMPORTANCE` | `0.2` | Memories below this importance are pruned during lifecycle cleanup. |
| `consolidate_jaccard_threshold` | `LUMINARY_CONSOLIDATE_JACCARD_THRESHOLD` | `0.9` | Token-overlap threshold for merging near-identical memories. |
| `consolidate_semantic` | `LUMINARY_CONSOLIDATE_SEMANTIC` | `true` | Merge paraphrases using embedding cosine (falls back to Jaccard when embeddings missing/degenerate). |
| `importance_auto` | `LUMINARY_IMPORTANCE_AUTO` | `true` | Auto-estimate each memory's importance from access count, recency, and graph centrality. |

## Ingest

| Field | Env var | Default | Meaning |
|-------|---------|---------|---------|
| `ingest_llm` | `LUMINARY_INGEST_LLM` | `false` | Enrich retained turns with an LLM (drops chit-chat, stores a factual summary instead of raw transcript). |
| `ingest_whitelist` | `LUMINARY_INGEST_WHITELIST` | `[]` | Comma-separated list of content prefixes/tags allowed to be ingested; empty = everything. |

## LLM enrichment

| Field | Env var | Default | Meaning |
|-------|---------|---------|---------|
| `llm_base_url` | `LUMINARY_LLM_BASE_URL` | (none) | OpenAI-compatible endpoint for the enricher (supports standard endpoints and gateway envelopes like Cline Pass). |
| `llm_api_key` | `LUMINARY_LLM_API_KEY` | (none) | API key for the enricher (secret). |
| `llm_model` | `LUMINARY_LLM_MODEL` | `gpt-4o-mini` | Enricher model id. |
| `llm_timeout` | `LUMINARY_LLM_TIMEOUT` | `10` | Request timeout (seconds). |
| `llm_max_tokens` | `LUMINARY_LLM_MAX_TOKENS` | `512` | Max completion tokens for the enricher output. |

## Rule detection

Turn a surfaced instruction into a pinned, non-contradictory rule.

| Field | Env var | Default | Meaning |
|-------|---------|---------|---------|
| `rule_keywords` | `LUMINARY_RULE_KEYWORDS` | `NEVER,ALWAYS,MUST,...` | Comma-separated imperative markers that indicate a rule (`NEVER`, `ALWAYS`, `MUST`, `FORBIDDEN`, ...). |
| `rule_importance` | `LUMINARY_RULE_IMPORTANCE` | `0.9` | Importance assigned to a detected rule (≥ 0.9 = pinned, exempt from prune/consolidate). |
| `rule_auto_replace` | `LUMINARY_RULE_AUTO_REPLACE` | `true` (legacy library default) | Replace an existing rule semantically similar to a new one instead of stacking conflicting rows. Hermes/CLI set this to `false` so claim conflicts remain auditable. |
| `rule_auto_replace_threshold` | `LUMINARY_RULE_AUTO_REPLACE_THRESHOLD` | `0.85` | Embedding-cosine similarity at which a new rule replaces the old one. |

**Note on rule detection scope:** with `ingest_llm` enabled, rule keywords are
checked **only** against the LLM-curated summary, never the raw transcript. A
turn that merely mentions "PLAN" is not pinned as a rule.

---

# Provider config (`_DEFAULTS`)

Persisted to `$HERMES_HOME/luminary/config.json` (created on first save, mode
`0600`). Missing keys fall back to these defaults, so the file is optional and
forward-compatible. This is what the dashboard (`Settings → Memory`) and
`hermes memory setup luminary` read/write.

| Key | Default | Meaning | In dashboard? |
|-----|---------|---------|---------------|
| `mode` | `hybrid` | Injection mode: `context` (auto-inject only), `tools` (tool-only), `hybrid` (both). | ✅ |
| `db_path` | `""` | Override store path; empty = `$HERMES_HOME/luminary/memory.db`. | ✅ |
| `backend` | `sqlite` | `sqlite` or `pgvector`. | ✅ |
| `recall_limit` | `10` | Top-N memories returned per recall. | ✅ |
| `max_memories` | `1000` | Hard cap on store size; oldest/lowest importance pruned when exceeded. | ✅ |
| `token_budget` | `2048` | Recall context token budget. | ✅ |
| `auto_recall` | `true` | Enable per-turn background recall. | ✅ |
| `auto_retain` | `true` | Enable per-turn auto-save. | ✅ |
| `recall_sync` | `false` | Synchronous (live) recall instead of warm prefetch. | ✅ |
| `retain_every_n_turns` | `1` | Batch N turns into one store write. | ✅ |
| `retain_user_prefix` | `User` | Prefix when formatting retained user turns. | ✅ |
| `retain_assistant_prefix` | `Assistant` | Prefix when formatting retained assistant turns. | ✅ |
| `ingest_llm` | `false` | LLM curation on retain (drops chit-chat, stores factual summary). | ✅ |
| `auto_maintain` | `false` | LLM store review at session end (keeps/updates/deletes stale or duplicate facts; requires `ingest_llm`). | ✅ |
| `consolidate_semantic` | `true` | Embedding-cosine consolidation in lifecycle. | ✅ |
| `importance_auto` | `true` | Auto importance estimation on ingest/lifecycle. | ✅ |
| `llm_base_url` | `""` | OpenAI-compatible endpoint for the enricher (supports standard endpoints and gateway envelopes like Cline Pass). | ✅ |
| `llm_model` | `""` | Enricher model. | ✅ |
| `llm_timeout` | `60` | Enricher request timeout (seconds). | ✅ |
| `recall_indicator` | `true` | Show `🌙 Luminary, recalled N memories`. | ✅ |
| `retain_indicator` | `true` | Show `🌙 Luminary, memory saved`. | ✅ |
| `core_tag` | `core` | Tag marking DB-backed core memories. | ✅ |
| `core_top_n` | `12` | Max core memories injected into the system prompt. | ✅ |
| `core_budget` | `8000` | Max characters of core memory injected. | ✅ |
| `extract_on_session_end` | `false` | Compatibility/dashboard flag reserved for session-end extraction integrations; normal provider retention is already flushed at session end. | ✅ |
| `importance_recall_boost` | `1.0` | Ranking multiplier for memories at importance ≥ 0.8 — durable rules surface first in recall. | ✅ |
| `recall_min_score` | `0.0` | Score floor for recall results (0 = off; weak results may be empty). | ✅ |

---

# Secrets

| Key | Env var / config | Default | Meaning |
|-----|------------------|---------|---------|
| `llm_api_key` | `LUMINARY_LLM_API_KEY` | `""` | Enricher API key. Treated as a secret by the provider schema (never echoed by the CLI/setup). Appears as a secret field in the dashboard. |

---

## Env var → config.json mapping (quick per-layer cheat sheet)

Since the two layers can both tune overlapping behavior, here is what wins when
both are set: the **provider `config.json` value** is used by the Hermes
provider for its own behavior, but the **library `Settings` env var** is used
for engine internals (recall/consolidation) and for tools (`luminary_recall`
etc.). When they disagree, engine-level tuning tends to be the actual behavior
because the tools call straight into `MemoryClient`.

If you depend on a specific value, set it in **both** places, or keep one layer
at default and tune the other.
