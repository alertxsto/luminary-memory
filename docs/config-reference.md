# Configuration reference

This page documents **every** configuration input for luminary-memory, where it
can be set, its default, and what changing it actually does. It has three
integration layers:

- `src/luminary_memory/config.py` → `Settings` dataclass (library-level, read
  from `LUMINARY_*` environment variables).
- `src/luminary_memory/hermes/config.py` → `_DEFAULTS` (Hermes provider config,
  persisted to `$HERMES_HOME/luminary/config.json` and surfaced in the
  dashboard).
- `opencode/package.json` and `opencode/src/plugin.ts` → the OpenCode npm
  plugin configuration and plugin options.

There are three layers by design:

1. **Library settings** (`Settings` + `LUMINARY_*` env vars) control the core
   engine: recall, embeddings, consolidation, pruning, LLM enrichment.
2. **Provider config** (`config.json` + dashboard) controls how the provider
   hooks into Hermes: which AI agent session triggers auto-recall and automatic
   turn curation,
   what gets injected into the system prompt, and LLM endpoint settings.
3. **OpenCode plugin config** (`opencode.json` plus plugin options) controls
   package discovery, sidecar selection, and OpenCode scope mapping. It does not
   enable Hermes provider features.

---

## Tables of contents

| Layer | Where set | Link |
|-------|-----------|------|
| Library settings (`Settings`) | `LUMINARY_*` env vars | [section below](#library-settings-settings) |
| Provider config (`_DEFAULTS`) | `$HERMES_HOME/luminary/config.json` + dashboard | [section below](#provider-config-defaults) |
| OpenCode plugin configuration | `opencode.json`, plugin options, `.opencode/` | [section below](#opencode-plugin-configuration) |
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
| `embedding_model` | `LUMINARY_EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | Sentence-transformer used for semantic similarity. Language coverage follows the selected model; the memory pipeline does not classify durability from vocabulary. |
| `embedding_dim` | `LUMINARY_EMBEDDING_DIM` | `384` | Embedding vector dimension, must match the model output and the pgvector column. |

## Recall

Controls how stored memories are matched and ranked against a query.

| Field | Env var | Default | Meaning |
|-------|---------|---------|---------|
| `rrf_k` | `LUMINARY_RRF_K` | `60` | Reciprocal Rank Fusion constant. Higher smooths score differences across the fusion strategies. |
| `strategy_weights.semantic` | `LUMINARY_WEIGHT_SEMANTIC` | `0.4` | Fusion weight for embedding similarity. |
| `strategy_weights.keyword` | `LUMINARY_WEIGHT_KEYWORD` | `0.3` | Fusion weight for lexical/FTS keyword match. |
| `strategy_weights.graph` | `LUMINARY_WEIGHT_GRAPH` | `0.2` | Fusion weight for entity-graph relationships. |
| `strategy_weights.temporal` | `LUMINARY_WEIGHT_TEMPORAL` | `0.1` | Fusion weight for recency. |
| `recall_cliff_threshold` | `LUMINARY_RECALL_CLIFF_THRESHOLD` | `0.45` | Adaptive cutoff: results that drop more than 45% below the top score are trimmed. Higher = more aggressive trimming. |
| `dedup_jaccard_threshold` | `LUMINARY_DEDUP_JACCARD_THRESHOLD` | `0.85` | Near-duplicates (token-overlap Jaccard ≥ this) are removed before ranking. Lower = more aggressive dedup. |
| `token_budget` | `LUMINARY_TOKEN_BUDGET` | `4096` | Hard cap on total tokens injected by a recall, so memory never overflows the agent context. |
| `importance_recall_boost` | `LUMINARY_IMPORTANCE_RECALL_BOOST` | `1.0` | Ranking multiplier applied to memories at importance ≥ 0.8, so durable rules surface before chit-chat in recall. |
| `recall_min_score` | `LUMINARY_RECALL_MIN_SCORE` | `0.0` | Score floor for recall results; memory below this is dropped (0 = off). Provider/CLI may return an empty result when no evidence survives. |
| `query_planner` | `LUMINARY_QUERY_PLANNER` | `true` | Apply conservative strategy guards (for example, skip graph when no entity signal exists, or temporal when a strong lexical match is present). Semantic and keyword candidates remain enabled. |
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
| `core_tag` | `LUMINARY_CORE_TAG` | `core` | Tag marking DB-backed core memories. Active rows carrying this tag are eligible for the every-session prompt block, bounded by `core_top_n` and `core_budget`. |
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
| `ingest_llm` | `LUMINARY_INGEST_LLM` | `false` | Enrich retained turns and run the provider's grounded incremental review (drops chit-chat, stores a factual summary, and checks for captures/corrections instead of storing raw transcript). |
| `ingest_whitelist` | `LUMINARY_INGEST_WHITELIST` | `[]` | Comma-separated list of content prefixes/tags allowed to be ingested; empty = everything. |

## LLM enrichment

| Field | Env var | Default | Meaning |
|-------|---------|---------|---------|
| `llm_base_url` | `LUMINARY_LLM_BASE_URL` | (none) | OpenAI-compatible endpoint for the enricher (supports standard endpoints and gateway envelopes like Cline Pass). |
| `llm_api_key` | `LUMINARY_LLM_API_KEY` | (none) | API key for the enricher (secret). |
| `llm_model` | `LUMINARY_LLM_MODEL` | `gpt-4o-mini` | Enricher model id. |
| `llm_timeout` | `LUMINARY_LLM_TIMEOUT` | `10` | Request timeout (seconds). |
| `llm_max_tokens` | `LUMINARY_LLM_MAX_TOKENS` | `512` | Max completion tokens for the enricher output. |

## Compatibility and explicit replacement

These fields remain for compatibility with older callers. They do not classify
durability from words or language. Durable core membership is explicit (`core`
tag or core tool), structured importance comes from the caller/enricher or the
behavioral estimator, and conflicting claims require an explicit supersession.

| Field | Env var | Default | Meaning |
|-------|---------|---------|---------|
| `rule_keywords` | `LUMINARY_RULE_KEYWORDS` | `""` | Compatibility input for callers of the standalone phrase matcher. It is not read by the active durability/importance pipeline. |
| `rule_importance` | `LUMINARY_RULE_IMPORTANCE` | `0.9` | Pin threshold used by core/importance protection. It is not assigned because a phrase matches. |
| `rule_auto_replace` | `LUMINARY_RULE_AUTO_REPLACE` | `true` (legacy library default) | Enables the explicit replacement compatibility path. A `supersedes_id` is still required; without it, different same-key claims remain auditable conflicts. Hermes/CLI disable this path by default. |
| `rule_auto_replace_threshold` | `LUMINARY_RULE_AUTO_REPLACE_THRESHOLD` | `0.85` | Similarity threshold used only after the caller explicitly authorizes replacement. |

---

## OpenCode plugin configuration

OpenCode uses JSON or JSONC configuration. Add the published npm package to the
project `opencode.json`; OpenCode installs it through Bun:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": ["opencode-luminary-memory@0.1.0"]
}
```

Project plugins may also live in `.opencode/plugins/`; global plugins use
`~/.config/opencode/plugins/`. Skills use `.opencode/skills/<name>/SKILL.md` or
`~/.config/opencode/skills/<name>/SKILL.md`; copy the package skill there when
package skill discovery is unavailable. Keep `opencode-luminary-memory@0.1.0` paired
with `luminary-memory==0.3.0`; the sidecar protocol is version `1`.

The plugin options are:

| Option | Meaning |
| --- | --- |
| `userID` | Local identity override used as `user_id`. |
| `clientOptions.pythonExecutable` | Python executable for the sidecar. |
| `clientOptions.databasePath` | Sets `LUMINARY_DB_PATH` for the sidecar. |
| `clientOptions.sidecarModule` | Python module, default `luminary_memory.opencode.sidecar`. |
| `clientOptions.cwd` | Sidecar working directory. |
| `clientOptions.timeoutMs` | Per-request timeout, default 10000 ms. |
| `clientOptions.transport` | Injected transport for development/tests only. |

OpenCode automatic recall is fixed by the plugin to `limit=5` and `strict=true`.
It has no `mode`, `auto_recall`, `auto_retain`, `recall_sync`,
`retain_every_n_turns`, `auto_maintain`, indicator, or core-tool settings.
`LUMINARY_DB_PATH` and the library `LUMINARY_*` settings still configure the
Python sidecar engine.

OpenCode maps normalized `worktree` or `directory` to `workspace_id`, the
OpenCode agent name to `agent_id`, and carries the session id as `session_id` in
protocol/client context. Durable `recall`, `ingest`, and `list` use only
`user_id`/`workspace_id`/`agent_id`; `session_id` is removed from those
operations. No current OpenCode sidecar operation (`health`, `recall`, `ingest`,
or `list`, as applicable) exposes exact-session continuity or episode
operations. The local identity
precedence is plugin `userID`, then `LUMINARY_USER_ID`, then
`USER`/`USERNAME`/`HOME`, all prefixed with `local:` when derived from the
environment. The model cannot override ownership fields.

---

# Provider config (`_DEFAULTS`) (Hermes only)

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
| `auto_retain` | `true` | Record accepted turns in the exact-session continuity ledger and queue completed batches for curation; uncurated automatic transcripts are not promoted into durable memory. | ✅ |
| `recall_sync` | `false` | Synchronous (live) recall instead of warm prefetch. | ✅ |
| `retain_every_n_turns` | `1` | Batch N turns into one store write. | ✅ |
| `retain_user_prefix` | `User` | Structural prefix supplied to the optional curator for user content. | ✅ |
| `retain_assistant_prefix` | `Assistant` | Structural prefix supplied to the optional curator for assistant content. | ✅ |
| `ingest_llm` | `false` | LLM curation on retain plus serialized post-turn reconciliation (drops chit-chat, stores factual summary, and requires current-turn evidence for mutations). | ✅ |
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
| `extract_on_session_end` | `false` | Compatibility/dashboard flag; the current provider does not run a second extraction mode from this key. Session end drains accepted retains and may run `auto_maintain`. | ✅ |
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

## Hermes activation boundary (Hermes only)

These three values live in Hermes' `$HERMES_HOME/config.yaml`, not in
Luminary's `$HERMES_HOME/luminary/config.json`:

```yaml
memory:
  provider: luminary
  memory_enabled: false
  user_profile_enabled: false
```

`provider` selects the public Luminary entry point. The two boolean switches
disable Hermes' native `MEMORY.md` and `USER.md` prompt/tool surfaces, leaving
one persistent authority. `hermes/install.sh` updates this block idempotently
in the root config and in profile configs that already exist; it does not
create profiles, rewrite Hermes source, or require a Hermes version number. If
a provider update leaves either native switch enabled, treat the installation
as incomplete rather than merging the stores implicitly.

The provider runtime does not import Hermes' private Python modules. Its
optional setup callback is only a convenience for Hermes CLIs that expose that
callback; the on-disk activation helper and the installer remain the portable
path across Hermes updates.

## Exact-session continuity is not another config layer (Hermes only)

When Hermes `auto_retain` is enabled, each accepted completed turn is written
to the backend's immutable episode ledger with the current `session_id`,
ownership scope, and sequence metadata before the durable curation queue runs.
If durable recall returns no usable block, the provider may read only the
current session's recent episodes (up to four rows, bounded by the existing
`token_budget` and an internal character ceiling) as untrusted reference
context. The current user request remains authoritative.

This fallback is intentionally not exposed as a new toggle or provider key:
turns in the ledger are continuity evidence, not semantic memories, and they
are never used to widen a query into another session, user, workspace, or
agent. Set `auto_retain=false` only when automatic episode admission and
automatic durable curation should both be disabled.
