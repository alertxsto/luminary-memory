"""Hermes memory provider package for luminary-memory.

This package registers luminary-memory as a Hermes ``MemoryProvider`` through the
``hermes_agent.memory_providers`` entry-point group. It is the standalone,
pip-installable integration surface (see ``docs/hermes-integration.md``).
"""

__all__ = ["LuminaryMemoryProvider", "register"]


def __getattr__(name: str):
    """Load the Hermes runtime adapter only when Hermes asks for it."""

    if name == "LuminaryMemoryProvider":
        from luminary_memory.hermes.provider import LuminaryMemoryProvider

        return LuminaryMemoryProvider
    raise AttributeError(name)


def register(ctx) -> None:
    """Register the provider with a Hermes plugin context."""

    from luminary_memory.hermes.provider import LuminaryMemoryProvider

    ctx.register_memory_provider(LuminaryMemoryProvider())
