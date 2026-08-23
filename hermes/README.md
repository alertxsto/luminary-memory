# luminary-memory, Hermes integration

One-shot installer for using luminary-memory as a first-class Hermes Agent
memory provider: auto-recall every turn, automatic turn curation, zero LLM
tokens for retrieval, plus optional write-time maintenance, a chat-activity hook,
and a skill.

## Quick install

```bash
git clone https://github.com/alertxsto/luminary-memory.git
cd luminary-memory
bash hermes/install.sh
```

That installs everything:

| Component | What it does |
|-----------|--------------|
| **Provider** | `pip install luminary-memory[hermes]` + Luminary selected and native memory switches disabled in Hermes config |
| **Hook** | `luminary-activity`, posts `🌙 Luminary — N memories stored` to chat after committed writes |
| **Skill** | `luminary-memory` skill for agent use |

Then restart your gateway:

```bash
bash ~/.hermes/scripts/restart-bots.sh
```

The installer checks the public provider capabilities and never compares a
Hermes release number. If Hermes runs from a dedicated interpreter, set
`HERMES_PYTHON` so installation and activation use that same runtime.

## Installer options

```bash
bash hermes/install.sh --hook      # hook only
bash hermes/install.sh --skill     # skill only
bash hermes/install.sh --llm       # also enable LLM memory curation (ingest_llm)
bash hermes/install.sh --no-hook --no-skill   # provider only
```

## LLM memory curation (optional but recommended)

By default the provider does not promote automatic turn transcripts into durable
memory (zero LLM cost). Explicit ingest/core writes still work. With LLM
curation enabled, an enricher evaluates each automatic turn batch and:

- **Drops chit-chat**, greetings, "ok", trivial acknowledgements never reach
  the store (`worth_saving: false`).
- **Stores factual summaries**, kept turns are saved as concise facts (e.g.
  `"Deploy target is the staging cluster."`) instead of raw transcripts.

Enable it (after `bash hermes/install.sh --llm`, edit
`~/.hermes/luminary/config.json`):

```json
{
  "ingest_llm": true,
  "llm_base_url": "https://api.commandcode.ai/provider/v1",
  "llm_model": "deepseek/deepseek-v4-flash",
  "llm_api_key": "<your key>"
}
```

Any OpenAI-compatible endpoint works. It costs one enrichment call plus one
bounded reconciliation call per retained turn when the reviewer is enabled
(temperature 0, strict JSON). Gateway responses may be direct
`choices` or wrapped as `data.choices`; both are accepted. If curation fails
or produces no durable summary, the Hermes provider drops that turn rather than
storing a raw transcript as a false fact; the writer never blocks the agent.

When `ingest_llm` is enabled, the same serialized writer then runs an
incremental self-improvement review. It compares the current turn with a
bounded exact-scope candidate window and can only capture, supersede, or
retract with a candidate ID plus an exact evidence quote from that turn.
Similarity alone never overwrites a claim, and a failed or malformed review
cannot stop later retains.

### Store maintenance (auto_maintain)

With `auto_maintain: true` (plus `ingest_llm: true`), the provider also
reviews the store at every session end, the LLM keeps current facts, updates
changed ones, and **deletes stale, contradicted, or duplicate memories**:

```json
{
  "ingest_llm": true,
  "llm_base_url": "https://api.commandcode.ai/provider/v1",
  "llm_model": "deepseek/deepseek-v4-flash",
  "llm_api_key": "your-key",
  "auto_maintain": true
}
```

Results land in the JSONL transparency log as a scoped
`maintenance.completed` event with `trace_id`, status, counts, and latency.
The log never includes raw prompt or memory content.

For correctness, Hermes sets strict recall/evidence mode and disables
destructive rule replacement. Conflicting claim keys remain visible in audit
history until explicitly superseded.

Luminary is the authoritative memory surface when `memory.provider: luminary` is
active together with:

```yaml
memory:
  provider: luminary
  memory_enabled: false
  user_profile_enabled: false
```

Hermes' native files remain on disk for compatibility, but their normal prompt
and tool surfaces are disabled by those existing switches. They are not
mirrored into Luminary or silently merged as a second source of truth. If a
provider cannot be discovered or loaded, use Hermes' provider-availability
diagnostic; do not re-enable native memory as an implicit fallback.

The installer does not edit Hermes source. It only selects the public provider
entry point and disables Hermes' existing native memory switches so there is a
single persistent surface. Future Hermes upgrades therefore do not require a
Luminary patch to be merged or rebased. Keep the provider selection and the
native switches in `config.yaml`, then restart the gateway after an upgrade.

Runtime context remains split into three non-competing surfaces: DB-backed
`core` rows loaded every session, evidence-aware durable recall for the current
query, and a bounded untrusted exact-session episode fallback used only when
durable recall has no usable result. The episode fallback preserves active
conversation scope; it is not durable semantic memory and never searches other
sessions.

If the installed Hermes cannot discover the `MemoryProvider` entry point,
setup must stop with a visible compatibility error. Do not copy Luminary into
Hermes' source tree or add a private import as a workaround.

If an older store contains imported authority snapshots or uncurated Hermes
transcripts, inspect and optionally apply the migration helper before relying
on automatic writes:

```bash
python scripts/repair_memory_authority.py \
  --db-path ~/.hermes/luminary/memory.db
python scripts/repair_memory_authority.py \
  --db-path ~/.hermes/luminary/memory.db --apply
```

The dry run is read-only. Applying creates a SQLite backup, archives matching
rows, and appends audit events; it does not delete rows or classify content by
language.

## Manual install (no script)

```bash
pip install "luminary-memory[hermes]"

# config.yaml, add under memory:
#   provider: luminary
#   memory_enabled: false
#   user_profile_enabled: false

# hook
mkdir -p ~/.hermes/hooks/luminary-activity
cp hermes/hooks/luminary-activity/handler.py ~/.hermes/hooks/luminary-activity/
cp hermes/hooks/luminary-activity/HOOK.yaml ~/.hermes/hooks/luminary-activity/

# skill
mkdir -p ~/.hermes/skills/luminary-memory
cp hermes/SKILL.md ~/.hermes/skills/luminary-memory/SKILL.md
```

## What you get

- 🌙 **Auto-recall**, relevant memories retrieved in the background and
  injected into agent context every turn.
- 💾 **Auto-retain + reconcile**, completed turns are queued and session
  boundaries flush the queue; only curated summaries and evidence-backed
  incremental decisions become durable automatic memories.
- 🛠️ **Explicit tools**, `luminary_recall` / `luminary_ingest` /
  `luminary_list` on demand.
- 📋 **Deterministic indicator**, `🌙 Luminary, recalled N memories` in the
  agent UI.
- 🔔 **Chat activity hook**, optional mirror of store activity to your chat.
- 🛡️ **Accuracy guard**, scoped/evidence-aware recall can abstain instead of
  injecting a weak or unrelated memory.
- 🧠 **Skill**, agent-side guidance for store usage.
- 📜 **Transparency log**, `~/.hermes/luminary/luminary.log` records JSONL
  initialization/recall/retain/review/pre-compress/core/maintenance events with
  scope, `trace_id`, status/reason, counts, confidence, and latency, so you
  can see exactly what the provider is doing and correlate failures without
  logging memory content. Accepted writes are drained before the writer closes.
  A partial shutdown is reported when a worker cannot be joined within the
  bounded wait; Luminary refuses to start a new lifecycle while that worker is
  still alive, so a slow curation result cannot leak into a later session.

## Requirements

- Python 3.11+ (Hermes venv recommended)
- Hermes Agent with `memory.provider` support (external providers)

See `docs/hermes-integration.md` in the repo root for the full configuration
table and the legacy standalone-skill path.
