"""LuminaryMemoryProvider — Hermes memory provider implementation.

The provider imports the ``MemoryProvider`` ABC from ``agent.memory_provider``,
which exists only in the hermes-agent runtime. Tests inject a faithful stub via
``tests/conftest.py`` (see tests/hermes_stubs/agent/memory_provider.py); at
runtime the real ABC is used.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import queue
import threading

from agent.memory_provider import MemoryProvider  # present only in hermes runtime

from luminary_memory.api import MemoryClient
from luminary_memory.config import Settings
from luminary_memory.hermes.config import _DEFAULTS, load_config, save_config

_LUMINARY_GLYPH = "🌙"

_MODE_CHOICES = ["context", "tools", "hybrid"]

_SENTINEL = None  # writer-queue shutdown marker


class LuminaryMemoryProvider(MemoryProvider):
    """Hermes memory provider backed by the luminary-memory store."""

    def __init__(self) -> None:
        self._hermes_home: str | None = None
        self._config: dict = dict(_DEFAULTS)
        self._client: MemoryClient | None = None
        self._session_id: str | None = None
        self._parent_session_id: str | None = None
        self._platform: str = ""
        self._agent_identity: str = ""
        self._user_id: str = ""
        self._status_callback = None
        self._shutting_down = threading.Event()
        self._retain_queue: queue.Queue = queue.Queue()
        self._writer_thread: threading.Thread | None = None
        self._session_turns: list[str] = []
        self._turn_counter: int = 0
        self._thread_client: MemoryClient | None = None
        self._thread_client_owner: str | None = None

    # ------------------------------------------------------------------ #
    # Identity & availability
    # ------------------------------------------------------------------ #

    @property
    def name(self) -> str:
        return "luminary"

    def is_available(self) -> bool:
        """Return True when the package imports and (for pgvector) deps exist.

        No network, no store creation.
        """
        if importlib.util.find_spec("luminary_memory") is None:
            return False
        backend = self._config.get("backend", "sqlite")
        if backend == "pgvector":
            if importlib.util.find_spec("psycopg") is None:
                return False
            if importlib.util.find_spec("pgvector") is None:
                return False
        return True

    def unavailable_reason(self) -> str:
        """Actionable hint when the provider cannot activate."""
        if importlib.util.find_spec("luminary_memory") is None:
            return "luminary-memory is not installed; run `pip install luminary-memory`"
        backend = self._config.get("backend", "sqlite")
        if backend == "pgvector":
            missing = [
                name
                for name in ("psycopg", "pgvector")
                if importlib.util.find_spec(name) is None
            ]
            if missing:
                return f"backend 'pgvector' requires: {', '.join(missing)}"
        return ""

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    def initialize(self, session_id: str, **kwargs) -> None:
        """Connect, load config, create resources, start the writer thread.

        Must not trigger an embedding-model load (that happens on first recall).
        """
        hermes_home = kwargs.get("hermes_home") or os.environ.get(
            "HERMES_HOME", os.path.expanduser("~/.hermes")
        )
        self._hermes_home = str(hermes_home)
        self._config = load_config(self._hermes_home)
        self._session_id = session_id
        self._platform = kwargs.get("platform", "")
        self._agent_identity = kwargs.get("agent_identity", "")
        self._agent_workspace = kwargs.get("agent_workspace", "")
        self._user_id = kwargs.get("user_id", "")
        self._status_callback = kwargs.get("status_callback")

        db_path = self._resolve_db_path()
        settings = Settings(
            backend=self._config.get("backend", "sqlite"),
            db_path=db_path,
            token_budget=int(self._config.get("token_budget", 2048)),
            ingest_llm=bool(self._config.get("ingest_llm", False)),
        )
        if self._config.get("ingest_llm"):
            settings.ingest_llm = True
        self._client = MemoryClient(settings=settings)
        self._shutting_down.clear()
        self._start_writer()
        if kwargs.get("status_callback") is None:
            # Hermes passes a status callback; a no-op keeps the provider safe
            # when constructed and initialized directly.
            self._status_callback = self._status_callback

    def _resolve_db_path(self) -> str:
        cfg_path = self._config.get("db_path", "") or ""
        if cfg_path:
            return cfg_path
        db_path = os.path.join(self._hermes_home, "luminary", "memory.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        return db_path

    def _start_writer(self) -> None:
        self._writer_thread = threading.Thread(
            target=self._writer_loop, name="luminary-retain-writer", daemon=True
        )
        self._writer_thread.start()

    def _writer_loop(self) -> None:
        while True:
            item = self._retain_queue.get()
            if item is _SENTINEL:
                self._retain_queue.task_done()
                break
            try:
                fn = item[0]
                fn(*item[1:])
            except Exception:  # writer must never die
                logging.getLogger(__name__).exception("retain writer task failed")
            finally:
                self._retain_queue.task_done()

    def shutdown(self) -> None:
        """Flush queued retains, stop the writer, close the store."""
        self._shutting_down.set()
        self._retain_queue.put(_SENTINEL)
        if self._writer_thread is not None:
            self._writer_thread.join(timeout=5.0)
        if self._thread_client is not None:
            try:
                self._thread_client.close()
            except Exception:
                logging.getLogger(__name__).exception("thread client close failed")
            self._thread_client = None
        if self._client is not None:
            self._client.close()
            self._client = None

    # ------------------------------------------------------------------ #
    # Config
    # ------------------------------------------------------------------ #

    def get_config_schema(self) -> list[dict]:
        """Declare the config fields surfaced by ``hermes memory setup``."""
        return [
            {
                "key": "mode",
                "label": "Mode",
                "type": "select",
                "choices": _MODE_CHOICES,
                "default": _DEFAULTS["mode"],
            },
            {
                "key": "db_path",
                "label": "Database path",
                "type": "text",
                "default": _DEFAULTS["db_path"],
            },
            {
                "key": "backend",
                "label": "Backend",
                "type": "select",
                "choices": ["sqlite", "pgvector"],
                "default": _DEFAULTS["backend"],
            },
            {
                "key": "recall_limit",
                "label": "Recall limit",
                "type": "number",
                "default": _DEFAULTS["recall_limit"],
            },
            {
                "key": "token_budget",
                "label": "Token budget",
                "type": "number",
                "default": _DEFAULTS["token_budget"],
            },
            {
                "key": "auto_recall",
                "label": "Auto recall",
                "type": "boolean",
                "default": _DEFAULTS["auto_recall"],
            },
            {
                "key": "recall_sync",
                "label": "Synchronous recall",
                "type": "boolean",
                "default": _DEFAULTS["recall_sync"],
            },
            {
                "key": "auto_retain",
                "label": "Auto retain",
                "type": "boolean",
                "default": _DEFAULTS["auto_retain"],
            },
            {
                "key": "retain_every_n_turns",
                "label": "Retain every N turns",
                "type": "number",
                "default": _DEFAULTS["retain_every_n_turns"],
            },
            {
                "key": "retain_user_prefix",
                "label": "User prefix",
                "type": "text",
                "default": _DEFAULTS["retain_user_prefix"],
            },
            {
                "key": "retain_assistant_prefix",
                "label": "Assistant prefix",
                "type": "text",
                "default": _DEFAULTS["retain_assistant_prefix"],
            },
            {
                "key": "ingest_llm",
                "label": "LLM enrichment",
                "type": "boolean",
                "default": _DEFAULTS["ingest_llm"],
            },
            {
                "key": "llm_base_url",
                "label": "LLM base URL",
                "type": "text",
                "default": _DEFAULTS["llm_base_url"],
            },
            {
                "key": "llm_model",
                "label": "LLM model",
                "type": "text",
                "default": _DEFAULTS["llm_model"],
            },
            {
                "key": "llm_timeout",
                "label": "LLM timeout (s)",
                "type": "number",
                "default": _DEFAULTS["llm_timeout"],
            },
            {
                "key": "llm_api_key",
                "label": "LLM API key",
                "type": "text",
                "secret": True,
                "env_var": "LUMINARY_LLM_API_KEY",
                "default": "",
            },
            {
                "key": "recall_indicator",
                "label": "Recall indicator",
                "type": "boolean",
                "default": _DEFAULTS["recall_indicator"],
            },
            {
                "key": "retain_indicator",
                "label": "Retain indicator",
                "type": "boolean",
                "default": _DEFAULTS["retain_indicator"],
            },
        ]

    def save_config(self, values: dict) -> None:
        """Persist config values to the provider config file."""
        if not self._hermes_home:
            raise RuntimeError("provider is not initialized; cannot save config")
        save_config(values, self._hermes_home)
        self._config.update({k: v for k, v in values.items() if k in _DEFAULTS})

    # ------------------------------------------------------------------ #
    # Session boundaries
    # ------------------------------------------------------------------ #

    def _flush_session_turns(self, session_id: str | None = None) -> None:
        """Flush buffered turns under a session lineage (writer-enqueued)."""
        if not self._session_turns:
            return
        content = "\n".join(self._session_turns)
        sid = session_id or self._session_id
        tags = [f"session:{sid}"] if sid else []
        if self._parent_session_id:
            tags.append(f"parent:{self._parent_session_id}")
        if self._platform:
            tags.append(f"platform:{self._platform}")
        if self._agent_identity:
            tags.append(f"agent:{self._agent_identity}")
        metadata = {
            "turn_index": None,
            "message_count": len(self._session_turns),
            "session_id": sid,
            "platform": self._platform,
            "agent_identity": self._agent_identity,
        }
        self._enqueue_retain(content, tags, metadata)
        self._emit_retain_indicator()
        self._session_turns = []
        self._turn_counter = 0

    def on_session_end(self, messages) -> None:
        """Flush buffered turns under the current session lineage."""
        if not self._client or self._shutting_down.is_set():
            return
        self._flush_session_turns()

    def on_session_switch(self, new_session_id: str, **kwargs) -> None:
        """Flush the old session, then rebind to the new one."""
        if not self._client or self._shutting_down.is_set():
            return
        old_id = self._session_id
        self._flush_session_turns(old_id)

        reset = kwargs.get("reset", False)
        if reset:
            self._session_turns = []
            self._turn_counter = 0

        if new_session_id:
            self._session_id = new_session_id
            self._parent_session_id = kwargs.get("parent_session_id") or self._parent_session_id

    # ------------------------------------------------------------------ #
    # Auto-save
    # ------------------------------------------------------------------ #

    def sync_turn(self, user: str, assistant: str, **kwargs) -> None:
        """Persist a completed turn to the store (buffered, non-blocking).

        Turns accumulate in ``_session_turns``; every ``retain_every_n_turns``
        turns the batch is enqueued on the single writer thread.
        """
        if not self._client or self._shutting_down.is_set():
            return
        if not self._config.get("auto_retain", True):
            return

        user_prefix = self._config.get("retain_user_prefix", "User")
        assistant_prefix = self._config.get("retain_assistant_prefix", "Assistant")
        content = f"{user_prefix}: {user}\n{assistant_prefix}: {assistant}"

        self._session_turns.append(content)
        self._turn_counter += 1

        every_n = int(self._config.get("retain_every_n_turns", 1) or 1)
        if self._turn_counter % every_n != 0:
            return  # buffer only

        batch = "\n".join(self._session_turns)
        self._session_turns = []
        self._turn_counter = 0

        session_id = kwargs.get("session_id") or self._session_id
        parent_id = kwargs.get("parent_session_id") or self._parent_session_id

        tags = [f"session:{session_id}"] if session_id else []
        if parent_id:
            tags.append(f"parent:{parent_id}")
        if self._platform:
            tags.append(f"platform:{self._platform}")
        if self._agent_identity:
            tags.append(f"agent:{self._agent_identity}")

        metadata = {
            "turn_index": kwargs.get("turn_index"),
            "message_count": kwargs.get("message_count"),
            "session_id": session_id,
            "platform": self._platform,
            "agent_identity": self._agent_identity,
        }

        self._enqueue_retain(batch, tags, metadata)
        self._emit_retain_indicator()

    def _enqueue_retain(self, content: str, tags: list[str], metadata: dict) -> None:
        self._retain_queue.put((self._do_retain, content, tags, metadata))

    def _do_retain(self, content: str, tags: list[str], metadata: dict) -> None:
        """Writer-thread task: ingest the buffered turn batch.

        The client is created lazily on the writer thread so that SQLite
        connections are used exclusively from the thread that created them.
        """
        client = self._writer_client()
        if client is None:
            return
        try:
            client.ingest(content, tags=tags, source="hermes")
        except Exception:  # writer must never die
            logging.getLogger(__name__).exception("retain ingest failed")

    def _writer_client(self) -> MemoryClient | None:
        """Return a client owned by the calling (writer) thread."""
        thread_name = threading.current_thread().name
        if self._thread_client is not None and self._thread_client_owner == thread_name:
            return self._thread_client
        if self._hermes_home:
            db_path = self._resolve_db_path()
            settings = Settings(
                backend=self._config.get("backend", "sqlite"),
                db_path=db_path,
                token_budget=int(self._config.get("token_budget", 2048)),
                ingest_llm=bool(self._config.get("ingest_llm", False)),
            )
            client = MemoryClient(settings=settings)
            if getattr(client, "engine", None) is not None:
                # Reuse the shared engine instance (single model load).
                client.engine = self._client.engine if self._client else client.engine
            self._thread_client = client
            self._thread_client_owner = thread_name
            return client
        return None

    def _emit_retain_indicator(self) -> None:
        if not self._config.get("retain_indicator", True):
            return
        if self._status_callback:
            try:
                self._status_callback("🌙 Luminary — memory saved")
            except Exception:
                logging.getLogger(__name__).exception("status callback failed")

    # ------------------------------------------------------------------ #
    # System prompt
    # ------------------------------------------------------------------ #

    def system_prompt_block(self) -> str:
        """Emit a compact, mode-aware block for the system prompt."""
        if not self._hermes_home:
            return ""
        mode = self._config.get("mode", "hybrid")
        db_path = self._resolve_db_path()
        lines = [
            "# Luminary Memory",
            f"Active ({mode} mode). Store: {db_path}.",
        ]
        if mode in ("context", "hybrid"):
            lines.append("Relevant memories are automatically injected into context.")
        if mode in ("tools", "hybrid"):
            lines.append("Use the `luminary_recall` / `luminary_ingest` tools to query or store memories on demand.")
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    # Tools (stub — full implementation lands in T10)
    # ------------------------------------------------------------------ #

    def get_tool_schemas(self) -> list[dict]:
        """Expose model-callable tool schemas (tools land in T10)."""
        return []
