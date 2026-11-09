"""Hermes profile settings adapter: revision-bound, secret-free, profile-typed."""
from __future__ import annotations

import json
import sys
import types

import pytest

from luminary_memory.hermes.config import load_config
from luminary_memory.hermes.inspector_settings import HermesSettingsAdapter
from luminary_memory.inspector.mutations import Conflict


@pytest.fixture
def secrets(monkeypatch):
    module = types.ModuleType("agent.secret_scope")
    present = {"LUMINARY_LLM_API_KEY": "configured", "LUMINARY_PG_DSN": ""}
    module.get_secret = lambda key: present.get(key, "")
    monkeypatch.setitem(sys.modules, "agent", types.ModuleType("agent"))
    monkeypatch.setitem(sys.modules, "agent.secret_scope", module)
    return present


@pytest.fixture
def bound(tmp_path, secrets):
    from types import SimpleNamespace

    return HermesSettingsAdapter(str(tmp_path)), SimpleNamespace(profile_id=str(tmp_path.resolve()))


def test_read_reports_editable_fields_without_secret_values(bound, secrets):
    adapter, context = bound
    result = adapter.read(context)
    assert result["secret_presence"] == {"llm_api_key": True, "pg_dsn": False}
    assert "llm_api_key" not in result["values"]
    assert "pg_dsn" not in result["values"]
    assert "configured" not in json.dumps(result)
    assert result["readiness"]["provider_restart_required"] is True
    assert result["revision"] == adapter.read(context)["revision"]


def test_read_is_refused_after_the_native_profile_changes(bound, tmp_path):
    from types import SimpleNamespace

    adapter, _ = bound
    with pytest.raises(PermissionError, match="profile changed"):
        adapter.read(SimpleNamespace(profile_id=str(tmp_path / "other")))


def test_apply_requires_the_observed_revision(bound):
    adapter, context = bound
    with pytest.raises(Conflict):
        adapter.apply(context, {"recall_limit": 5}, "stale-revision", on_external_effect=lambda: None)


def test_apply_persists_only_editable_typed_values(bound, tmp_path):
    adapter, context = bound
    revision = adapter.read(context)["revision"]
    effects = []
    result = adapter.apply(context, {"recall_limit": 9, "auto_retain": False},
                           revision, on_external_effect=lambda: effects.append(True))
    assert effects == [True]
    assert (result["values"]["recall_limit"], result["values"]["auto_retain"]) == (9, False)
    assert load_config(str(tmp_path))["recall_limit"] == 9
    assert result["revision"] != revision


@pytest.mark.parametrize("changes", [
    {},
    {"db_path": "/etc/secrets.db"},
    {"llm_api_key": "leak"},
    {"pg_dsn": "postgresql://x"},
    {"unknown_key": 1},
])
def test_apply_refuses_uneditable_or_empty_changes(bound, changes):
    adapter, context = bound
    revision = adapter.read(context)["revision"]
    with pytest.raises(PermissionError, match="Unsupported Hermes setting"):
        adapter.apply(context, changes, revision, on_external_effect=lambda: None)


@pytest.mark.parametrize("key,value", [
    ("auto_retain", "false"),
    ("auto_retain", 0),
    ("recall_limit", "9"),
    ("recall_limit", -1),
    ("importance_recall_boost", "high"),
    ("importance_recall_boost", -0.1),
    ("importance_recall_boost", 1001),
    ("mode", "sideways"),
    ("core_tag", 5),
    ("core_tag", "x" * 5000),
])
def test_apply_rejects_values_that_do_not_match_the_native_type(bound, key, value):
    adapter, context = bound
    revision = adapter.read(context)["revision"]
    with pytest.raises(ValueError, match="Invalid Hermes setting value"):
        adapter.apply(context, {key: value}, revision, on_external_effect=lambda: None)
    assert load_config(adapter.home)[key] != value
