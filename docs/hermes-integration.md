# Hermes integration

Use luminary-memory as a first-class **memory provider** for [Hermes Agent](https://github.com/NousResearch/hermes-agent). The recommended path is the pip entry-point provider (`luminary`), which replaces the standalone-skill approach described below. The provider uses the strict accuracy path: scoped candidates, evidence-required results, abstention, and non-destructive rule updates.

## Preferred: install the provider

`luminary-memory` ships a Hermes `MemoryProvider` registered through the
`hermes_agent.memory_providers` entry-point group.

```bash
pip install "luminary-memory[hermes]"
bash hermes/install.sh
```

The installer uses `HERMES_PYTHON` when it is set, so package installation,
capability checks, and config activation all run in the same interpreter as a
Hermes deployment. Without it, the installer uses `python3`.

Activation updates the root Hermes config and only the profile config files
that already exist. It does not create profile directories or guess which
profiles a deployment should use, so existing profile selection stays intact
without coupling Luminary to a Hermes release layout.

`hermes memory setup luminary` may still be used to edit provider settings on
Hermes installations that expose the optional provider setup hook. The
installer is the portable activation path because it writes only the public
`config.yaml` boundary and does not depend on that optional CLI callback.

Then set in `config.yaml`:

```yaml
memory:
  provider: luminary
  memory_enabled: false
  user_profile_enabled: false
```

The two native switches are part of Hermes' existing memory configuration.
They are written automatically by `hermes/install.sh` and by Hermes setup when
it supports the optional provider setup hook. Keeping them off is what makes
Luminary the sole persistent memory surface; no Hermes core file is modified.

The provider has three deliberately separate context surfaces:

1. **Core memory** — active DB rows tagged `core`, selected in stable insertion
   order and bounded by `core_top_n`/`core_budget`; loaded in the system prompt
   every session.
2. **Durable query recall** — strict, evidence-aware semantic, keyword, graph,
   and temporal retrieval for the current request.
3. **Exact-session continuity** — at most the recent current-session episode
   window, injected only when durable recall produces no usable block. It is an
   untrusted reference, never semantic memory, never a cross-session fallback,
   and not an additional configuration surface.

On the next session Hermes will:

- **Auto-recall every turn**, the current user message is used to recall relevant memories from the local store, injected as a `# Luminary Memory (persistent cross-session context)` reference block. The block is filtered by session/user/workspace/agent scope and may explicitly abstain.
- **Core rules auto-load every session**, durable rules tagged `core` (the DB-backed `MEMORY.md`) are always in the system prompt, independent of query match. All other memories come from query recall, merged under anti-duplication so nothing appears twice.
- **Auto-retain and reconcile every completed turn**, accepted turns first enter a
  strictly scoped episode ledger, then are queued under session lineage tags
  (`session:<id>`, `parent:<id>`, `platform:<p>`, `agent:<identity>`). A normal
  curation pass produces a concise fact, then a serialized incremental reviewer
  compares the turn with scoped active/conflicted candidates. Raw turns are
  kept only as exact-session continuity evidence; they are never promoted to
  semantic durable memory unless curation produces a grounded fact. Explicit
  ingest/core/delegation writes remain available.
- **Preserve the active task on ambiguous follow-ups**, when durable recall abstains, Luminary can inject a bounded, untrusted reference block from the current session's recent episodes. This keeps a scoped request attached to its immediately active topic instead of silently widening it to the entire session library. The current user request remains authoritative.
- **Expose explicit tools**, `luminary_recall` / `luminary_ingest` / `luminary_list` are registered for the model in `tools` and `hybrid` modes.
- **Report a deterministic indicator**, a `🌙 Luminary, recalled N memories` status line appears whenever recall injected context.

`auto_retain=false` disables both automatic episode admission and automatic
curation for that provider instance. `retain_every_n_turns` only controls when
the buffered batch enters the durable curation queue; each accepted turn is
still recorded individually in the exact-session ledger first.

Luminary does not edit Hermes' native data files or source tree. The runtime
uses only the provider entry point and the public `MemoryProvider` lifecycle,
prompt, recall, tool, and turn hooks. If the configured provider cannot be
loaded, Hermes' normal provider-availability diagnostic is the source of truth;
Luminary does not silently pretend that native and external memories were
merged.

### Hermes upgrades

There is no Hermes source patch to rebase or merge. Upgrade Hermes normally,
keep the `memory.provider` selection and the two native switches in
`config.yaml`, then restart the gateway. A future Hermes release that removes
or changes the provider entry-point contract must be handled as an explicit
compatibility issue; it must not be papered over with a private import or a
version check in Luminary.

If an existing store contains rows imported from another authority or raw
Hermes turn batches from an earlier configuration, inspect the repair plan
before enabling a new deployment:

```bash
python scripts/repair_memory_authority.py \
  --db-path ~/.hermes/luminary/memory.db
python scripts/repair_memory_authority.py \
  --db-path ~/.hermes/luminary/memory.db --apply
```

The first command is read-only. `--apply` creates a consistent SQLite backup,
archives only structurally identified historical/uncurated rows, and appends
an audit event; it does not delete data or infer facts from a language list.

### Configuration

The provider reads `$HERMES_HOME/luminary/config.json` (created on first save with
`0600` permissions). Key settings:

> For the complete reference of every config key and environment variable, see [Configuration reference](config-reference.md).

| Key | Default | Meaning |
|-----|---------|---------|
| `mode` | `hybrid` | `context` (auto-inject only) · `tools` (tool-only) · `hybrid` (both) |
| `db_path` | `""` | Override store path; `""` = `$HERMES_HOME/luminary/memory.db` |
| `backend` | `sqlite` | `sqlite` or `pgvector` |
| `recall_limit` | `10` | Top-N memories per recall |
| `max_memories` | `1000` | Hard cap on store size, oldest/lowest-importance pruned when exceeded |
| `token_budget` | `2048` | Recall context budget |
| `auto_recall` | `true` | Enable per-turn background recall |
| `recall_sync` | `false` | Synchronous (live) recall instead of warm prefetch |
| `auto_retain` | `true` | Record accepted turns in the exact-session continuity ledger and queue completed batches for the curation gate; raw turns are not promoted without curation |
| `retain_every_n_turns` | `1` | Batch N turns into one store write |
| `ingest_llm` | `false` | **LLM memory curation and incremental reconciliation**, the enricher decides whether a turn is worth saving, stores a factual summary instead of the raw transcript, and checks the same turn for grounded captures/corrections |
| `llm_base_url` | `""` | OpenAI-compatible endpoint for the enricher (e.g. `https://api.cline.bot/v1`, `https://api.commandcode.ai/provider/v1`, Groq, Ollama) |
| `llm_model` | `""` | Enricher model (e.g. `deepseek/deepseek-v4-flash`) |
| `llm_api_key` | `""` | Enricher API key (settable as a secret field in the dashboard) |
| `llm_timeout` | `60` | Enricher request timeout (seconds) |
| `recall_indicator` | `true` | Show `🌙 Luminary, recalled N memories` |
| `retain_indicator` | `true` | Show `🌙 Luminary, memory saved` |
| `retain_user_prefix` | `User` | Prefix used when formatting retained user turns |
| `retain_assistant_prefix` | `Assistant` | Prefix used when formatting retained assistant turns |
| `extract_on_session_end` | `false` | Compatibility/dashboard flag; the current provider does not run a second extraction mode from this key. Session-end behavior is queue drain plus optional `auto_maintain` |
| `auto_maintain` | `false` | **LLM store review at session end**, keeps/updates/deletes stale, contradicted, or duplicate facts (requires `ingest_llm`) |
| `consolidate_semantic` | `true` | **Embedding-cosine consolidation** in lifecycle, merges paraphrases (falls back to Jaccard when embeddings are degenerate/missing) |
| `importance_auto` | `true` | **Auto importance estimation**, scores each memory from access, recency, and graph centrality on ingest/lifecycle |
| `importance_recall_boost` | `1.0` | Ranking bonus multiplier for memories at importance ≥ 0.8, so durable rules surface in recall (configurable via config.json / dashboard OR via LUMINARY_IMPORTANCE_RECALL_BOOST env var) |
| `core_tag` | `core` | Tag marking DB-backed core memories — always auto-loaded into the system prompt every session (like MEMORY.md) |
| `core_top_n` | `12` | Max core memories injected into the system prompt |
| `core_budget` | `8000` | Max characters of core memory injected into the system prompt |

The provider internally sets `strict_recall=true`, `evidence_required=true`,
and `rule_auto_replace=false` regardless of the legacy direct-client defaults.
This keeps weak results abstainable and contradictory claims auditable.

### Core memory (DB-backed, v0.2.13+)

Luminary equivalent of Hermes' native `MEMORY.md`, but stored in the
database. Memories tagged `core` are **auto-loaded into the system prompt
every session (the DB-backed `MEMORY.md`) — so a new session that
has not mentioned the topic yet still gets the durable instruction from the
very first prompt.

```
Core memory (auto-loaded every session):
- <rule 1>
- <rule 2>
```

Core and query recall are intentionally different surfaces. Core is curated
persistent context for stable identity, preferences, and durable rules; the
agent should apply it as default context when relevant and follow an explicit
current-user correction. Query recall is evidence that may be stale or
incomplete, not an instruction and never a higher-priority system message.

Managed via tools (`luminary_core_add` / `luminary_core_remove` /
`luminary_core_list`) or by ingesting with the `core` tag. The block is capped
by `core_top_n` memories and `core_budget` characters and selected in stable
ascending store-id/insertion order. Core memories are pinned (importance ≥
0.9, exempt from prune/consolidate).

**Sourcing (v0.2.15):** core content comes **only** from the database —
`by_tag_top(tag)` reads memories carrying the `core` tag. It is **never**
derived from recall results or from `_injected_ids`.

**Anti-duplication (v0.2.15):** `_injected_ids` is an anti-dup **tracker**, not
a content source. Core and recall both add to it, and the recall
block skips anything already injected. Dedup is now **content-level** as well
as id-level: a memory whose text is already in the core block is skipped by
recall even when it has a different id — so a rule
stored both as `core` and as a plain high-importance memory appears in context
**exactly once** per turn.

### Persistent context (removed in v0.2.18)

The importance-based persistent-context family (`context_top_n`,
`context_budget`, `context_min_importance`) was **removed**. Importance is now
used only for query retrieval/recall and pruning; it no longer pins memory
into the system prompt as rules that could override a live user instruction.
Durable rules that must always be present across sessions belong in **core
memory** (auto-loaded via the `core` tag).

### LLM memory curation (v0.2.2+)

With `ingest_llm: true`, every retained turn is sent to the enricher, which
returns:

- **`worth_saving`**, `false` excludes the turn from durable semantic memory
  (chit-chat, greetings, and trivial acknowledgements never become durable
  facts). The raw turn may still remain in the exact-session continuity ledger.
- **`summary`**, a concise factual summary in the turn's language that
  becomes the stored content, instead of the raw `User: ... / Assistant: ...`
  transcript.
- **`entities` / `tags`**, attached as metadata/tags for richer recall.

The enricher talks to the configured `llm_base_url` over HTTP with
`requests` (User-Agent `luminary-memory/<version>`, one immediate retry on
transient failure). `requests` is used instead of `urllib.request` because
some OpenAI-compatible gateways sit behind Cloudflare, which blocks the
plain `urllib` User-Agent with HTTP 1010; `requests` sends a browser-like
User-Agent and keeps a connection pool, so curation calls get through.
Errors are surfaced as `enricher_failed` in the event log instead of being
silently swallowed, so an outage never masquerades as "nothing worth saving".

Without `ingest_llm` (default), automatic turn batches are treated as
uncurated observations and skipped by the durable-memory writer, with zero LLM
cost, while the separate session ledger still preserves short-term continuity.
Direct `luminary_ingest`, core-memory operations, and other explicit provider
hooks remain writable without an LLM.

### Incremental self-improvement review

When `ingest_llm` is enabled, the provider performs a second, provider-owned
review after each queued automatic retain batch. This is not a second memory
authority and does not touch Hermes source or skill files:

1. the normal retain task commits (or rejects) the curated summary;
2. the same writer queue passes the current turn plus a bounded exact-scope
   candidate window to `review_turn`;
3. the structured response may capture a new fact, explicitly supersede a
   claim, retract a fact, or keep everything unchanged;
4. every capture or mutation must cite an exact substring from the current
   turn, target a candidate ID, and pass the store's evidence and scope guards.

Supersession preserves the old row and claim lineage. A same-key correction
without an explicit grounded action remains a conflict; similarity alone never
overwrites a memory. Invalid JSON, unknown IDs, unsupported actions, missing
evidence, or a failed LLM call are recorded as skipped/degraded review events
and cannot kill the retain worker. `auto_maintain` remains the broader
session-boundary sweep; the incremental reviewer is what catches corrections
before a real session boundary.

The CLI-capable Hermes path may show a truthful status such as:

```text
🌙 Luminary — self-improvement: saved 1, updated 1, retracted 1
```

The structured log records `memory.review.started`,
`memory.review.completed`, `memory.review.action_skipped`, and
`memory.review.failed` without raw turn or memory content. The optional
Telegram activity hook remains delivery-safe and reports only persisted active
rows at `agent:end`; it does not call Telegram from the provider and therefore
does not create a second integration path.

### Rule hygiene (v0.2.11+)

Two safeguards keep rules accurate and non-contradictory:

- **No vocabulary-specific rule detection**: durability is decided by the
  explicit write path, structured curation output, or behavioral importance
  estimation; it is never inferred from a hardcoded language marker list.
- **Raw automatic transcripts are dropped when curation is absent or yields no
  summary**: with `ingest_llm: true`, a turn whose enrichment fails or returns
  nothing durable is not stored verbatim (avoids polluting the store with
  conversation noise).
- **Non-destructive provider writes**: Hermes disables semantic rule
  auto-replacement. A same-key, different-value claim remains `conflicted`
  until the caller supplies an explicit supersession and evidence. The direct
  library client keeps its legacy `rule_auto_replace` default for compatibility.
- **Rule pinning**: memories at importance ≥ 0.9 are pinned — never pruned by
  importance or the `max_memories` cap, and never deleted by consolidation.

### Scope, evidence, and status

Provider-owned memories carry `user_id`, `workspace_id`, `agent_id`, and
`session_id` when Hermes supplies them. Scope predicates run before semantic,
keyword, graph, temporal, and fallback candidate generation. Every accepted
write stores a grounded `evidence_quote`, source identifier, status, and
confidence. Normal recall hides `conflicted`, `superseded`, and expired rows;
diagnostic callers can request conflicts explicitly.

### Store layout

```
$HERMES_HOME/luminary/
├── config.json          # provider config, 0600
├── memory.db            # SQLite store (created by MemoryClient)
└── luminary.log         # JSONL transparency log (scoped operations/errors)
```

The store is profile-scoped and picked up by `hermes backup` automatically. If you
override `db_path` to a location outside HERMES_HOME, `backup_paths()` declares it.

### Transparency log and troubleshooting

The provider emits one JSON object per line for initialization, retain, recall,
incremental review, pre-compress, core-tool/core-load, maintenance, discard,
failure, and shutdown events. Each operation
has a `trace_id` and a stable `scope` object (`user_id`, `workspace_id`,
`agent_id`, `session_id`) plus `context` (`backend`, `mode`, `platform`).
Completion events include `status`, `reason`, result count, confidence, and
`latency_ms`. Async prefetch uses a short `query_hash` instead of writing the
query itself.

Initialization reports `provider.initialize.started` followed by
`provider.initialized` only after the client and writer are live; failures use
`provider.initialize.failed`. Shutdown reports `partial` when a worker could
not be joined within the timeout. This keeps the log truthful during startup
and recovery rather than treating an attempted transition as completed.
Accepted retain batches are drained before a clean shutdown. If a slow
enricher exceeds the bounded wait, the provider reports `partial` and refuses
to start a new lifecycle while that worker remains alive; it cannot append an
old turn into a later session.

Example:

```json
{"event":"recall.completed","trace_id":"8f2c1e0a7b91d4c2","scope":{"user_id":"u_42","workspace_id":"main","agent_id":"luminary","session_id":"s_17"},"status":"abstain","reason":"low_confidence_or_ambiguous","memory_count":0,"confidence":0.22,"latency_ms":3.4}
```

The log intentionally omits prompt text, memory content, Telegram tokens, and
LLM API keys. Use it to answer “which scoped operation failed and why”, not to
recover the stored memory itself:

```bash
tail -f ~/.hermes/luminary/luminary.log | jq
rg '"trace_id": "8f2c1e0a7b91d4c2"' ~/.hermes/luminary/luminary.log
jq 'select(.event == "recall.completed" or .event == "recall.failed")' \
  ~/.hermes/luminary/luminary.log
```

Because scope identifiers are included for support correlation, keep the file
under normal local permission and retention controls.

### Activity hook contract

The optional `luminary-activity` hook is registered for `agent:end`. It reports
only persisted active writes, excludes soft-deleted rows, escapes Telegram
Markdown, supports Forum Topic IDs, and advances its cursor only after
Telegram returns `ok: true`. Telegram failure/network errors leave active rows
unchanged so the notification retries; inactive-only ranges are acknowledged
without an empty post.
See [`hermes/hooks/luminary-activity/README.md`](../hermes/hooks/luminary-activity/README.md).

### Directory-install fallback

The provider also ships `plugin.yaml`; users who prefer a directory install can copy
the `luminary_memory/hermes/` package contents to `~/.hermes/plugins/luminary/`.

## Legacy: standalone skill (pre-0.2.1)

Copy `hermes/SKILL.md` into the agent's skills directory:

```bash
mkdir -p ~/.hermes/skills/luminary-memory
cp hermes/SKILL.md ~/.hermes/skills/luminary-memory/SKILL.md
```

## How the agent uses it

1. **Ingest on tool call**, after learning a durable fact (preference, environment detail), call `client.ingest(...)`.
2. **Recall into the system prompt**, before answering, call `client.recall(query)` and inject the top memories as context.
3. **Lifecycle via cron**, schedule `luminary-memory lifecycle` to keep the store clean.
4. **Monitor health**, `luminary-memory health` (or `client.health_score()`) reports store quality; run it in a cron to catch drift.
5. **LLM curation (optional)**, with `ingest_llm` + `auto_maintain`, turns are curated and stale facts pruned automatically.

## Example

```python
from luminary_memory import MemoryClient

client = MemoryClient(db_path="~/.luminary/memory.db")

# durable fact learned this session
client.ingest("user prefers concise responses", tags=["preference"], source="hermes")

# recall relevant context for the current turn
result = client.recall("response style preference", limit=3)
context = "\n".join(m.content for m in result.memories)

client.close()
```

Inject `context` into the agent's system prompt for the current turn.
