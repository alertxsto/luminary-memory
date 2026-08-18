"""LuminaryMemoryProvider — Hermes memory provider implementation.

The provider imports the ``MemoryProvider`` ABC from ``agent.memory_provider``,
which exists only in the hermes-agent runtime. Tests inject a faithful stub via
``tests/conftest.py`` (see tests/hermes_stubs/agent/memory_provider.py); at
runtime the real ABC is used.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import queue
import threading
import time

from agent.memory_provider import MemoryProvider  # present only in hermes runtime

from luminary_memory.api import MemoryClient
from luminary_memory.config import Settings
from luminary_memory.hermes.config import _DEFAULTS, load_config, save_config

_LUMINARY_GLYPH = "🌙"

_MODE_CHOICES = ["context", "tools", "hybrid"]

_RECALL_HEADER = "# Luminary Memory (persistent cross-session context)"

_SENTINEL = None  # writer-queue shutdown marker


def _setup_logger(hermes_home: str) -> logging.Logger:
    """Return a logger that writes to $HERMES_HOME/luminary/luminary.log.

    The log records every recall, retain, and error so users can see what
    the provider is doing (transparency log).
    """
    logger = logging.getLogger("luminary_memory.hermes")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        log_dir = os.path.join(hermes_home, "luminary")
        os.makedirs(log_dir, exist_ok=True)
        fh = logging.FileHandler(os.path.join(log_dir, "luminary.log"), encoding="utf-8")
        fh.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        )
        logger.addHandler(fh)
    return logger


class LuminaryMemoryProvider(MemoryProvider):
    """Hermes memory provider backed by the luminary-memory store."""

    def __init__(self) -> None:
        self._hermes_home: str | None = None
        self._log = logging.getLogger("luminary_memory.hermes")
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
        self._prefetch_cache: tuple[str, int] | None = None
        self._prefetch_lock = threading.Lock()
        self._prefetch_thread: threading.Thread | None = None
        self._last_recall_count: int = 0
        self._last_recall_returned: bool = False

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
        self._log = _setup_logger(self._hermes_home)
        self._log.info(
            "initialize session=%s platform=%s agent=%s",
            session_id, kwargs.get("platform", ""), kwargs.get("agent_identity", ""),
        )
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
                # Close the thread-owned client here (SQLite thread affinity).
                if self._thread_client is not None:
                    try:
                        self._thread_client.close()
                    except Exception:
                        logging.getLogger(__name__).exception("thread client close failed")
                    self._thread_client = None
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
        # Ask the writer thread to close its own client (SQLite objects are
        # thread-affine — closing from the main thread would crash).
        self._retain_queue.put(_SENTINEL)
        if self._writer_thread is not None:
            self._writer_thread.join(timeout=5.0)
        self._thread_client = None
        if self._client is not None:
            self._client.close()
            self._client = None

    # ------------------------------------------------------------------ #
    # Config
    # ------------------------------------------------------------------ #

    def get_config_schema(self) -> list[dict]:
        """Declare the config fields surfaced by ``hermes memory setup``.

        Derived from ``hermes.config_schema.CONFIG_SCHEMA`` (single source of
        truth for dashboard + CLI). ``llm_api_key`` is appended as a secret;
        select fields get their choices from the shared constants.
        """
        from luminary_memory.hermes.config_schema import CONFIG_SCHEMA

        fields: list[dict] = []
        for f in CONFIG_SCHEMA.fields:
            key = f["key"]
            entry: dict = {
                "key": key,
                "label": f["label"],
                "type": f["type"],
                "default": _DEFAULTS.get(key, ""),
            }
            if key == "mode":
                entry["choices"] = _MODE_CHOICES
            elif key == "backend":
                entry["choices"] = ["sqlite", "pgvector"]
            fields.append(entry)

        fields.append(
            {
                "key": "llm_api_key",
                "label": "LLM API key",
                "type": "text",
                "secret": True,
                "env_var": "LUMINARY_LLM_API_KEY",
                "default": "",
            }
        )
        return fields

    def save_config(self, values: dict, hermes_home: str | None = None) -> None:
        """Persist config values to the provider config file.

        ``hermes_home`` is accepted for the Hermes dashboard contract
        (``provider.save_config(values, hermes_home)``); when omitted, the
        provider's own home is used.
        """
        home = hermes_home or self._hermes_home
        if not home:
            raise RuntimeError("provider is not initialized; cannot save config")
        save_config(values, home)
        self._config.update({k: v for k, v in values.items() if k in _DEFAULTS})

    # ------------------------------------------------------------------ #
    # Hooks: builtin-mirror, delegation, pre-compress
    # ------------------------------------------------------------------ #

    def on_memory_write(self, action: str, target: str, content: str, metadata=None) -> None:
        """Mirror built-in memory tool writes into the store (additive)."""
        if not self._client or self._shutting_down.is_set():
            return
        tags = ["builtin", target] if target else ["builtin"]
        if action == "replace":
            tags.append("replace:builtin")
        self._enqueue_retain(
            content, tags, {"action": action, "target": target}, source="hermes-builtin"
        )

    def on_delegation(self, task, result, child_session_id: str = "") -> None:
        """Persist a delegation observation."""
        if not self._client or self._shutting_down.is_set():
            return
        tags = ["delegation"]
        if child_session_id:
            tags.append(f"child:{child_session_id}")
        metadata = {"result": (result or "")[:500]}
        self._enqueue_retain(f"delegated: {task}", tags, metadata)

    def on_pre_compress(self, messages) -> str:
        """Return an extraction block for pre-compression (no-op)."""
        return ""

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
        """Flush buffered turns; optionally run LLM store maintenance."""
        if not self._client or self._shutting_down.is_set():
            return
        self._flush_session_turns()
        if self._config.get("auto_maintain", False) and self._config.get("ingest_llm", False):
            try:
                result = self._client.run_maintenance()
                self._log.info("maintenance %s", result)
            except Exception:
                logging.getLogger(__name__).exception("LLM maintenance failed")

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

    def _enqueue_retain(self, content: str, tags: list[str], metadata: dict, source: str = "hermes") -> None:
        self._retain_queue.put((self._do_retain, content, tags, metadata, source))

    def _do_retain(self, content: str, tags: list[str], metadata: dict, source: str = "hermes") -> None:
        """Writer-thread task: ingest the buffered turn batch.

        The client is created lazily on the writer thread so that SQLite
        connections are used exclusively from the thread that created them.

        When LLM enrichment is enabled, the enricher decides whether the
        turn is worth saving and produces a factual summary; turns the LLM
        deems trivial are dropped instead of polluting the store.
        """
        client = self._writer_client()
        if client is None:
            return
        try:
            if self._config.get("ingest_llm") and client.enricher is not None:
                enriched = client.enricher.enrich(content)
                if not enriched.worth_saving:
                    self._log.info("retain skipped (LLM: not worth saving) len=%d", len(content))
                    return
                # Store the factual summary (not the raw transcript) as content.
                if enriched.summary:
                    content = enriched.summary
            meta = {k: v for k, v in (metadata or {}).items() if v is not None}
            client.ingest(content, tags=tags, source=source, metadata=meta)
            self._log.info("retain stored len=%d tags=%s", len(content), tags)
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
            enricher = None
            if self._config.get("ingest_llm"):
                from luminary_memory.ingest.llm import OpenAICompatibleEnricher

                enricher = OpenAICompatibleEnricher(
                    base_url=self._config.get("llm_base_url") or "",
                    api_key=self._config.get("llm_api_key") or "",
                    model=self._config.get("llm_model") or "",
                    timeout=int(self._config.get("llm_timeout", 60)),
                )
            client = MemoryClient(settings=settings, enricher=enricher)
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
    # Auto-recall
    # ------------------------------------------------------------------ #

    def _format_recall_block(self, memories, scores) -> str:
        lines = [_RECALL_HEADER, "Recalled relevant memories to ground the reply."]
        for m, s in zip(memories, scores):
            lines.append(f"- {m.content}")
        return "\n".join(lines)

    def queue_prefetch(self, query: str, session_id: str) -> None:
        """Queue a background recall for the next turn (warm prefetch)."""
        if self._shutting_down.is_set():
            return
        if not self._client:
            return
        if not self._config.get("auto_recall", True):
            return
        if self._config.get("mode", "hybrid") == "tools":
            return
        if self._config.get("recall_sync", False):
            return

        def _worker() -> None:
            try:
                _t0 = time.time()
                client = self._writer_client()
                if client is None:
                    return
                result = client.recall(
                    query,
                    limit=int(self._config.get("recall_limit", 10)),
                    token_budget=int(self._config.get("token_budget", 2048)),
                )
                text = self._format_recall_block(result.memories, result.scores)
                with self._prefetch_lock:
                    self._prefetch_cache = (text, len(result.memories))
                self._log.info(
                    "recall query=%r limit=%s -> %d memories (%.0fms)",
                    query, self._config.get("recall_limit", 10),
                    len(result.memories), (time.time() - _t0) * 1000,
                )
            except Exception:
                logging.getLogger(__name__).exception("prefetch recall failed")

        # Join any in-flight prefetch first so a fast double-call never leaks
        # a thread or lets an older worker overwrite a newer cache.
        if self._prefetch_thread is not None and self._prefetch_thread.is_alive():
            self._prefetch_thread.join(timeout=3.0)
        t = threading.Thread(target=_worker, name="luminary-prefetch", daemon=True)
        t.start()
        self._prefetch_thread = t

    def prefetch(self, query: str, session_id: str) -> str:
        """Return recall context for the current turn (cached or live)."""
        if not self._client:
            return ""
        if not self._config.get("auto_recall", True):
            return ""
        if self._config.get("mode", "hybrid") == "tools":
            return ""

        if self._config.get("recall_sync", False):
            try:
                result = self._client.recall(
                    query,
                    limit=int(self._config.get("recall_limit", 10)),
                    token_budget=int(self._config.get("token_budget", 2048)),
                )
                text = self._format_recall_block(result.memories, result.scores)
                self._last_recall_count = len(result.memories)
                self._last_recall_returned = bool(text)
                return text
            except Exception:
                logging.getLogger(__name__).exception("sync recall failed")
                return ""

        # Cached path: join the worker briefly, then drain the cache.
        if self._prefetch_thread is not None and self._prefetch_thread.is_alive():
            self._prefetch_thread.join(timeout=3.0)
        with self._prefetch_lock:
            cached = self._prefetch_cache
            self._prefetch_cache = None
        if cached is None:
            return ""
        text, count = cached
        self._last_recall_count = count
        self._last_recall_returned = bool(text)
        return text

    def recall_status(self):
        """Return the deterministic RecallStatus for the last prefetch."""
        from agent.memory_provider import RecallStatus

        if not self._config.get("recall_indicator", True):
            return None
        if not getattr(self, "_last_recall_returned", False):
            return None
        return RecallStatus("Luminary", getattr(self, "_last_recall_count", 0), _LUMINARY_GLYPH)

    # ------------------------------------------------------------------ #
    # Backup
    # ------------------------------------------------------------------ #

    def backup_paths(self) -> list[str]:
        """Declare state paths outside HERMES_HOME (for ``hermes backup``).

        The default store lives under HERMES_HOME/luminary/, so it is already
        covered by a standard backup. Only a user-overridden ``db_path`` that
        points outside HERMES_HOME needs to be declared.
        """
        cfg_path = self._config.get("db_path", "") or ""
        if not cfg_path:
            return []
        home = self._hermes_home or os.environ.get(
            "HERMES_HOME", os.path.expanduser("~/.hermes")
        )
        resolved_home = os.path.abspath(os.path.expanduser(home))
        resolved_path = os.path.abspath(os.path.expanduser(cfg_path))
        if resolved_path.startswith(resolved_home + os.sep) or resolved_path == resolved_home:
            return []
        return [cfg_path]

    # ------------------------------------------------------------------ #
    # Tools
    # ------------------------------------------------------------------ #

    def _tool_error(self, message: str) -> str:
        return json.dumps({"error": message})

    def get_tool_schemas(self) -> list[dict]:
        """Expose luminary recall/ingest/list tools (empty in context mode)."""
        if self._config.get("mode", "hybrid") == "context":
            return []
        return [
            {
                "type": "function",
                "function": {
                    "name": "luminary_recall",
                    "description": "Recall relevant memories from the luminary store for a query.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Query text"},
                            "limit": {"type": "integer", "description": "Max results"},
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "luminary_ingest",
                    "description": "Store a new memory in the luminary store.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string", "description": "Memory content"},
                            "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags"},
                        },
                        "required": ["content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "luminary_list",
                    "description": "List recent memories from the luminary store (read-only).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "limit": {"type": "integer", "description": "Max results"},
                        },
                    },
                },
            },
        ]

    def _handle_recall(self, args: dict) -> str:
        query = args.get("query")
        if not query or not str(query).strip():
            return self._tool_error("luminary_recall requires a non-empty 'query'")
        try:
            result = self._client.recall(
                str(query),
                limit=int(args.get("limit") or self._config.get("recall_limit", 10)),
                token_budget=int(self._config.get("token_budget", 2048)),
            )
            payload = {
                "memories": [
                    {"id": m.id, "content": m.content, "tags": m.tags} for m in result.memories
                ],
                "scores": result.scores,
            }
            return json.dumps(payload)
        except Exception as exc:  # noqa: BLE001 -- tool errors are returned as JSON
            return self._tool_error(f"recall failed: {exc}")

    def _handle_ingest(self, args: dict) -> str:
        content = args.get("content")
        if not content or not str(content).strip():
            return self._tool_error("luminary_ingest requires non-empty 'content'")
        try:
            tags = args.get("tags") or []
            mid = self._client.ingest(str(content), tags=list(tags), source="hermes-tool")
            if mid is None:
                return json.dumps({"result": "Memory rejected by whitelist."})
            return json.dumps({"result": f"Memory stored (id={mid})."})
        except Exception as exc:  # noqa: BLE001 -- tool errors are returned as JSON
            return self._tool_error(f"ingest failed: {exc}")

    def _handle_list(self, args: dict) -> str:
        try:
            limit = int(args.get("limit") or 20)
            memories = self._client.list(limit=limit, offset=0)
            payload = [
                {"id": m.id, "content": m.content, "tags": m.tags} for m in memories
            ]
            return json.dumps({"memories": payload})
        except Exception as exc:  # noqa: BLE001 -- tool errors are returned as JSON
            return self._tool_error(f"list failed: {exc}")

    def handle_tool_call(self, name: str, args: dict) -> str:
        """Dispatch a tool call to the client and return a JSON string."""
        if not self._client:
            return self._tool_error("provider is not initialized")
        if name == "luminary_recall":
            return self._handle_recall(args)
        if name == "luminary_ingest":
            return self._handle_ingest(args)
        if name == "luminary_list":
            return self._handle_list(args)
        return self._tool_error(f"unknown tool: {name}")
