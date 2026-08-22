"""Unit tests for the luminary-activity hook (handler.py).

The hook surfaces new memories to a Telegram chat after agent turns.
These tests mock the Telegram API and SQLite store; no live network.
"""
import importlib.util
import json
import os
import sqlite3
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

# ============================================================================
# Helpers — load handler module with mocked globals
# ============================================================================

def _load_handler(tmp_path, **env_overrides):
    """Load handler.py with its module-level globals pointed at tmp_path."""
    db_path = str(tmp_path / "memory.db")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS memories (id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT, "
        "created_at TEXT, updated_at TEXT, last_accessed_at TEXT, access_count INTEGER, "
        "importance REAL DEFAULT 0.5, source TEXT, tags TEXT DEFAULT '[]', metadata TEXT DEFAULT '{}', "
        "ttl_seconds INTEGER, embedding BLOB)"
    )
    conn.commit()
    conn.close()

    env = dict(os.environ)
    env.update({
        "TELEGRAM_BOT_TOKEN": "fake-token",
        "LUMINARY_HOOK_CHAT_ID": "12345",
        "LUMINARY_DB_PATH": db_path,
        **(env_overrides or {}),
    })

    mock_log_dir = tmp_path / "hooks" / "luminary-activity"
    mock_log_dir.mkdir(parents=True, exist_ok=True)

    with patch.dict(os.environ, env, clear=True),          patch.object(Path, "home", return_value=tmp_path):
        # Load handler.py as a module from its file path
        handler_path = Path(__file__).parent.parent.parent / "hermes" / "hooks" / "luminary-activity" / "handler.py"
        spec = importlib.util.spec_from_file_location("luminary_activity_handler", handler_path)
        h = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(h)
        # Override state/log paths to our controlled tmp directory
        h.STATE_FILE = tmp_path / "state.json"
        h.LOG_FILE = tmp_path / "hook.log"
        h.DB_PATH = db_path
        return h


def _seed(db_path, contents):
    conn = sqlite3.connect(db_path)
    for i, c in enumerate(contents, 1):
        conn.execute(
            "INSERT INTO memories (id, content) VALUES (?, ?)",
            (i, c),
        )
    conn.commit()
    conn.close()


# ============================================================================
# _recent_activity — dedup, last_id tracking, content format
# ============================================================================

def test_recent_activity_first_run_returns_only_newest(tmp_path):
    """First run (last_id=0): only the single newest memory is shown."""
    h = _load_handler(tmp_path)
    _seed(h.DB_PATH, ["old fact", "middle fact", "newest fact"])

    result = h._recent_activity()
    assert result is not None
    assert "newest fact" in result
    assert "old fact" not in result
    assert "1 memory" in result


def test_recent_activity_shows_new_memories_since_last_id(tmp_path):
    """After last_id is set, only memories with id > last_id appear."""
    h = _load_handler(tmp_path)
    h._set_last_shown_id(2)
    _seed(h.DB_PATH, ["shown before", "already seen", "new fact 1", "new fact 2"])

    result = h._recent_activity()
    assert result is not None
    assert "new fact 1" in result
    assert "new fact 2" in result
    assert "already seen" not in result
    assert "2 memories" in result


def test_recent_activity_no_new_memories_returns_none(tmp_path):
    h = _load_handler(tmp_path)
    h._set_last_shown_id(99)
    _seed(h.DB_PATH, ["old fact"])

    assert h._recent_activity() is None


def test_recent_activity_empty_store_returns_none(tmp_path):
    h = _load_handler(tmp_path)
    assert h._recent_activity() is None


def test_recent_activity_truncates_long_content(tmp_path):
    h = _load_handler(tmp_path)
    h._set_last_shown_id(0)
    long = "A" * 200 + " final word"
    _seed(h.DB_PATH, [long])

    result = h._recent_activity()
    assert len(result) < 200, f"too long: {len(result)}"
    assert "…" in result


def test_recent_activity_marks_last_shown_id(tmp_path):
    h = _load_handler(tmp_path)
    h._set_last_shown_id(2)
    _seed(h.DB_PATH, ["a", "b", "c", "d", "e"])

    h._last_shown_id()
    h._recent_activity()
    after = h._last_shown_id()
    assert after >= 4, f"last_shown_id should advance past shown ids, got {after}"


def test_recent_activity_missing_db_returns_none(tmp_path):
    h = _load_handler(tmp_path)
    h.DB_PATH = str(tmp_path / "nonexistent.db")
    assert h._recent_activity() is None


# ============================================================================
# _post — payload, error handling, token/chat missing
# ============================================================================

def test_post_sends_correct_payload(tmp_path):
    h = _load_handler(tmp_path)

    with patch("urllib.request.urlopen") as mock_open:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"ok":true}'
        mock_open.return_value.__enter__.return_value = mock_resp

        h._post("test message")

        args, _ = mock_open.call_args
        req = args[0]
        body = json.loads(req.data.decode())
        assert body["chat_id"] == "12345"
        assert body["text"] == "test message"
        assert body["parse_mode"] == "Markdown"


def test_post_includes_forum_thread_id(tmp_path):
    h = _load_handler(tmp_path, LUMINARY_HOOK_THREAD_ID="42")

    with patch("urllib.request.urlopen") as mock_open:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"ok":true}'
        mock_open.return_value.__enter__.return_value = mock_resp

        assert h._post("threaded activity") is True
        req = mock_open.call_args.args[0]
        body = json.loads(req.data.decode())
        assert body["message_thread_id"] == 42


def test_post_treats_telegram_ok_false_as_delivery_failure(tmp_path):
    h = _load_handler(tmp_path)

    with patch("urllib.request.urlopen") as mock_open:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"ok":false,"description":"chat not found"}'
        mock_open.return_value.__enter__.return_value = mock_resp

        assert h._post("retriable activity") is False


def test_post_swallows_network_error(tmp_path):
    h = _load_handler(tmp_path)

    with patch("urllib.request.urlopen", side_effect=OSError("network down")):
        # Must not raise
        h._post("test message")


def test_post_skips_when_token_missing(tmp_path):
    h = _load_handler(tmp_path, TELEGRAM_BOT_TOKEN="")
    # Must not raise
    h._post("should be skipped")


def test_post_skips_when_chat_missing(tmp_path):
    h = _load_handler(tmp_path, LUMINARY_HOOK_CHAT_ID="", TELEGRAM_HOME_CHANNEL="")
    # Must not raise
    h._post("should be skipped")


def test_post_falls_back_to_plain_text_on_http_400(tmp_path):
    h = _load_handler(tmp_path)

    calls = []

    def mock_urlopen(req, timeout=10):
        body = json.loads(req.data.decode())
        calls.append(body)
        if "parse_mode" in body:
            raise urllib.error.HTTPError("url", 400, "Bad Request: can't parse entities", {}, None)
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"ok":true}'
        return mock_resp

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        h._post("content with strange _ formatting")

    assert len(calls) == 2
    assert calls[0]["parse_mode"] == "Markdown"
    assert "parse_mode" not in calls[1]
    assert calls[1]["text"] == "content with strange _ formatting"



# ============================================================================
# handle — only on agent:end; the cursor commits after delivery succeeds
# ============================================================================

def test_handle_fires_on_agent_end(tmp_path):
    h = _load_handler(tmp_path)
    with patch.object(h, "_read_recent_activity", return_value=("test line", 7)) as mock_ra, \
         patch.object(h, "_post", return_value=True) as mock_post:
        h.handle("agent:end", {})
        mock_ra.assert_called_once()
        mock_post.assert_called_once_with("test line")
        assert h._last_shown_id() == 7


def test_handle_ignores_agent_start(tmp_path):
    h = _load_handler(tmp_path)
    with patch.object(h, "_read_recent_activity") as mock_ra, \
         patch.object(h, "_post") as mock_post:
        h.handle("agent:start", {})
        mock_ra.assert_not_called()
        mock_post.assert_not_called()


def test_handle_skips_when_store_idle(tmp_path):
    h = _load_handler(tmp_path)
    with patch.object(h, "_read_recent_activity", return_value=(None, None)), \
         patch.object(h, "_post") as mock_post:
        h.handle("agent:end", {})
        mock_post.assert_not_called()


def test_handle_does_not_advance_cursor_when_telegram_fails(tmp_path):
    h = _load_handler(tmp_path)
    h._set_last_shown_id(0)
    _seed(h.DB_PATH, ["fact that must be retried"])

    with patch.object(h, "_post", return_value=False):
        h.handle("agent:end", {})
    assert h._last_shown_id() == 0

    with patch.object(h, "_post", return_value=True):
        h.handle("agent:end", {})
    assert h._last_shown_id() == 1


def test_recent_activity_escapes_markdown_underscores(tmp_path):
    h = _load_handler(tmp_path)
    h._set_last_shown_id(0)
    _seed(h.DB_PATH, ["Configured llm_base_url in src/test_module.py"])
    res = h._recent_activity()
    assert res is not None
    assert r"llm\_base\_url" in res or r"test\_module.py" in res


def test_recent_activity_shows_pin_icon_for_rules(tmp_path):
    h = _load_handler(tmp_path)
    h._set_last_shown_id(0)
    conn = sqlite3.connect(h.DB_PATH)
    conn.execute(
        "INSERT INTO memories (id, content, importance, tags) VALUES (?, ?, ?, ?)",
        (1, "ALWAYS use PostgreSQL for database migration.", 0.9, "rule"),
    )
    conn.commit()
    conn.close()
    res = h._recent_activity()
    assert res is not None
    assert "📌" in res


def test_recent_activity_handles_batch_overflow(tmp_path):
    h = _load_handler(tmp_path)
    h._set_last_shown_id(1)
    _seed(h.DB_PATH, ["f1", "f2", "f3", "f4", "f5"])
    res = h._recent_activity()
    assert res is not None
    assert "4 memories stored" in res
    assert "(+1 more)" in res
    assert h._last_shown_id() == 5
