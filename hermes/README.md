# luminary-memory, Hermes integration

One-shot installer for using luminary-memory as a first-class Hermes Agent
memory provider: auto-recall every turn, auto-save every session, zero LLM
tokens for retrieval, plus optional write-time curation, a chat-activity hook,
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
| **Provider** | `pip install luminary-memory[hermes]` + `memory.provider: luminary` in Hermes config |
| **Hook** | `luminary-activity`, posts `🌙 Luminary — N memories stored` to chat after committed writes |
| **Skill** | `luminary-memory` skill for agent use |

Then restart your gateway:

```bash
bash ~/.hermes/scripts/restart-bots.sh
```

## Installer options

```bash
bash hermes/install.sh --hook      # hook only
bash hermes/install.sh --skill     # skill only
bash hermes/install.sh --llm       # also enable LLM memory curation (ingest_llm)
bash hermes/install.sh --no-hook --no-skill   # provider only
```

## LLM memory curation (optional but recommended)

By default the provider stores every turn verbatim (zero LLM cost). With LLM
curation enabled, an enricher evaluates each turn and:

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

Any OpenAI-compatible endpoint works. It costs one small LLM call per retained
turn (temperature 0, strict JSON). Gateway responses may be direct
`choices` or wrapped as `data.choices`; both are accepted. If curation fails
or produces no durable summary, the Hermes provider drops that turn rather than
storing a raw transcript as a false fact; the writer never blocks the agent.

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

Results land in the transparency log:
`maintenance {'reviewed': N, 'deleted': N, 'updated': N}`.

For correctness, Hermes sets strict recall/evidence mode and disables
destructive rule replacement. Conflicting claim keys remain visible in audit
history until explicitly superseded.

## Manual install (no script)

```bash
pip install "luminary-memory[hermes]>=0.2.18"

# config.yaml, add under memory:
#   provider: luminary

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
- 💾 **Auto-save**, completed turns persisted automatically; session
  boundaries flush buffered turns.
- 🛠️ **Explicit tools**, `luminary_recall` / `luminary_ingest` /
  `luminary_list` on demand.
- 📋 **Deterministic indicator**, `🌙 Luminary, recalled N memories` in the
  agent UI.
- 🔔 **Chat activity hook**, optional mirror of store activity to your chat.
- 🛡️ **Accuracy guard**, scoped/evidence-aware recall can abstain instead of
  injecting a weak or unrelated memory.
- 🧠 **Skill**, agent-side guidance for store usage.
- 📜 **Transparency log**, `~/.hermes/luminary/luminary.log` records every
  recall, retain, and error (initialize/recall/retain lines), so you can see
  exactly what the provider is doing and whether anything failed.

## Requirements

- Python 3.11+ (Hermes venv recommended)
- Hermes Agent with `memory.provider` support (external providers)

See `docs/hermes-integration.md` in the repo root for the full configuration
table and the legacy standalone-skill path.
