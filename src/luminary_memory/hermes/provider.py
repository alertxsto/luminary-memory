"""LuminaryMemoryProvider — Hermes memory provider implementation.

The provider imports the ``MemoryProvider`` ABC from ``agent.memory_provider``,
which exists only in the hermes-agent runtime. Tests inject a faithful stub via
``tests/conftest.py`` (see tests/hermes_stubs/agent/memory_provider.py); at
runtime the real ABC is used.
"""

from agent.memory_provider import MemoryProvider  # present only in hermes runtime

_LUMINARY_GLYPH = "🌙"


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
