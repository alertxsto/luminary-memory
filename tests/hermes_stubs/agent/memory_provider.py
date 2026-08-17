"""Test stub for the hermes-agent MemoryProvider ABC.

This module mirrors the *signatures* of ``agent.memory_provider`` from the
hermes-agent tree (authoritative source: hermes-agent/agent/memory_provider.py).
It is injected into ``sys.modules`` by ``tests/conftest.py`` so that luminary's
own tests can import the provider without a hermes-agent install.

Only signatures are mirrored; bodies are no-ops. Runtime behavior always uses
the real ABC from the hermes-agent package.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class RecallStatus:
    """Deterministic memory-use indicator."""

    provider_label: str
    count: int
    glyph: str


def is_trivial_prompt(text: str) -> bool:
    """Return True for prompts that should skip recall (e.g. single tokens)."""
    return len((text or "").strip().split()) < 2


class MemoryProvider(ABC):
    """Memory provider interface (mirrored signatures)."""

    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    def is_available(self) -> bool:
        return True

    def unavailable_reason(self) -> str:
        return ""

    def initialize(self, session_id: str, **kwargs) -> None:
        pass

    def system_prompt_block(self) -> str:
        return ""

    def prefetch(self, query: str, session_id: str) -> str:
        return ""

    def queue_prefetch(self, query: str, session_id: str) -> None:
        pass

    def recall_status(self):
        return None

    def sync_turn(self, user: str, assistant: str, **kwargs) -> None:
        pass

    def get_tool_schemas(self) -> list[dict]:
        return []

    def handle_tool_call(self, name: str, args: dict) -> str:
        return '{"error": "unknown tool"}'

    def shutdown(self) -> None:
        pass

    def on_session_end(self, messages) -> None:
        pass

    def on_session_switch(self, new_session_id: str, **kwargs) -> None:
        pass

    def on_pre_compress(self, messages) -> str:
        return ""

    def on_delegation(self, task, result, child_session_id: str = "") -> None:
        pass

    def on_memory_write(self, action: str, target: str, content: str, metadata=None) -> None:
        pass

    def get_config_schema(self) -> list[dict]:
        return []

    def save_config(self, values: dict) -> None:
        pass

    def backup_paths(self) -> list[str]:
        return []
