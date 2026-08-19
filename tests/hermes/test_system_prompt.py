"""T5: Provider system prompt block (mode-aware)."""

from luminary_memory.hermes.provider import LuminaryMemoryProvider


def _init_provider(tmp_path, mode="hybrid"):
    p = LuminaryMemoryProvider()
    p.initialize("s1", hermes_home=str(tmp_path), platform="cli")
    p._config["mode"] = mode
    return p


def test_uninitialized_returns_empty():
    p = LuminaryMemoryProvider()
    assert p.system_prompt_block() == ""


def test_hybrid_mode_mentions_recall_and_injection(tmp_path):
    p = _init_provider(tmp_path, mode="hybrid")
    block = p.system_prompt_block()
    assert "luminary_recall" in block
    assert "Important memories are recalled on demand" in block
    p.shutdown()


def test_tools_mode_no_injection(tmp_path):
    p = _init_provider(tmp_path, mode="tools")
    block = p.system_prompt_block()
    assert "luminary_recall" in block
    assert "automatically injected" not in block
    p.shutdown()


def test_context_mode_no_tool_mention(tmp_path):
    p = _init_provider(tmp_path, mode="context")
    block = p.system_prompt_block()
    assert "luminary_recall" not in block
    assert "Important memories are recalled on demand" in block
    p.shutdown()
