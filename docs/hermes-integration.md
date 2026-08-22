# Hermes integration

Use luminary-memory as a first-class **memory provider** for [Hermes Agent](https://github.com/NousResearch/hermes-agent). Since v0.2.1 the recommended path is the pip entry-point provider (`luminary`), which replaces the standalone-skill approach described below. The current provider is `0.2.18` and uses the strict accuracy path: scoped candidates, evidence-required results, abstention, and non-destructive rule updates.

## Preferred: install the provider (v0.2.1+)

`luminary-memory` ships a Hermes `MemoryProvider` registered through the
`hermes_agent.memory_providers` entry-point group.

```bash
pip install luminary-memory>=0.2.1
hermes memory setup luminary
```

Then set in `config.yaml`:

```yaml
memory:
  provider: luminary
```

On the next session Hermes will:

- **Auto-recall every turn**, the current user message is used to recall relevant memories from the local store, injected as a `# Luminary Memory (persistent cross-session context)` reference block. The block is filtered by session/user/workspace/agent scope and may explicitly abstain.
- **Core rules auto-load every session**, durable rules tagged `core` (the DB-backed `MEMORY.md`) are always in the system prompt, independent of query match. All other memories come from query recall, merged under anti-duplication so nothing appears twice.
- **Auto-save every session**, completed turns are persisted under session lineage tags (`session:<id>`, `parent:<id>`, `platform:<p>`, `agent:<identity>`) and ownership fields.
- **Expose explicit tools**, `luminary_recall` / `luminary_ingest` / `luminary_list` are registered for the model in `tools` and `hybrid` modes.
- **Report a deterministic indicator**, a `🌙 Luminary, recalled N memories` status line appears whenever recall injected context.

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
| `auto_retain` | `true` | Enable per-turn auto-save |
| `retain_every_n_turns` | `1` | Batch N turns into one store write |
| `ingest_llm` | `false` | **LLM memory curation on retain**, the enricher decides whether a turn is worth saving (drops chit-chat) and stores a factual summary instead of the raw transcript |
| `llm_base_url` | `""` | OpenAI-compatible endpoint for the enricher (e.g. `https://api.cline.bot/v1`, `https://api.commandcode.ai/provider/v1`, Groq, Ollama) |
| `llm_model` | `""` | Enricher model (e.g. `deepseek/deepseek-v4-flash`) |
| `llm_api_key` | `""` | Enricher API key (settable as a secret field in the dashboard) |
| `llm_timeout` | `60` | Enricher request timeout (seconds) |
| `recall_indicator` | `true` | Show `🌙 Luminary, recalled N memories` |
| `retain_indicator` | `true` | Show `🌙 Luminary, memory saved` |
| `retain_user_prefix` | `User` | Prefix used when formatting retained user turns |
| `retain_assistant_prefix` | `Assistant` | Prefix used when formatting retained assistant turns |
| `extract_on_session_end` | `false` | Run an extraction pass at session end (requires `ingest_llm`) |
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
never mentions "tabel" still gets the table rule from the very first prompt.

```
Core memory (auto-loaded every session):
- <rule 1>
- <rule 2>
```

Managed via tools (`luminary_core_add` / `luminary_core_remove` /
`luminary_core_list`) or by ingesting with the `core` tag. The block is capped
by `core_top_n` memories and `core_budget` characters. Core memories are
pinned (importance ≥ 0.9, exempt from prune/consolidate).

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

- **`worth_saving`**, `false` drops the turn entirely (chit-chat, greetings,
  trivial acknowledgements never reach the store).
- **`summary`**, a concise factual summary in the turn's language that
  becomes the stored content, instead of the raw `User: ... / Assistant: ...`
  transcript.
- **`entities` / `tags`**, attached as metadata/tags for richer recall.

Without `ingest_llm` (default), turns are stored verbatim, zero LLM cost.

### Rule hygiene (v0.2.11+)

Two safeguards keep rules accurate and non-contradictory:

- **Rule keywords are checked only against the LLM-curated summary**, never
  the raw transcript. A turn that merely *mentions* a keyword (e.g. a
  conversation that says "PLAN") is not pinned as a rule — only a distilled
  fact that reads like an instruction gets `importance 0.9`+.
- **Raw transcripts are dropped when curation yields no summary**: with
  `ingest_llm: true`, a turn whose enrichment fails or returns nothing durable
  is not stored verbatim (avoids polluting the store with conversation noise).
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
└── luminary.log         # transparency log (initialize/recall/retain/errors)
```

The store is profile-scoped and picked up by `hermes backup` automatically. If you
override `db_path` to a location outside HERMES_HOME, `backup_paths()` declares it.

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
