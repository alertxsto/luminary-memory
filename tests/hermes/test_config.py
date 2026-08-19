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


def test_persistent_context_keys_removed():
    """v0.2.18 removed the persistent-context family (context_top_n & co)."""
    from luminary_memory.hermes import config_schema
    from luminary_memory.hermes.config import _DEFAULTS

    keys = {f["key"] for f in config_schema.CONFIG_SCHEMA.fields}
    assert "context_top_n" not in keys
    assert "context_budget" not in keys
    assert "context_min_importance" not in keys
    assert "context_top_n" not in _DEFAULTS
    assert "context_budget" not in _DEFAULTS
    assert "context_min_importance" not in _DEFAULTS
