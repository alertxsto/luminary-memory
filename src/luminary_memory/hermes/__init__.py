"""Hermes memory provider package for luminary-memory.

This package registers luminary-memory as a Hermes ``MemoryProvider`` through the
``hermes_agent.memory_providers`` entry-point group. It is the standalone,
pip-installable integration surface (see PLAN-v0.2.1.md §2.3).
"""

from luminary_memory.hermes.provider import LuminaryMemoryProvider

__all__ = ["LuminaryMemoryProvider", "register"]


def register(ctx) -> None:
    """Register the provider with a Hermes plugin context."""
    ctx.register_memory_provider(LuminaryMemoryProvider())
