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

The hook is not a second memory authority. It reads active durable rows from
the same SQLite store as the provider and does not report raw session episodes,
recall hits, rejected curation, or rows that were soft-deleted.

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

## Runtime path and cursor

The handler resolves the active Hermes home from hook context, `HERMES_HOME`,
or `~/.hermes`. It resolves the database in this order: an explicit hook
context path, `LUMINARY_DB_PATH`, the provider's
`$HERMES_HOME/luminary/config.json` `db_path`, then the default
`$HERMES_HOME/luminary/memory.db`. Relative configured paths are resolved from
that Hermes home so the hook follows the provider profile instead of silently
opening a different working-directory database.

The delivery cursor is stored beside the hook at
`$HERMES_HOME/hooks/luminary-activity/state.json`, with a sibling lock file.
The cursor advances only after Telegram returns a boolean `{"ok": true}`;
malformed JSON, `ok:false`, HTTP errors, and network errors leave the range
pending for retry. Each Hermes home therefore has an independent cursor.

## Configuration (env vars)

| Var | Default | Description |
|-----|---------|-------------|
| `LUMINARY_HOOK_CHAT_ID` | `TELEGRAM_HOME_CHANNEL` | Chat to post activity to |
| `LUMINARY_HOOK_THREAD_ID` | `TELEGRAM_HOME_CHANNEL_THREAD_ID` | Optional Telegram Forum Topic ID |
| `LUMINARY_DB_PATH` | unset | Explicit Luminary store to watch; otherwise provider config/default resolution is used |

## Notes

- **Non-blocking** — hooks never block the agent; failures are logged to
  `~/.hermes/hooks/luminary-activity/hook.log` and swallowed.
- **Quiet by default** — only posts when the store was actually active.
- **Delivery-safe** — state advances only after Telegram accepts the message.
- The provider's built-in indicators (`recall_indicator`, `retain_indicator`,
  `recall_status()`) already surface a `🌙` status line in the agent UI; this
  hook is the opt-in *chat* mirror for group/DM workflows.
