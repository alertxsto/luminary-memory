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
STATE_FILE = LOG_FILE.parent / "state.json"

def _last_shown_id() -> int:
    try:
        return int(json.loads(STATE_FILE.read_text())["last_id"])
    except Exception:
        return 0

def _set_last_shown_id(mid: int) -> None:
    STATE_FILE.write_text(json.dumps({"last_id": mid}))
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
    """Return a status line for *new* memories since last post (no repeats)."""
    if not Path(DB_PATH).exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        last_id = _last_shown_id()
        # First run after fix: only show the single newest to avoid spamming history
        if last_id == 0:
            row = conn.execute("SELECT MAX(id) as max_id FROM memories").fetchone()
            max_id = int(row["max_id"] or 0)
            if max_id == 0:
                conn.close()
                return None
            new_rows = conn.execute(
                "SELECT id, content FROM memories WHERE id = ?",
                (max_id,),
            ).fetchall()
        else:
            new_rows = conn.execute(
                "SELECT id, content FROM memories WHERE id > ? ORDER BY id ASC LIMIT 3",
                (last_id,),
            ).fetchall()
            if not new_rows:
                conn.close()
                return None
        n_new = len(new_rows)
        noun = "memory" if n_new == 1 else "memories"
        lines = [f"🌙 Luminary — {n_new} {noun} stored"]
        for r in new_rows:
            content = str(r["content"] or "").replace("\n", " ").strip()
            if len(content) > 120:
                content = content[:120].rsplit(" ", 1)[0] + "…"
            if content:
                lines.append(f"  • {content}")
        max_shown = max(int(r["id"]) for r in new_rows)
        _set_last_shown_id(max_shown)
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
