"""Pytest bootstrap: inject a fake ``agent.memory_provider`` module.

This lets the provider code import ``agent.memory_provider`` inside the
luminary-memory test suite without a hermes-agent install. The stub mirrors
the real ABC signatures only (see tests/hermes_stubs/agent/memory_provider.py).
"""

import importlib.util
import sys
import types
from pathlib import Path

_STUB_PATH = Path(__file__).parent / "hermes_stubs" / "agent" / "memory_provider.py"


def _ensure_agent_stub() -> None:
    if "agent.memory_provider" in sys.modules:
        return
    agent = types.ModuleType("agent")
    agent.__path__ = []  # mark as a package
    spec = importlib.util.spec_from_file_location("agent.memory_provider", _STUB_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["agent"] = agent
    sys.modules["agent.memory_provider"] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)


_ensure_agent_stub()
