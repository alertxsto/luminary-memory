# Hermes integration

Use luminary-memory as a first-class **memory provider** for [Hermes Agent](https://github.com/NousResearch/hermes-agent). Since v0.2.1 the recommended path is the pip entry-point provider (`luminary`), which replaces the standalone-skill approach described below.

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

- **Auto-recall every turn**, the current user message is used to recall relevant memories from the local store, injected as a `# Luminary Memory (persistent cross-session context)` block.
- **Inject persistent context every turn**, the top-N most important memories (durable rules, critical facts) are always present in context — independent of whether the query matches them. This fixes the "agent forgot the rule" failure mode: the system prompt is byte-stable for prompt caching, so per-turn prefetch carries the rules. Anti-duplication ensures nothing appears twice.
- **Auto-save every session**, completed turns are persisted under session lineage tags (`session:<id>`, `parent:<id>`, `platform:<p>`, `agent:<identity>`).
- **Expose explicit tools**, `luminary_recall` / `luminary_ingest` / `luminary_list` are registered for the model in `tools` and `hybrid` modes.
- **Report a deterministic indicator**, a `🌙 Luminary, recalled N memories` status line appears whenever recall injected context.

### Configuration

The provider reads `$HERMES_HOME/luminary/config.json` (created on first save with
`0600` permissions). Key settings:

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
| `llm_base_url` | `""` | OpenAI-compatible endpoint for the enricher (e.g. `https://api.commandcode.ai/provider/v1`) |
| `llm_model` | `""` | Enricher model (e.g. `deepseek/deepseek-v4-flash`) |
| `llm_api_key` | `""` | Enricher API key |
| `llm_timeout` | `60` | Enricher request timeout (seconds) |
| `recall_indicator` | `true` | Show `🌙 Luminary, recalled N memories` |
| `retain_indicator` | `true` | Show `🌙 Luminary, memory saved` |
| `retain_user_prefix` | `User` | Prefix used when formatting retained user turns |
| `retain_assistant_prefix` | `Assistant` | Prefix used when formatting retained assistant turns |
| `auto_maintain` | `false` | **LLM store review at session end**, keeps/updates/deletes stale, contradicted, or duplicate facts (requires `ingest_llm`) |
| `consolidate_semantic` | `true` | **Embedding-cosine consolidation** in lifecycle, merges paraphrases (falls back to Jaccard when embeddings are degenerate/missing) |
| `importance_auto` | `true` | **Auto importance estimation**, scores each memory from access, recency, and graph centrality on ingest/lifecycle |
| `context_top_n` | `8` | Top-N important memories injected into context every turn (persistent context) |
| `context_budget` | `2000` | Max tokens of persistent context per turn |
| `context_min_importance` | `0.0` | Only inject memories at/above this importance into persistent context |
| `importance_recall_boost` | `1.0` | Ranking bonus multiplier for memories at importance ≥ 0.8, so durable rules surface in recall |
| `core_tag` | `core` | Tag marking DB-backed core memories — always auto-loaded into the system prompt every session (like MEMORY.md) |
| `core_top_n` | `12` | Max core memories injected into the system prompt |
| `core_budget` | `8000` | Max characters of core memory injected into the system prompt |

### Core memory (DB-backed, v0.2.13+)

Luminary equivalent of Hermes' native `MEMORY.md`, but stored in the
database. Memories tagged `core` are **auto-loaded into the system prompt
every session**, before persistent context and recall — so a new session that
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
a content source. Core and persistent context both add to it, and the recall
block skips anything already injected. Dedup is now **content-level** as well
as id-level: a memory whose text is already in the core block is skipped by
persistent context and recall even when it has a different id — so a rule
stored both as `core` and as a plain high-importance memory appears in context
**exactly once** per turn.

### Persistent context (v0.2.11+)

The system prompt is byte-stable for the life of a conversation (Hermes
prompt caching is sacred), so a memory ingested mid-session would never reach
the model through `system_prompt_block()` alone. The provider instead builds
the persistent-context block **every turn** in `prefetch()`:

```
Key memories:
- <top-N by importance, capped at context_budget>
```

Merged with the query-recall block under anti-duplication: memories already
injected by persistent context are skipped by recall, so nothing appears
twice in one turn's context. Memory ids injected are tracked per turn
(`_injected_ids`), never accumulated across turns.

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
- **Rule auto-replace (anti-contradiction)**: ingesting a rule semantically
  similar to an existing one (embedding cosine ≥ `rule_auto_replace_threshold`,
  default 0.85) replaces it in place instead of stacking conflicting rows
  (e.g. "never use tables" vs "always use tables").
- **Rule pinning**: memories at importance ≥ 0.9 are pinned — never pruned by
  importance or the `max_memories` cap, and never deleted by consolidation.

### Store layout

```
$HERMES_HOME/luminary/
├── config.json          # provider config, 0600
├── memory.db            # SQLite store (created by MemoryClient)
└── luminary.log         # transparency log (initialize/recall/retain/errors)
```

The store is profile-scoped and picked up by `hermes backup` automatically. If you
override `db_path` to a location outside HERMES_HOME, `backup_paths()` declares it.

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
