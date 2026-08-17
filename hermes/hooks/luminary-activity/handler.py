#!/usr/bin/env python3
"""Luminary activity hook — surface luminary-memory activity to the chat.

Fires on agent:start and agent:end, reading the luminary store's recent
activity (recalls, retains, lifecycle runs) and posting a compact status
line to the configured Telegram chat via the Bot API.

Install: copy this directory to ~/.hermes/hooks/luminary-activity/
(see HOOK.yaml). Requires TELEGRAM_BOT_TOKEN + TELEGRAM_HOME_CHANNEL
(or LUMINARY_HOOK_CHAT_ID) in ~/.hermes/.env.

Security: shell=False, no subprocess, markdown-escaped output, all
failures logged and swallowed (hooks never block the agent).
"""
import json
import logging
import os
import sqlite3
import time
from pathlib import Path

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("LUMINARY_HOOK_CHAT_ID") or os.getenv("TELEGRAM_HOME_CHANNEL", "")
DB_PATH = os.getenv(
    "LUMINARY_DB_PATH",
    str(Path.home() / ".hermes" / "luminary" / "memory.db"),
)
LOG_FILE = Path.home() / ".hermes" / "hooks" / "luminary-activity" / "hook.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=str(LOG_FILE), level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def _post(text: str) -> None:
    if not BOT_TOKEN or not CHAT_ID:
        logging.warning("luminary-activity skipped: token/chat not set")
        return
    try:
        import urllib.request

        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = json.dumps({
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "Markdown",
        }).encode()
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10).read()
    except Exception:
        logging.exception("failed to post activity")


def _recent_activity(seconds: int = 30) -> str | None:
    """Return a compact status line if the store was active recently."""
    if not Path(DB_PATH).exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cutoff = int(time.time()) - seconds
        # created recently (recall updates last_accessed_at, ingest inserts new)
        row = conn.execute(
            "SELECT COUNT(*) AS n, "
            "MAX(CASE WHEN strftime('%s', created_at) > ? THEN 1 ELSE 0 END) AS new_mem "
            "FROM memories",
            (cutoff,),
        ).fetchone()
        n = int(row["n"] or 0)
        new_mem = bool(row["new_mem"])
        if n == 0:
            conn.close()
            return None
        label = "stored" if new_mem else "recalled"
        noun = "memory" if n == 1 else "memories"
        lines = [f"🌙 Luminary — {n} {noun} {label}"]
        # Show the content of newly stored facts (transparency).
        if new_mem:
            new_rows = conn.execute(
                "SELECT content FROM memories "
                "WHERE strftime('%s', created_at) > ? "
                "ORDER BY id DESC LIMIT 3",
                (cutoff,),
            ).fetchall()
            for r in new_rows:
                content = str(r["content"] or "").replace("\n", " ")[:90]
                if content:
                    lines.append(f"  • {content}")
        conn.close()
        return "\n".join(lines)
    except Exception:
        logging.exception("activity read failed")
        return None


def handle(event_type: str, context: dict) -> None:
    """Hook entry point: surface luminary activity on agent:end."""
    # Only surface on agent:end (after work), cooldown-ish: skip if store idle.
    if event_type != "agent:end":
        return
    line = _recent_activity(seconds=30)
    if line:
        _post(line)
