"""Core memory (DB-backed) — auto-loaded system prompt block + tools.

Core memories (tag 'core') are injected into the system prompt every session
before persistent context, so durable rules are always visible without a
query match — the DB-backed equivalent of Hermes' native MEMORY.md.
"""

from luminary_memory.hermes.provider import LuminaryMemoryProvider


class _FakeEngine:
    def embed(self, text: str) -> list[float]:
        return [0.25] * 384

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[0.25] * 384 for _ in texts]


def _init_provider(tmp_path, **overrides):
    p = LuminaryMemoryProvider()
    p.initialize("s1", hermes_home=str(tmp_path), platform="cli", agent_identity="test")
    p._config.update(overrides)
    p._client.engine = _FakeEngine()
    return p


def _seed_core(p, texts):
    tag = p._core_tag()
    p._client.settings.rule_auto_replace = False  # fake embeddings are collinear -> would merge
    for t in texts:
        p._client.ingest(t, tags=[tag], source="test")


def test_system_prompt_includes_core_block(tmp_path):
    p = _init_provider(tmp_path)
    _seed_core(p, ["always use markdown tables in Telegram"])
    block = p.system_prompt_block()
    assert "Core memory, auto-loaded every session" in block
    assert "markdown table" in block
    p.shutdown()


def test_core_budget_chars_respected(tmp_path):
    p = _init_provider(tmp_path)
    p._client.settings.core_budget = 50
    _seed_core(p, ["aturan format tabel yang sangat panjang sekali untuk test budget"]
                + ["aturan lain yang juga panjang untuk memastikan truncate"] * 3)
    core = p._build_core_memory()
    # budget counts chars of content, plus header + "- " prefix; cap at reasonable bound
    assert len(core) <= 50 + 200, f"core block too large: {len(core)}"
    p.shutdown()


def test_core_top_n_respected(tmp_path):
    p = _init_provider(tmp_path)
    p._client.settings.core_top_n = 2
    _seed_core(p, [f"rule inti nomor {i}" for i in range(5)])
    core = p._build_core_memory()
    assert core.count("\n- ") == 2
    p.shutdown()


def test_core_memories_go_to_injected_ids(tmp_path):
    p = _init_provider(tmp_path)
    _seed_core(p, ["aturan format tabel inti"])
    p._build_core_memory()
    with p._prefetch_lock:
        injected = set(p._injected_ids)
    core = [m for m in p._client.list(limit=0) if "tabel inti" in m.content]
    assert core and core[0].id in injected, "core memory must be tracked as injected"
    p.shutdown()


def test_core_tools_in_schema(tmp_path):
    p = _init_provider(tmp_path)
    names = {s["function"]["name"] for s in p.get_tool_schemas()}
    assert "luminary_core_add" in names
    assert "luminary_core_remove" in names
    assert "luminary_core_list" in names
    p.shutdown()


def test_core_add_tool_stores_and_pins(tmp_path):
    p = _init_provider(tmp_path)
    import json
    out = p.handle_tool_call("luminary_core_add", {"content": "always use markdown tables for all reports"})
    data = json.loads(out)
    assert "Core memory stored" in data["result"]
    mems = [m for m in p._client.list(limit=0) if "markdown tables" in m.content]
    assert len(mems) == 1
    assert p._core_tag() in (mems[0].tags or [])
    assert float(mems[0].importance or 0) >= 0.9, "core add must pin importance"
    p.shutdown()


def test_core_remove_tool_unpins_keeps_memory(tmp_path):
    p = _init_provider(tmp_path)
    import json
    out = p.handle_tool_call("luminary_core_add", {"content": "aturan inti deploy"})
    mid = None
    for m in p._client.list(limit=0):
        if "aturan inti deploy" in m.content:
            mid = m.id
    assert mid is not None
    out = p.handle_tool_call("luminary_core_remove", {"id": mid})
    data = json.loads(out)
    assert "removed from core" in data["result"]
    m = p._client.get(mid)
    assert m is not None, "memory must remain in store after unpin"
    assert p._core_tag() not in (m.tags or [])
    p.shutdown()


def test_core_remove_unknown_id_returns_error(tmp_path):
    p = _init_provider(tmp_path)
    import json
    out = p.handle_tool_call("luminary_core_remove", {"id": 99999})
    data = json.loads(out)
    assert "error" in data
    p.shutdown()


def test_core_list_returns_core_memories(tmp_path):
    p = _init_provider(tmp_path)
    import json
    _seed_core(p, ["aturan satu", "aturan dua"])
    out = p.handle_tool_call("luminary_core_list", {})
    data = json.loads(out)
    assert "core" in data
    assert len(data["core"]) >= 2
    p.shutdown()


def test_core_list_respects_provider_scope(tmp_path):
    import json

    from luminary_memory.api import MemoryClient
    from luminary_memory.ingest.llm import NoopEnricher

    p = LuminaryMemoryProvider()
    p.initialize(
        "s1",
        hermes_home=str(tmp_path),
        platform="cli",
        agent_identity="test",
        user_id="alice",
    )
    p._client.engine = _FakeEngine()
    p._client.ingest("alice scoped core", tags=[p._core_tag()])
    other = MemoryClient(
        db_path=str(tmp_path / "luminary" / "memory.db"),
        engine=_FakeEngine(),
        enricher=NoopEnricher(),
    )
    other.ingest("bob scoped core", tags=[p._core_tag()], user_id="bob")

    data = json.loads(p.handle_tool_call("luminary_core_list", {}))
    contents = {row["content"] for row in data["core"]}
    assert "alice scoped core" in contents
    assert "bob scoped core" not in contents
    other.close()
    p.shutdown()


def test_core_block_included_in_prefetch_context(tmp_path):
    p = _init_provider(tmp_path)
    _seed_core(p, ["always use markdown tables in all output"])
    p._config["recall_sync"] = True
    result = p.prefetch("riset teknologi x y z", session_id="s1")
    assert "Core memory, auto-loaded every session" in result
    assert "markdown tables" in result
    p.shutdown()


# ============================================================================
# Invariant tests (T2.x — core sourced from DB tag 'core', not recall/injected)
# ============================================================================

def test_core_sourced_only_from_db_tag(tmp_path):
    """Core block content comes ONLY from DB memories tagged 'core'."""
    p = _init_provider(tmp_path)
    _seed_core(p, ["aturan inti satu", "aturan inti dua"])
    block = p._build_core_memory()
    assert "aturan inti satu" in block
    assert "aturan inti dua" in block
    p.shutdown()


def test_core_never_sourced_from_recall_or_importance(tmp_path):
    """A high-importance non-core memory must NEVER appear in the core block.

    Proves the core block is fed by the DB 'core' tag, not by recall ranking,
    importance, or persistent-context selection.
    """
    p = _init_provider(tmp_path)
    _seed_core(p, ["rule inti pakai markdown table"])
    # A NON-core memory with maximum importance — would dominate any
    # importance/recall-based selection, but must NOT leak into core.
    p._client.settings.rule_auto_replace = False
    mid = p._client.ingest(
        "aturan sangat penting tapi bukan core memory", tags=["biasa"], source="test")
    assert mid is not None
    m = p._client.get(mid)
    m.importance = 1.0
    p._client.update(m)

    block = p._build_core_memory()
    assert "markdown table" in block
    assert "bukan core memory" not in block, "non-core memory leaked into core block"
    p.shutdown()


def test_core_content_independent_of_injected_ids(tmp_path):
    """Clearing _injected_ids must NOT change the core block content."""
    p = _init_provider(tmp_path)
    _seed_core(p, ["aturan inti stabil"])
    with p._prefetch_lock:
        p._injected_ids = set()
    block = p._build_core_memory()
    assert "aturan inti stabil" in block
    p.shutdown()


def test_core_budget_skips_oversized_top_row_and_keeps_later_rule(tmp_path):
    p = _init_provider(tmp_path)
    p._client.settings.core_top_n = 2
    p._client.settings.core_budget = 24
    tag = p._core_tag()
    p._client.ingest("this core rule is much too long for the budget", tags=[tag], importance=1.0)
    p._client.ingest("short core rule", tags=[tag], importance=0.8)

    block = p._build_core_memory()
    assert "this core rule is much too long" not in block
    assert "short core rule" in block
    core_ids, core_hashes = p._core_identifiers()
    assert len(core_ids) == 1
    assert len(core_hashes) == 1
    p.shutdown()


def test_core_add_promotes_exact_duplicate_without_creating_second_row(tmp_path):
    p = _init_provider(tmp_path)
    content = "always keep the deploy target evidence grounded"
    p._client.ingest(content, tags=["ordinary"], source="test", **p._operation_scope())

    import json

    out = p.handle_tool_call("luminary_core_add", {"content": content})
    data = json.loads(out)
    assert "Core memory stored" in data["result"]
    matching = [m for m in p._client.list(limit=0) if m.content == content]
    assert len(matching) == 1
    assert p._core_tag() in (matching[0].tags or [])
    assert matching[0].importance >= p._client.settings.rule_importance
    p.shutdown()


def test_core_and_persistent_same_memory_not_duplicated(tmp_path):
    """The same memory surfaced by core AND persistent context appears once."""
    p = _init_provider(tmp_path)
    p._client.settings.rule_auto_replace = False
    # High-importance non-core memory that would be picked by persistent context
    p._client.ingest("aturan sering dipakai biar muncul di persistent", tags=["biasa"],
                     source="test")
    # Same content ALSO stored as core
    _seed_core(p, ["aturan sering dipakai biar muncul di persistent"])
    p._config["recall_sync"] = True
    result = p.prefetch("apa aturan yang sering dipakai?", session_id="s1")
    # Whole block: core + persistent + recall must contain the content exactly once
    assert result.count("aturan sering dipakai biar muncul di persistent") == 1, \
        "memory must appear exactly once across core/persistent/recall"
    p.shutdown()


def test_injected_ids_union_skips_recall_duplicates(tmp_path):
    """_injected_ids holds core+persistent ids; recall block skips them."""
    p = _init_provider(tmp_path)
    _seed_core(p, ["aturan format tabel yang inti"])
    p._build_core_memory()
    with p._prefetch_lock:
        injected = set(p._injected_ids)
    assert injected, "core build must populate _injected_ids"
    # Simulate a recall that returns the same memory
    core_mem = next(m for m in p._client.list(limit=0) if "format tabel" in m.content)
    from luminary_memory.types import Memory
    fake = Memory(id=core_mem.id, content=core_mem.content)
    block = p._format_recall_block([fake], [0.9])
    assert "format tabel" not in block, "recall block must skip an already-injected id"
    p.shutdown()
