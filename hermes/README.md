# luminary-memory — Hermes integration

One-shot installer for using luminary-memory as a first-class Hermes Agent
memory provider: auto-recall every turn, auto-save every session, zero LLM
tokens per turn — plus an optional chat-activity hook and a skill.

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
| **Hook** | `luminary-activity` — posts `🌙 Luminary — N memories recalled/stored` to chat |
| **Skill** | `luminary-memory` skill for agent use |

Then restart your gateway:

```bash
bash ~/.hermes/scripts/restart-bots.sh
```

## Installer options

```bash
bash hermes/install.sh --hook      # hook only
bash hermes/install.sh --skill     # skill only
bash hermes/install.sh --no-hook --no-skill   # provider only
```

## Manual install (no script)

```bash
pip install "luminary-memory[hermes]>=0.2.1"

# config.yaml — add under memory:
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

- 🌙 **Auto-recall** — relevant memories retrieved in the background and
  injected into agent context every turn.
- 💾 **Auto-save** — completed turns persisted automatically; session
  boundaries flush buffered turns.
- 🛠️ **Explicit tools** — `luminary_recall` / `luminary_ingest` /
  `luminary_list` on demand.
- 📋 **Deterministic indicator** — `🌙 Luminary — recalled N memories` in the
  agent UI.
- 🔔 **Chat activity hook** — optional mirror of store activity to your chat.
- 🧠 **Skill** — agent-side guidance for store usage.

## Requirements

- Python 3.11+ (Hermes venv recommended)
- Hermes Agent with `memory.provider` support (external providers)

See `docs/hermes-integration.md` in the repo root for the full configuration
table and the legacy standalone-skill path.
