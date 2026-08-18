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
    _seed_core(p, ["WAJIB pakai markdown table di Telegram"])
    block = p.system_prompt_block()
    assert "Core memory (auto-loaded every session)" in block
    assert "markdown table" in block
    p.shutdown()


def test_core_block_before_persistent_context(tmp_path):
    p = _init_provider(tmp_path)
    _seed_core(p, ["rule inti format tabel"])
    # A non-core high-importance memory that would land in persistent context.
    p._client.settings.rule_auto_replace = False
    p._client.ingest("fakta biasa deploy cluster", tags=["biasa"], source="test")
    block = p.system_prompt_block()
    core_idx = block.find("Core memory (auto-loaded")
    ctx_idx = block.find("Key memories")
    assert core_idx != -1 and ctx_idx != -1
    assert core_idx < ctx_idx, "core block must come before persistent context"
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
    out = p.handle_tool_call("luminary_core_add", {"content": "WAJIB table untuk semua laporan"})
    data = json.loads(out)
    assert "Core memory stored" in data["result"]
    mems = [m for m in p._client.list(limit=0) if "table untuk semua" in m.content]
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


def test_core_block_included_in_prefetch_context(tmp_path):
    p = _init_provider(tmp_path)
    _seed_core(p, ["aturan format tabel WAJIB di semua output"])
    p._config["recall_sync"] = True
    result = p.prefetch("riset teknologi x y z", session_id="s1")
    assert "Core memory (auto-loaded every session)" in result
    assert "format tabel WAJIB" in result
    p.shutdown()
