#!/usr/bin/env python3
"""Luminary activity hook — surface stored-memory activity to Telegram.

Fires on ``agent:end``, reads memories that have not been acknowledged by the
hook yet, and posts a compact status line to the configured Telegram chat via
the Bot API. The acknowledgement cursor advances only after Telegram accepts
the message, so a transient delivery failure is retried on the next event.

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
from contextlib import contextmanager
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None

logger = logging.getLogger("luminary-activity")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("LUMINARY_HOOK_CHAT_ID") or os.getenv("TELEGRAM_HOME_CHANNEL", "")
THREAD_ID = os.getenv("LUMINARY_HOOK_THREAD_ID") or os.getenv("TELEGRAM_HOME_CHANNEL_THREAD_ID", "")
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
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("could not parse state file: %s", exc)
    return 0


@contextmanager
def _cursor_lock():
    """Serialize read -> send -> cursor-advance across hook processes."""
    lock_file = STATE_FILE.with_name(f"{STATE_FILE.name}.lock")
    try:
        with open(lock_file, "a+", encoding="utf-8") as fh:
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except OSError:
        # Hooks must never block agent completion because a local lock file is
        # unavailable. The atomic state replacement still protects the write.
        yield


def _set_last_shown_id(mid: int) -> None:
    tmp_file = STATE_FILE.with_name(f"{STATE_FILE.name}.tmp")
    try:
        with open(tmp_file, "w", encoding="utf-8") as fh:
            json.dump({"last_id": int(mid)}, fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_file, STATE_FILE)
    except OSError as exc:
        logger.warning("could not write state file: %s", exc)
        try:
            tmp_file.unlink(missing_ok=True)
        except OSError:
            pass


def _send_telegram_request(url: str, payload_data: dict[str, str | int]) -> bool:
    payload = json.dumps(payload_data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        raw = response.read()
    # Telegram may return HTTP 200 with {"ok": false}. Treat that, malformed
    # JSON, and non-boolean success responses as delivery failures so the
    # activity cursor is not advanced prematurely. Telegram's Bot API always
    # returns a JSON envelope; accepting arbitrary HTTP-200 proxy bodies would
    # silently lose activity when the request was not actually delivered.
    try:
        response = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else str(raw))
        if not isinstance(response, dict) or response.get("ok") is not True:
            logger.warning("Telegram API rejected activity message: %s", response)
            return False
    except (TypeError, ValueError, UnicodeDecodeError):
        logger.warning("Telegram API returned a malformed response body")
        return False
    return True


def _post(text: str) -> bool:
    token = BOT_TOKEN
    chat = CHAT_ID
    thread = THREAD_ID
    if not token or not chat:
        file_env = _load_hermes_env()
        token = token or file_env.get("TELEGRAM_BOT_TOKEN", "")
        chat = chat or file_env.get("LUMINARY_HOOK_CHAT_ID") or file_env.get("TELEGRAM_HOME_CHANNEL", "")
        thread = thread or file_env.get("LUMINARY_HOOK_THREAD_ID") or file_env.get("TELEGRAM_HOME_CHANNEL_THREAD_ID", "")
    if not token or not chat:
        logger.warning("luminary-activity skipped: token/chat not set")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload_data: dict[str, str | int] = {
        "chat_id": chat,
        "text": text,
        "parse_mode": "Markdown",
    }
    if thread and thread.isdigit():
        payload_data["message_thread_id"] = int(thread)

    try:
        return _send_telegram_request(url, payload_data)
    except urllib.error.HTTPError as exc:
        # If Telegram rejects markdown formatting with 400 Bad Request, retry as plain text
        if exc.code == 400 and "parse_mode" in payload_data:
            # HTTPError stringification can include the request URL, which
            # contains the Telegram bot token. Keep the retry diagnostic
            # useful without putting credentials in the hook log.
            logger.warning(
                "Telegram markdown parse error, falling back to plain text (HTTP %s)",
                exc.code,
            )
            try:
                payload_data.pop("parse_mode", None)
                return _send_telegram_request(url, payload_data)
            except Exception as fallback_exc:  # noqa: BLE001 -- hook boundary must never raise
                # Do not log the exception object: urllib errors can carry the
                # request URL, which contains the Telegram bot token.
                logger.error(
                    "failed to post activity in plain text fallback (%s)",
                    type(fallback_exc).__name__,
                )
                return False
        else:
            logger.error("failed to post activity (HTTP %s)", exc.code)
            return False
    except Exception as exc:  # noqa: BLE001 -- hook boundary must never raise
        # Keep hook logs useful without risking credentials from a URL-bearing
        # exception or traceback.
        logger.error("failed to post activity (%s)", type(exc).__name__)
        return False


def _read_recent_activity() -> tuple[str | None, int | None]:
    """Read pending activity without advancing the delivery cursor."""
    db = DB_PATH
    if not Path(db).exists():
        return None, None
    conn = None
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        last_id = _last_shown_id()
        columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(memories)")}
        has_status = "status" in columns
        active_filter = " AND COALESCE(status, 'active') = 'active'" if has_status else ""
        # First run after install: show only the newest row to avoid replaying
        # the entire existing store into Telegram.
        if last_id == 0:
            row = conn.execute("SELECT MAX(id) as max_id FROM memories").fetchone()
            max_id = int(row["max_id"] or 0) if row else 0
            if max_id == 0:
                return None, None
            count = 1
            display_rows = conn.execute(
                f"SELECT * FROM memories WHERE id <= ?{active_filter} ORDER BY id DESC LIMIT 1",
                (max_id,),
            ).fetchall()
        else:
            summary = conn.execute(
                f"SELECT COUNT(*) AS count, MAX(id) AS max_id FROM memories WHERE id > ?{active_filter}",
                (last_id,),
            ).fetchone()
            count = int(summary["count"] or 0) if summary else 0
            pending = conn.execute(
                "SELECT MAX(id) AS max_id FROM memories WHERE id > ?",
                (last_id,),
            ).fetchone()
            max_id = int(pending["max_id"] or 0) if pending else 0
            if max_id == 0:
                return None, None
            # Only the three rows shown in the notification need to be read;
            # a large backlog must not become an unbounded Python list.
            display_rows = conn.execute(
                f"SELECT * FROM memories WHERE id > ?{active_filter} ORDER BY id ASC LIMIT 3",
                (last_id,),
            ).fetchall()
            # Inactive rows still advance the cursor after a successful hook
            # cycle, but they must never be presented as newly stored memory.
            if count == 0:
                return None, max_id
        if not display_rows:
            # A first-run store can contain only retracted/expired rows. Ack
            # the high-water mark without emitting a misleading empty post.
            return None, max_id
        n_new = count
        noun = "memory" if n_new == 1 else "memories"
        lines = [f"🌙 Luminary — {n_new} {noun} stored"]
        for r in display_rows:
            content = str(r["content"] or "").replace("\n", " ").strip()
            if len(content) > 120:
                content = content[:120].rsplit(" ", 1)[0] + "…"
            if content:
                row_keys = r.keys()
                try:
                    imp = float(r["importance"] or 0.0) if "importance" in row_keys else 0.0
                except (TypeError, ValueError):
                    imp = 0.0
                tags = str(r["tags"] or "") if "tags" in row_keys else ""
                is_rule = imp >= 0.85 or "core" in tags or "rule" in tags
                icon = "📌" if is_rule else "•"
                lines.append(f"  {icon} {_escape_md(content)}")
        if n_new > 3:
            lines.append(f"  ... (+{n_new - 3} more)")
        return "\n".join(lines), max_id
    except Exception:
        logger.exception("activity read failed")
        return None, None
    finally:
        if conn is not None:
            conn.close()


def _recent_activity(seconds: int = 30, *, commit: bool = True) -> str | None:
    """Return new-memory activity; commit the cursor only when requested.

    ``seconds`` remains for compatibility with older callers. Activity is
    cursor-based rather than wall-clock-based so delayed writer jobs are not
    silently missed.
    """
    with _cursor_lock():
        line, max_id = _read_recent_activity()
        if commit and max_id is not None:
            _set_last_shown_id(max_id)
    return line


def handle(event_type: str, context: dict) -> None:
    """Hook entry point: surface stored-memory activity on agent:end."""
    if event_type != "agent:end":
        return
    with _cursor_lock():
        line, max_id = _read_recent_activity()
        if max_id is not None and (line is None or _post(line)):
            _set_last_shown_id(max_id)
