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

- **Auto-recall every turn** — the current user message is used to recall relevant memories from the local store, injected as a `# Luminary Memory (persistent cross-session context)` block.
- **Auto-save every session** — completed turns are persisted under session lineage tags (`session:<id>`, `parent:<id>`, `platform:<p>`, `agent:<identity>`).
- **Expose explicit tools** — `luminary_recall` / `luminary_ingest` / `luminary_list` are registered for the model in `tools` and `hybrid` modes.
- **Report a deterministic indicator** — a `🌙 Luminary — recalled N memories` status line appears whenever recall injected context.

### Configuration

The provider reads `$HERMES_HOME/luminary/config.json` (created on first save with
`0600` permissions). Key settings:

| Key | Default | Meaning |
|-----|---------|---------|
| `mode` | `hybrid` | `context` (auto-inject only) · `tools` (tool-only) · `hybrid` (both) |
| `db_path` | `""` | Override store path; `""` = `$HERMES_HOME/luminary/memory.db` |
| `backend` | `sqlite` | `sqlite` or `pgvector` |
| `recall_limit` | `10` | Top-N memories per recall |
| `token_budget` | `2048` | Recall context budget |
| `auto_recall` | `true` | Enable per-turn background recall |
| `recall_sync` | `false` | Synchronous (live) recall instead of warm prefetch |
| `auto_retain` | `true` | Enable per-turn auto-save |
| `retain_every_n_turns` | `1` | Batch N turns into one store write |
| `ingest_llm` | `false` | **LLM memory curation on retain** — the enricher decides whether a turn is worth saving (drops chit-chat) and stores a factual summary instead of the raw transcript |
| `llm_base_url` | `""` | OpenAI-compatible endpoint for the enricher (e.g. `https://api.commandcode.ai/provider/v1`) |
| `llm_model` | `""` | Enricher model (e.g. `deepseek/deepseek-v4-flash`) |
| `llm_api_key` | `""` | Enricher API key |
| `llm_timeout` | `60` | Enricher request timeout (seconds) |
| `recall_indicator` | `true` | Show `🌙 Luminary — recalled N memories` |
| `retain_indicator` | `true` | Show `🌙 Luminary — memory saved` |
| `auto_maintain` | `false` | **LLM store review at session end** — keeps/updates/deletes stale, contradicted, or duplicate facts (requires `ingest_llm`) |

### LLM memory curation (v0.2.2+)

With `ingest_llm: true`, every retained turn is sent to the enricher, which
returns:

- **`worth_saving`** — `false` drops the turn entirely (chit-chat, greetings,
  trivial acknowledgements never reach the store).
- **`summary`** — a concise factual summary in the turn's language that
  becomes the stored content, instead of the raw `User: ... / Assistant: ...`
  transcript.
- **`entities` / `tags`** — attached as metadata/tags for richer recall.

Without `ingest_llm` (default), turns are stored verbatim — zero LLM cost.

### Store layout

```
$HERMES_HOME/luminary/
├── config.json          # provider config — 0600
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

1. **Ingest on tool call** — after learning a durable fact (preference, environment detail), call `client.ingest(...)`.
2. **Recall into the system prompt** — before answering, call `client.recall(query)` and inject the top memories as context.
3. **Lifecycle via cron** — schedule `luminary-memory lifecycle` to keep the store clean.

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
