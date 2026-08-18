"""T3: Provider config layer + schema."""

import os
import stat

from luminary_memory.hermes.provider import LuminaryMemoryProvider


def test_save_config_writes_0600_and_roundtrips(tmp_path):
    from luminary_memory.hermes.config import load_config, save_config

    save_config({"backend": "pgvector"}, str(tmp_path))

    cfg_path = tmp_path / "luminary" / "config.json"
    assert cfg_path.exists(), "config.json was not written"
    mode = stat.S_IMODE(os.stat(cfg_path).st_mode)
    assert mode == 0o600, f"expected 0600, got {oct(mode)}"

    loaded = load_config(str(tmp_path))
    assert loaded["backend"] == "pgvector"
    assert loaded["mode"] == "hybrid"  # default filled for unspecified keys


def test_load_config_defaults_when_missing(tmp_path):
    from luminary_memory.hermes.config import load_config

    cfg = load_config(str(tmp_path))
    assert cfg["mode"] == "hybrid"
    assert cfg["backend"] == "sqlite"
    assert cfg["auto_recall"] is True
    assert cfg["recall_limit"] == 10
    assert cfg["token_budget"] == 2048


def test_get_config_schema_shape():
    p = LuminaryMemoryProvider()
    schema = p.get_config_schema()

    assert isinstance(schema, list) and schema
    for field in schema:
        assert "key" in field, "each schema field must carry a 'key'"

    by_key = {f["key"]: f for f in schema}
    mode = by_key["mode"]
    assert mode["choices"] == ["context", "tools", "hybrid"]

    llm_key = by_key["llm_api_key"]
    assert llm_key.get("secret") is True
    assert llm_key.get("env_var") == "LUMINARY_LLM_API_KEY"


def test_config_schema_module_is_pure_data():
    """config_schema.py must import without the agent runtime (dashboard path)."""
    from luminary_memory.hermes import config_schema

    schema = config_schema.CONFIG_SCHEMA
    assert schema.name == "luminary"
    assert schema.label == "Luminary Memory"
    assert schema.storage == "flat_json"
    assert schema.fields


def test_config_schema_standalone_shim(monkeypatch):
    """Fallback shim (no hermes runtime) exposes the same schema shape."""
    import sys

    # Block 'plugins' to simulate standalone install
    monkeypatch.setitem(sys.modules, "plugins", None)
    monkeypatch.setitem(sys.modules, "plugins.memory", None)
    monkeypatch.setitem(sys.modules, "plugins.memory.config_schema", None)

    import importlib

    from luminary_memory.hermes import config_schema
    importlib.reload(config_schema)

    schema = config_schema.CONFIG_SCHEMA
    assert schema.name == "luminary"
    assert schema.label == "Luminary Memory"
    assert schema.storage == "flat_json"
    assert schema.fields

    keys = [f["key"] for f in schema.fields]
    assert "auto_maintain" in keys
    assert "ingest_llm" in keys
    assert len(schema.fields) >= 18


def test_context_env_vars_map_to_settings(monkeypatch):
    """LUMINARY_CONTEXT_* env vars must exist and drive Settings defaults."""
    from luminary_memory.config import Settings

    monkeypatch.setenv("LUMINARY_CONTEXT_TOP_N", "12")
    monkeypatch.setenv("LUMINARY_CONTEXT_BUDGET", "3000")
    monkeypatch.setenv("LUMINARY_CONTEXT_MIN_IMPORTANCE", "0.5")

    s = Settings()
    assert s.context_top_n == 12
    assert s.context_budget == 3000
    assert s.context_min_importance == 0.5


def test_context_env_vars_drive_provider_persistent_context(tmp_path, monkeypatch):
    """The provider's persistent-context build honours LUMINARY_CONTEXT_*."""
    from luminary_memory.hermes.provider import LuminaryMemoryProvider

    monkeypatch.setenv("LUMINARY_CONTEXT_TOP_N", "2")
    monkeypatch.setenv("LUMINARY_CONTEXT_BUDGET", "2000")
    monkeypatch.setenv("LUMINARY_CONTEXT_MIN_IMPORTANCE", "0.0")

    p = LuminaryMemoryProvider()
    p.initialize("s1", hermes_home=str(tmp_path), platform="cli", agent_identity="test")

    class _E:
        def embed(self, t): return [0.1, 0.1, 0.1]
        def embed_batch(self, ts): return [[0.1, 0.1, 0.1] for _ in ts]

    p._client.engine = _E()
    for i in range(5):
        p._client.ingest(f"fact number {i}", tags=["t"], source="test")

    block = p._build_persistent_context()
    # top_n=2 -> only 2 memories injected
    assert block.count("\n- ") == 2
    p.shutdown()


def test_explicit_config_overrides_env_context(tmp_path, monkeypatch):
    """A config.json value that differs from default wins over the env var
    (dashboard edits must stay authoritative)."""
    from luminary_memory.hermes.config import save_config
    from luminary_memory.hermes.provider import LuminaryMemoryProvider

    monkeypatch.setenv("LUMINARY_CONTEXT_TOP_N", "2")
    save_config({"context_top_n": 5}, str(tmp_path))

    p = LuminaryMemoryProvider()
    p.initialize("s1", hermes_home=str(tmp_path), platform="cli", agent_identity="test")

    class _E:
        def embed(self, t): return [0.1, 0.1, 0.1]
        def embed_batch(self, ts): return [[0.1, 0.1, 0.1] for _ in ts]

    p._client.engine = _E()
    for i in range(8):
        p._client.ingest(f"fact number {i}", tags=["t"], source="test")

    block = p._build_persistent_context()
    assert block.count("\n- ") == 5, "config.json value (5) must override env (2)"
    p.shutdown()
