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
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger("luminary-activity")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("LUMINARY_HOOK_CHAT_ID") or os.getenv("TELEGRAM_HOME_CHANNEL", "")
DB_PATH = os.getenv(
    "LUMINARY_DB_PATH",
    str(Path.home() / ".hermes" / "luminary" / "memory.db"),
)
LOG_FILE = Path.home() / ".hermes" / "hooks" / "luminary-activity" / "hook.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
STATE_FILE = LOG_FILE.parent / "state.json"

logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def _escape_md(text: str) -> str:
    """Escape Telegram Markdown special characters to prevent API formatting errors."""
    # Escape backslash first to avoid corrupting subsequent escape sequences
    text = text.replace("\\", "\\\\")
    for ch in ("_", "*", "`", "[", "]", "(", ")"):
        text = text.replace(ch, f"\\{ch}")
    return text


def _load_hermes_env() -> dict[str, str]:
    """Parse ~/.hermes/.env as fallback if env vars are not in os.environ."""
    env_file = Path.home() / ".hermes" / ".env"
    if not env_file.exists():
        return {}
    res: dict[str, str] = {}
    try:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                res[k.strip()] = v.strip().strip("'\"")
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("failed to read .env file: %s", exc)
    return res


def _last_shown_id() -> int:
    try:
        if STATE_FILE.exists():
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            return int(data.get("last_id", 0))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("could not parse state file: %s", exc)
    return 0


def _set_last_shown_id(mid: int) -> None:
    try:
        STATE_FILE.write_text(json.dumps({"last_id": mid}), encoding="utf-8")
    except OSError as exc:
        logger.warning("could not write state file: %s", exc)


def _send_telegram_request(url: str, payload_data: dict[str, str | int]) -> None:
    payload = json.dumps(payload_data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(req, timeout=10).read()


def _post(text: str) -> None:
    token = BOT_TOKEN
    chat = CHAT_ID
    thread = os.getenv("LUMINARY_HOOK_THREAD_ID") or os.getenv("TELEGRAM_HOME_CHANNEL_THREAD_ID", "")
    if not token or not chat:
        file_env = _load_hermes_env()
        token = token or file_env.get("TELEGRAM_BOT_TOKEN", "")
        chat = chat or file_env.get("LUMINARY_HOOK_CHAT_ID") or file_env.get("TELEGRAM_HOME_CHANNEL", "")
        thread = thread or file_env.get("LUMINARY_HOOK_THREAD_ID") or file_env.get("TELEGRAM_HOME_CHANNEL_THREAD_ID", "")
    if not token or not chat:
        logger.warning("luminary-activity skipped: token/chat not set")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload_data: dict[str, str | int] = {
        "chat_id": chat,
        "text": text,
        "parse_mode": "Markdown",
    }
    if thread and thread.isdigit():
        payload_data["message_thread_id"] = int(thread)

    try:
        _send_telegram_request(url, payload_data)
    except urllib.error.HTTPError as exc:
        # If Telegram rejects markdown formatting with 400 Bad Request, retry as plain text
        if exc.code == 400 and "parse_mode" in payload_data:
            logger.warning("Telegram markdown parse error, falling back to plain text: %s", exc)
            try:
                payload_data.pop("parse_mode", None)
                _send_telegram_request(url, payload_data)
            except Exception:
                logger.exception("failed to post activity in plain text fallback")
        else:
            logger.exception("failed to post activity")
    except Exception:
        logger.exception("failed to post activity")


def _recent_activity(seconds: int = 30) -> str | None:
    """Return a status line for *new* memories since last post (no repeats)."""
    db = DB_PATH
    if not Path(db).exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        last_id = _last_shown_id()
        # First run after fix: only show the single newest to avoid spamming history
        if last_id == 0:
            row = conn.execute("SELECT MAX(id) as max_id FROM memories").fetchone()
            max_id = int(row["max_id"] or 0) if row else 0
            if max_id == 0:
                conn.close()
                return None
            all_rows = conn.execute(
                "SELECT * FROM memories WHERE id = ?",
                (max_id,),
            ).fetchall()
        else:
            all_rows = conn.execute(
                "SELECT * FROM memories WHERE id > ? ORDER BY id ASC",
                (last_id,),
            ).fetchall()
            if not all_rows:
                conn.close()
                return None
        n_new = len(all_rows)
        noun = "memory" if n_new == 1 else "memories"
        lines = [f"🌙 Luminary — {n_new} {noun} stored"]
        display_rows = all_rows[:3]
        for r in display_rows:
            content = str(r["content"] or "").replace("\n", " ").strip()
            if len(content) > 120:
                content = content[:120].rsplit(" ", 1)[0] + "…"
            if content:
                row_keys = r.keys()
                imp = float(r["importance"] or 0.0) if "importance" in row_keys else 0.0
                tags = str(r["tags"] or "") if "tags" in row_keys else ""
                is_rule = imp >= 0.85 or "core" in tags or "rule" in tags
                icon = "📌" if is_rule else "•"
                lines.append(f"  {icon} {_escape_md(content)}")
        if n_new > 3:
            lines.append(f"  ... (+{n_new - 3} more)")
        max_shown = max(int(r["id"]) for r in all_rows)
        _set_last_shown_id(max_shown)
        conn.close()
        return "\n".join(lines)
    except Exception:
        logger.exception("activity read failed")
        return None


def handle(event_type: str, context: dict) -> None:
    """Hook entry point: surface luminary activity on agent:end."""
    if event_type != "agent:end":
        return
    line = _recent_activity(seconds=30)
    if line:
        _post(line)
