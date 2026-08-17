"""LuminaryMemoryProvider — Hermes memory provider implementation.

The provider imports the ``MemoryProvider`` ABC from ``agent.memory_provider``,
which exists only in the hermes-agent runtime. Tests inject a faithful stub via
``tests/conftest.py`` (see tests/hermes_stubs/agent/memory_provider.py); at
runtime the real ABC is used.
"""

from agent.memory_provider import MemoryProvider  # present only in hermes runtime

from luminary_memory.hermes.config import _DEFAULTS, save_config

_LUMINARY_GLYPH = "🌙"

_MODE_CHOICES = ["context", "tools", "hybrid"]


class LuminaryMemoryProvider(MemoryProvider):
    """Hermes memory provider backed by the luminary-memory store."""

    @property
    def name(self) -> str:
        return "luminary"

    def is_available(self) -> bool:
        """Return True when the provider can activate (no network, no store)."""
        return True

    def initialize(self, session_id: str, **kwargs) -> None:
        """Initialize provider state for a session (stub; lifecycle lands in T4)."""

    def shutdown(self) -> None:
        """Release provider resources (stub; lifecycle lands in T4)."""

    def get_tool_schemas(self) -> list[dict]:
        """Expose model-callable tool schemas (tools land in T10)."""
        return []

    def get_config_schema(self) -> list[dict]:
        """Declare the config fields surfaced by ``hermes memory setup``."""
        schema = [
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
        return schema

    def save_config(self, values: dict) -> None:
        """Persist config values to the provider config file."""
        hermes_home = getattr(self, "_hermes_home", None)
        if not hermes_home:
            raise RuntimeError("provider is not initialized; cannot save config")
        save_config(values, hermes_home)
