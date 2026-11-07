"""Behavioral regressions at Hermes's typed settings and profile boundaries."""
from __future__ import annotations

import contextvars
import json
import sys
import threading
import types

import pytest

from luminary_memory.hermes.config import load_config, save_config
from luminary_memory.hermes.provider import LuminaryMemoryProvider


def test_typed_dashboard_select_roundtrips_through_cli_setup(tmp_path, hermes_config_sdk):
    from luminary_memory.hermes.config_schema import CONFIG_SCHEMA

    fields = {field.key: field for field in CONFIG_SCHEMA.fields}
    assert fields["mode"].allowed_values() == {"context", "tools", "hybrid"}
    assert fields["backend"].allowed_values() == {"sqlite", "pgvector"}
    assert fields["auto_retain"].kind == "bool"
    assert fields["llm_api_key"].is_secret
    assert fields["llm_api_key"].env_key == "LUMINARY_LLM_API_KEY"
    descriptors = {field["key"]: field for field in LuminaryMemoryProvider().get_config_schema()}
    assert descriptors["mode"]["choices"] == ["context", "tools", "hybrid"]
    assert descriptors["auto_retain"]["type"] == "boolean"
    save_config({"mode": "tools", "auto_retain": False, "recall_limit": 7}, str(tmp_path))
    loaded = load_config(str(tmp_path))
    assert (loaded["mode"], loaded["auto_retain"], loaded["recall_limit"]) == ("tools", False, 7)


def test_secret_never_written_to_flat_settings(tmp_path):
    save_config({"llm_api_key": "do-not-serialize", "auto_retain": False}, str(tmp_path))
    stored = json.loads((tmp_path / "luminary" / "config.json").read_text())
    assert "llm_api_key" not in stored
    assert stored["auto_retain"] is False


def test_setup_does_not_activate_sibling_profiles(tmp_path):
    sibling = tmp_path / "profiles" / "work" / "config.yaml"
    sibling.parent.mkdir(parents=True)
    sibling.write_text("memory:\n  provider: other\n")
    LuminaryMemoryProvider().post_setup(str(tmp_path), {})
    assert sibling.read_text() == "memory:\n  provider: other\n"


def test_retain_worker_inherits_native_context(monkeypatch):
    profile = contextvars.ContextVar("native-profile", default="unscoped")
    provider = LuminaryMemoryProvider()
    observed = []
    ready = threading.Event()

    def consume():
        observed.append(profile.get())
        ready.set()

    monkeypatch.setattr(provider, "_writer_loop", consume)
    token = profile.set("profile-a")
    try:
        provider._start_writer()
        assert ready.wait(2)
        provider._writer_thread.join(2)
    finally:
        profile.reset(token)
    assert observed == ["profile-a"]


def test_profile_secret_beats_global_or_legacy_key(tmp_path, monkeypatch):
    scoped = types.ModuleType("agent.secret_scope")
    scoped.get_secret = lambda name, default=None: "native-scoped-key" if name == "LUMINARY_LLM_API_KEY" else default
    monkeypatch.setitem(sys.modules, "agent.secret_scope", scoped)
    monkeypatch.setenv("LUMINARY_LLM_API_KEY", "wrong-process-profile")
    provider = LuminaryMemoryProvider()
    provider.initialize("s1", hermes_home=str(tmp_path), agent_identity="profile-a")
    try:
        assert provider._build_settings(provider._resolve_db_path()).llm_api_key == "native-scoped-key"
    finally:
        provider.shutdown()


def test_native_session_scope_ignores_frontend_authority(tmp_path, monkeypatch):
    from luminary_memory.hermes.inspector import native_session_context

    constants = types.ModuleType("hermes_constants")
    constants.get_hermes_home = lambda: tmp_path
    constants.profile_name_for_home = lambda home: "work"
    state = types.ModuleType("hermes_state")

    class SessionDB:
        def __init__(self, *, read_only):
            assert read_only is True

        def get_session(self, session_id):
            return {"id": "s1", "cwd": str(tmp_path / "project"), "source": "cli"} if session_id == "s1" else None

        def close(self):
            pass

    state.SessionDB = SessionDB
    monkeypatch.setitem(sys.modules, "hermes_constants", constants)
    monkeypatch.setitem(sys.modules, "hermes_state", state)
    context = native_session_context("s1")
    assert context["workspace"] == str(tmp_path / "project")
    assert context["session_id"] == "s1"
    assert context["profile_id"] == str(tmp_path.resolve())
    assert context["agent_id"] == "work"
    with pytest.raises(PermissionError):
        native_session_context("guessed-foreign-session")


def test_complete_native_session_maps_provider_scope_not_cwd(tmp_path, monkeypatch):
    from luminary_memory.hermes.inspector import native_session_context

    constants = types.ModuleType("hermes_constants")
    constants.get_hermes_home = lambda: tmp_path
    constants.profile_name_for_home = lambda home: "work"
    state = types.ModuleType("hermes_state")

    class SessionDB:
        def __init__(self, *, read_only):
            assert read_only is True

        def get_session(self, session_id):
            return {"id": session_id, "cwd": str(tmp_path / "project"),
                    "profile_name": "work", "user_id": "native-owner", "source": "telegram"}

        def close(self):
            pass

    state.SessionDB = SessionDB
    monkeypatch.setitem(sys.modules, "hermes_constants", constants)
    monkeypatch.setitem(sys.modules, "hermes_state", state)
    context = native_session_context("s1")
    assert context["user_id"] == "native-owner"
    assert context["workspace_id"] == "hermes"
    assert context["workspace"] == str(tmp_path / "project")


def test_legacy_scope_requires_explicit_complete_owner_binding(tmp_path):
    from luminary_memory.hermes.inspector import provider_record_scope

    native = {"profile_id": str(tmp_path), "agent_id": "work"}
    with pytest.raises(PermissionError, match="inspector-bind"):
        provider_record_scope(native)
    directory = tmp_path / "luminary"
    directory.mkdir()
    binding = directory / "inspector.json"
    binding.write_text(json.dumps({"owner_user_id": "owner", "record_scope": {
        "user_id": "owner", "workspace_id": "hermes", "agent_id": "work"}}))
    assert provider_record_scope(native) == {
        "user_id": "owner", "workspace_id": "hermes", "agent_id": "work"}
    binding.write_text(json.dumps({"owner_user_id": "owner", "record_scope": {
        "user_id": "", "workspace_id": "hermes", "agent_id": "work"}}))
    with pytest.raises(PermissionError, match="unowned"):
        provider_record_scope(native)


def test_cli_string_values_persist_as_typed_options(tmp_path):
    provider = LuminaryMemoryProvider()
    provider.save_config({"auto_retain": "false", "recall_limit": "7",
                          "importance_recall_boost": "0.5"}, str(tmp_path))
    stored = load_config(str(tmp_path))
    assert stored["auto_retain"] is False
    assert stored["recall_limit"] == 7
    assert stored["importance_recall_boost"] == 0.5


def test_cli_descriptor_exposes_native_description_and_choices(hermes_config_sdk):
    schema = {field["key"]: field for field in LuminaryMemoryProvider().get_config_schema()}
    assert schema["mode"]["description"]
    assert schema["mode"]["type"] == "text"
    assert schema["recall_limit"]["type"] == "integer"


def test_native_settings_persist_revision_and_reject_foreign_profile(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from luminary_memory.hermes.inspector_settings import HermesSettingsAdapter
    from luminary_memory.inspector.mutations import Conflict

    secrets = types.ModuleType("agent.secret_scope")
    secrets.get_secret = lambda name, default=None: "never-return-this" if name == "LUMINARY_LLM_API_KEY" else default
    monkeypatch.setitem(sys.modules, "agent.secret_scope", secrets)
    adapter = HermesSettingsAdapter(str(tmp_path))
    context = SimpleNamespace(profile_id=str(tmp_path))
    original = adapter.read(context)
    assert original["secret_presence"] == {"llm_api_key": True, "pg_dsn": False}
    assert "never-return-this" not in json.dumps(original)
    saved = adapter.apply(context, {"auto_retain": False}, original["revision"],
                          on_external_effect=lambda: None)
    assert saved["revision"] != original["revision"]
    assert load_config(str(tmp_path))["auto_retain"] is False
    with pytest.raises(Conflict):
        adapter.apply(context, {"auto_retain": True}, original["revision"],
                      on_external_effect=lambda: None)
    with pytest.raises(PermissionError):
        adapter.read(SimpleNamespace(profile_id=str(tmp_path / "sibling")))


def test_native_cli_consumes_typed_fields_without_provider_activation(tmp_path, monkeypatch, hermes_config_sdk):
    import argparse

    from luminary_memory.hermes.cli import register_cli

    constants = types.ModuleType("hermes_constants")
    constants.get_hermes_home = lambda: tmp_path
    monkeypatch.setitem(sys.modules, "hermes_constants", constants)
    config = tmp_path / "config.yaml"
    config.write_text("memory:\n  provider: other\n")
    parser = argparse.ArgumentParser()
    register_cli(parser)
    args = parser.parse_args(["configure", "--set", "auto_retain=false", "--set", "recall_limit=7"])
    assert args.func(args) == 0
    assert load_config(str(tmp_path))["auto_retain"] is False
    assert load_config(str(tmp_path))["recall_limit"] == 7
    assert config.read_text() == "memory:\n  provider: other\n"


def test_binding_cannot_override_complete_native_session_identity(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from luminary_memory.hermes import inspector
    from luminary_memory.hermes.cli import bind_inspector

    monkeypatch.setattr(inspector, "native_session_context", lambda session: {
        "profile_id": str(tmp_path), "agent_id": "work", "user_id": "native-owner",
        "workspace_id": "hermes", "workspace": str(tmp_path)})
    args = SimpleNamespace(session="s1", agent="work", owner="someone-else",
                           user="someone-else", workspace="hermes")
    with pytest.raises(PermissionError, match="native session"):
        bind_inspector(args)
    assert not (tmp_path / "luminary" / "inspector.json").exists()


def test_profile_settings_restart_preserves_native_writer_policy(tmp_path, hermes_config_sdk):
    from agent.secret_scope import reset_secret_scope, set_secret_scope

    from luminary_memory.hermes.inspector_settings import HermesSettingsAdapter
    from luminary_memory.inspector.contracts import ConsoleRequest
    from luminary_memory.inspector.identity import resolve_context
    from luminary_memory.inspector.service import InspectorService

    homes = [tmp_path / "disabled", tmp_path / "enabled"]
    for home, enabled in zip(homes, (False, True), strict=True):
        save_config({"auto_retain": enabled, "ingest_llm": False,
                     "token_budget": 1024, "retain_every_n_turns": 1}, str(home))
        (home / "config.yaml").write_text("memory:\n  provider: other\n", encoding="utf-8")
    sibling_before = (homes[1] / "luminary" / "config.json").read_bytes()
    providers = []

    def start(home, session):
        provider = LuminaryMemoryProvider()
        providers.append(provider)
        provider.initialize(session, hermes_home=str(home), user_id="native-owner",
                            agent_workspace="native-workspace", agent_identity="hermes", platform="cli")
        return provider

    token = set_secret_scope({"LUMINARY_LLM_API_KEY": "PROFILE_SECRET_NOT_RESPONSE"}, profile_home=str(homes[0]))
    try:
        first = start(homes[0], "disabled-session")
        native = {"user_id": "native-owner", "workspace": str(tmp_path), "workspace_id": "native-workspace",
                  "agent_id": "hermes", "session_id": "disabled-session", "host_id": "native-host",
                  "profile_id": str(homes[0])}
        context = resolve_context(first._client, native, initialize=True)
        service = InspectorService(first._client)
        service.settings_adapter = HermesSettingsAdapter(str(homes[0]))
        response = service.execute(context, ConsoleRequest(operation="get_settings", arguments={}, request_id="settings"))
        assert response.status == "ok", response.to_dict()
        assert response.data["values"]["backend"] == "sqlite"
        assert "PROFILE_SECRET_NOT_RESPONSE" not in json.dumps(response.to_dict())
        revision = response.data["revision"]
        preview = service.execute(context, ConsoleRequest(operation="preview_change", arguments={
            "kind": "set_settings", "changes": {"token_budget": 768}, "expected_revision": revision,
        }, request_id="preview"))
        assert preview.status == "ok", preview.to_dict()
        assert load_config(str(homes[0]))["token_budget"] == 1024  # preview/cancel has no configuration effect
        receipt = service.confirm(context, preview.data["preview_id"])
        committed = service.execute(context, ConsoleRequest(operation="set_settings", arguments={
            "preview_id": preview.data["preview_id"], "confirmation_receipt": receipt,
        }, request_id="commit"))
        assert committed.status == "ok", committed.to_dict()
        first.shutdown()
        restarted = start(homes[0], "disabled-session-restart")
        assert restarted._client.settings.token_budget == 768
        restarted.sync_turn("Orion deploys to staging.", "Recorded the deployment target.")
        restarted._retain_queue.join()
        assert restarted._client.backend.recent_episodes(scope=restarted._scope, include_global=False) == []
        assert restarted._client.backend.count() == 0
        assert (homes[1] / "luminary" / "config.json").read_bytes() == sibling_before
        for home in homes:
            assert (home / "config.yaml").read_text(encoding="utf-8") == "memory:\n  provider: other\n"
    finally:
        reset_secret_scope(token)
        for provider in providers:
            provider.shutdown()
            for handler in list(provider._log.handlers):
                handler.close()
                provider._log.removeHandler(handler)

    token = set_secret_scope({}, profile_home=str(homes[1]))
    started = len(providers)
    try:
        enabled = start(homes[1], "enabled-session")
        assert enabled._client.settings.token_budget == 1024
        enabled.sync_turn("Orion deploys to staging.", "Recorded the deployment target.")
        enabled._retain_queue.join()
        episodes = enabled._client.backend.recent_episodes(scope=enabled._scope, include_global=False)
        assert [row["session_id"] for row in episodes] == ["enabled-session"]
        assert enabled._client.backend.count() == 0  # raw turns never bypass the curation gate
    finally:
        for provider in providers[started:]:
            provider.shutdown()
            for handler in list(provider._log.handlers):
                handler.close()
                provider._log.removeHandler(handler)
        reset_secret_scope(token)


@pytest.mark.parametrize("failure", ["invalid_setting", "after_native_write", "database_commit"])
def test_native_settings_uncertain_completion_preserves_actual_profile_state(tmp_path, monkeypatch, hermes_config_sdk, failure):
    from contextlib import contextmanager

    from agent.secret_scope import reset_secret_scope, set_secret_scope

    from luminary_memory.hermes import inspector_settings
    from luminary_memory.inspector.contracts import ConsoleRequest
    from luminary_memory.inspector.identity import resolve_context
    from luminary_memory.inspector.service import InspectorService

    home = tmp_path / "owned-profile"
    save_config({"auto_retain": False, "ingest_llm": False, "token_budget": 1024}, str(home))
    token = set_secret_scope({}, profile_home=str(home))
    provider = LuminaryMemoryProvider()
    try:
        provider.initialize("owned-session", hermes_home=str(home), user_id="native-owner",
                            agent_workspace="native-workspace", agent_identity="hermes", platform="cli")
        native = {"user_id": "native-owner", "workspace": str(tmp_path), "workspace_id": "native-workspace",
                  "agent_id": "hermes", "session_id": "owned-session", "host_id": "native-host", "profile_id": str(home)}
        context = resolve_context(provider._client, native, initialize=True)
        service = InspectorService(provider._client)
        service.settings_adapter = inspector_settings.HermesSettingsAdapter(str(home))
        current = service.execute(context, ConsoleRequest(operation="get_settings", request_id="read"))
        preview = service.execute(context, ConsoleRequest(operation="preview_change", arguments={
            "kind": "set_settings", "changes": {"token_budget": -1 if failure == "invalid_setting" else 768},
            "expected_revision": current.data["revision"],
        }, request_id="preview"))
        assert preview.status == "ok", preview.to_dict()
        receipt = service.confirm(context, preview.data["preview_id"])
        backend = provider._client.backend
        original_save, original_transaction = inspector_settings.save_config, backend.transaction

        def failed_after_save(changes, profile):
            original_save(changes, profile)
            raise OSError("PRIVATE_NATIVE_FAILURE after writing profile")

        @contextmanager
        def failed_commit():
            outer = not backend.in_transaction
            with original_transaction():
                yield backend
                if outer:
                    raise OSError("PRIVATE_NATIVE_FAILURE at commit")

        with monkeypatch.context() as faults:
            if failure == "after_native_write":
                faults.setattr(inspector_settings, "save_config", failed_after_save)
            elif failure == "database_commit":
                faults.setattr(backend, "transaction", failed_commit)
            result = service.execute(context, ConsoleRequest(operation="set_settings", arguments={
                "preview_id": preview.data["preview_id"], "confirmation_receipt": receipt,
            }, request_id="commit"))
        assert result.status == ("invalid_request" if failure == "invalid_setting" else "unknown_outcome"), result.to_dict()
        assert "PRIVATE_NATIVE_FAILURE" not in json.dumps(result.to_dict())
        persisted = load_config(str(home))
        assert persisted["token_budget"] == (1024 if failure == "invalid_setting" else 768)
        assert persisted["auto_retain"] is False
        assert backend.count() == 0
    finally:
        provider.shutdown()
        for handler in list(provider._log.handlers):
            handler.close()
            provider._log.removeHandler(handler)
        reset_secret_scope(token)
