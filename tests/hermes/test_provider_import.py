"""T2: The provider package must import and expose the provider class."""

from luminary_memory.hermes.provider import LuminaryMemoryProvider


def test_provider_importable():
    """LuminaryMemoryProvider can be imported from the provider module."""
    from luminary_memory.hermes.provider import LuminaryMemoryProvider as P

    assert P is not None


def test_provider_name():
    """The provider reports its name as 'luminary'."""
    assert LuminaryMemoryProvider().name == "luminary"


def test_register_callback():
    """register() wires the provider into a plugin context."""
    from luminary_memory.hermes import register

    calls = []

    class _Ctx:
        def register_memory_provider(self, provider):
            calls.append(provider)

    register(_Ctx())
    assert calls and calls[0].name == "luminary"
