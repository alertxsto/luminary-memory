# Luminary Activity Hook

Surfaces newly stored luminary-memory facts as a compact status line in your
Telegram chat, so you can see exactly what the memory layer accepted.

```
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

- **agent:end** — after a turn, if new memories were stored since the last
  successfully delivered notification, a one-line status is posted.
- The hook tracks the highest delivered memory ID. If Telegram or the network
  fails, the cursor does not advance and the same activity is retried on the
  next `agent:end` event.
- Recall status is surfaced by the provider/CLI separately; this Telegram hook
  reports only persisted writes so its wording stays factual.

Delivery contract:

```json
{
  "chat_id": "12345",
  "text": "🌙 Luminary — 1 memory stored\n  • Deploy target is staging",
  "parse_mode": "Markdown",
  "message_thread_id": 42
}
```

`message_thread_id` is included only when `LUMINARY_HOOK_THREAD_ID` or
`TELEGRAM_HOME_CHANNEL_THREAD_ID` is configured. The hook advances its cursor
only after Telegram returns `{"ok": true}`; `ok:false`, HTTP errors, and
network errors leave the row pending for the next `agent:end`.

The equivalent local CLI view is:

```bash
luminary-memory activity --db-path ~/.hermes/luminary/memory.db
```

Example:

```text
🌙 Luminary — 2 recent memories stored
  📌 #12 ALWAYS verify tests before release
    tags: core, rule · source: hermes
  • #11 Deploy target is staging
    tags: deploy · source: cli
```

## Configuration (env vars)

| Var | Default | Description |
|-----|---------|-------------|
| `LUMINARY_HOOK_CHAT_ID` | `TELEGRAM_HOME_CHANNEL` | Chat to post activity to |
| `LUMINARY_HOOK_THREAD_ID` | `TELEGRAM_HOME_CHANNEL_THREAD_ID` | Optional Telegram Forum Topic ID |
| `LUMINARY_DB_PATH` | `~/.hermes/luminary/memory.db` | Luminary store to watch |

## Notes

- **Non-blocking** — hooks never block the agent; failures are logged to
  `~/.hermes/hooks/luminary-activity/hook.log` and swallowed.
- **Quiet by default** — only posts when the store was actually active.
- **Delivery-safe** — state advances only after Telegram accepts the message.
- The provider's built-in indicators (`recall_indicator`, `retain_indicator`,
  `recall_status()`) already surface a `🌙` status line in the agent UI; this
  hook is the opt-in *chat* mirror for group/DM workflows.
