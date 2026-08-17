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
