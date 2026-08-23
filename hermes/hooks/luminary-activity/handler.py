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
_DEFAULT_HERMES_HOME = Path(
    os.getenv("HERMES_HOME") or (Path.home() / ".hermes")
).expanduser()
DB_PATH = os.getenv(
    "LUMINARY_DB_PATH",
    str(_DEFAULT_HERMES_HOME / "luminary" / "memory.db"),
)
LOG_FILE = _DEFAULT_HERMES_HOME / "hooks" / "luminary-activity" / "hook.log"
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


def _load_hermes_env(context: dict | None = None) -> dict[str, str]:
    """Parse ~/.hermes/.env as fallback if env vars are not in os.environ."""
    env_file = _resolve_hermes_home(context) / ".env"
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


def _resolve_hermes_home(context: dict | None = None) -> Path:
    """Resolve the active Hermes home without importing Hermes internals."""
    if isinstance(context, dict):
        for key in ("hermes_home", "HERMES_HOME", "home"):
            value = context.get(key)
            if value:
                return Path(str(value)).expanduser()
    return Path(os.getenv("HERMES_HOME") or (Path.home() / ".hermes")).expanduser()


def _resolve_db_path(context: dict | None = None) -> str:
    """Resolve the same canonical store used by the Luminary provider."""
    home = _resolve_hermes_home(context)

    def canonical(value: str) -> str:
        path = Path(str(value)).expanduser()
        return str(path if path.is_absolute() else (home / path).resolve())

    if context is None:
        return str(DB_PATH)
    for key in ("luminary_db_path", "db_path"):
        value = context.get(key) if isinstance(context, dict) else None
        if value:
            return canonical(str(value))
    env_path = os.getenv("LUMINARY_DB_PATH")
    if env_path:
        return canonical(env_path)

    config_path = home / "luminary" / "config.json"
    try:
        stored = json.loads(config_path.read_text(encoding="utf-8"))
        configured = stored.get("db_path") if isinstance(stored, dict) else None
        if configured:
            path = Path(str(configured)).expanduser()
            return str(path if path.is_absolute() else (home / path).resolve())
    except (OSError, ValueError, json.JSONDecodeError):
        logger.warning("could not read Luminary path config at %s", config_path)
    return str(home / "luminary" / "memory.db")


def _resolve_state_file(context: dict | None = None) -> Path:
    """Use a cursor beside the active Hermes home, not a global user cursor."""
    if context is None:
        return Path(STATE_FILE)
    return _resolve_hermes_home(context) / "hooks" / "luminary-activity" / "state.json"


def _last_shown_id(state_file: str | Path | None = None) -> int:
    state_path = Path(state_file or STATE_FILE)
    try:
        if state_path.exists():
            data = json.loads(state_path.read_text(encoding="utf-8"))
            return int(data.get("last_id", 0))
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("could not parse state file: %s", exc)
    return 0


@contextmanager
def _cursor_lock(state_file: str | Path | None = None):
    """Serialize read -> send -> cursor-advance across hook processes."""
    state_path = Path(state_file or STATE_FILE)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = state_path.with_name(f"{state_path.name}.lock")
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


def _set_last_shown_id(mid: int, state_file: str | Path | None = None) -> None:
    state_path = Path(state_file or STATE_FILE)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = state_path.with_name(f"{state_path.name}.tmp")
    try:
        with open(tmp_file, "w", encoding="utf-8") as fh:
            json.dump({"last_id": int(mid)}, fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_file, state_path)
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


def _post(text: str, context: dict | None = None) -> bool:
    token = BOT_TOKEN
    chat = CHAT_ID
    thread = THREAD_ID
    if not token or not chat:
        file_env = _load_hermes_env(context)
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


def _read_recent_activity(
    context: dict | None = None,
    state_file: str | Path | None = None,
) -> tuple[str | None, int | None]:
    """Read pending activity without advancing the delivery cursor."""
    db = _resolve_db_path(context)
    if not Path(db).exists():
        return None, None
    conn = None
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        last_id = _last_shown_id(state_file)
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


def _recent_activity(
    seconds: int = 30,
    *,
    commit: bool = True,
    context: dict | None = None,
) -> str | None:
    """Return new-memory activity; commit the cursor only when requested.

    ``seconds`` remains for compatibility with older callers. Activity is
    cursor-based rather than wall-clock-based so delayed writer jobs are not
    silently missed.
    """
    state_file = _resolve_state_file(context)
    with _cursor_lock(state_file):
        line, max_id = _read_recent_activity(context, state_file)
        if commit and max_id is not None:
            _set_last_shown_id(max_id, state_file)
    return line


def handle(event_type: str, context: dict) -> None:
    """Hook entry point: surface stored-memory activity on agent:end."""
    if event_type != "agent:end":
        return
    effective_context = context if context else None
    state_file = _resolve_state_file(effective_context)
    with _cursor_lock(state_file):
        if effective_context is None:
            line, max_id = _read_recent_activity()
        else:
            line, max_id = _read_recent_activity(effective_context, state_file)
        if max_id is not None:
            delivered = (
                _post(line)
                if effective_context is None
                else _post(line, effective_context)
            ) if line is not None else True
            if delivered:
                if effective_context is None:
                    _set_last_shown_id(max_id)
                else:
                    _set_last_shown_id(max_id, state_file)
