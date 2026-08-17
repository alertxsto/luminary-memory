# Luminary Activity Hook

Surfaces what luminary-memory is doing — recalls, stores, lifecycle — as a
compact status line in your chat, so you can *see* the memory layer working.

```
🌙 Luminary — 12 memories recalled
🌙 Luminary — 3 memories stored
```

## Install

```bash
# 1. copy the hook into your Hermes hooks directory
mkdir -p ~/.hermes/hooks/luminary-activity
cp hermes/hooks/luminary-activity/handler.py ~/.hermes/hooks/luminary-activity/
cp hermes/hooks/luminary-activity/HOOK.yaml ~/.hermes/hooks/luminary-activity/

# 2. env vars (in ~/.hermes/.env)
echo "LUMINARY_HOOK_CHAT_ID=<your chat id>" >> ~/.hermes/.env
# TELEGRAM_BOT_TOKEN + TELEGRAM_HOME_CHANNEL are usually already set

# 3. restart your Hermes gateway
bash ~/.hermes/scripts/restart-bots.sh
```

## What it shows

- **agent:end** — after a turn, if the luminary store was touched in the last
  30s (a recall updated access timestamps, or an ingest added a memory), a
  one-line status is posted.

## Configuration (env vars)

| Var | Default | Description |
|-----|---------|-------------|
| `LUMINARY_HOOK_CHAT_ID` | `TELEGRAM_HOME_CHANNEL` | Chat to post activity to |
| `LUMINARY_DB_PATH` | `~/.hermes/luminary/memory.db` | Luminary store to watch |

## Notes

- **Non-blocking** — hooks never block the agent; failures are logged to
  `~/.hermes/hooks/luminary-activity/hook.log` and swallowed.
- **Quiet by default** — only posts when the store was actually active.
- The provider's built-in indicators (`recall_indicator`, `retain_indicator`,
  `recall_status()`) already surface a `🌙` status line in the agent UI; this
  hook is the opt-in *chat* mirror for group/DM workflows.
