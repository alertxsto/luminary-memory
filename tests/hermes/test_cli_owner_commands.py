"""Hermes owner commands: binding persistence and typed settings without activation."""
from __future__ import annotations

import argparse
import json
import sys
import types

import pytest

from luminary_memory.hermes.cli import bind_inspector, configure, register_cli


def native_profile(tmp_path, monkeypatch, **overrides):
    from luminary_memory.hermes import inspector

    native = {"profile_id": str(tmp_path), "agent_id": "work", "user_id": "native-owner",
              "workspace_id": "hermes", "workspace": str(tmp_path / "project"),
              "session_id": "s1", **overrides}
    monkeypatch.setattr(inspector, "native_session_context", lambda session: dict(native))
    return native


def owner_args(**overrides):
    values = {"session": "s1", "agent": "work", "owner": "native-owner",
              "user": "native-owner", "workspace": "hermes"}
    values.update(overrides)
    return argparse.Namespace(**values)


def test_binding_is_refused_for_a_foreign_owner(tmp_path, monkeypatch):
    native_profile(tmp_path, monkeypatch)
    with pytest.raises(PermissionError, match="owner"):
        bind_inspector(owner_args(owner="someone-else"))
    assert not (tmp_path / "luminary" / "inspector.json").exists()


def test_binding_requires_the_native_profile_agent(tmp_path, monkeypatch):
    native_profile(tmp_path, monkeypatch)
    with pytest.raises(PermissionError, match="native provider"):
        bind_inspector(owner_args(agent="other-agent"))


def test_binding_rejects_a_scope_that_disagrees_with_the_session(tmp_path, monkeypatch):
    native_profile(tmp_path, monkeypatch)
    with pytest.raises(PermissionError, match="complete native session"):
        bind_inspector(owner_args(user="another-user", owner="another-user"))
    with pytest.raises(PermissionError, match="complete native session"):
        bind_inspector(owner_args(workspace="elsewhere"))
    assert not (tmp_path / "luminary" / "inspector.json").exists()


@pytest.mark.parametrize("field", ["owner", "workspace"])
def test_binding_rejects_empty_values_for_a_legacy_session(tmp_path, monkeypatch, field):
    from luminary_memory.hermes import inspector

    monkeypatch.setattr(inspector, "native_session_context", lambda session: {
        "profile_id": str(tmp_path), "agent_id": "work", "workspace": str(tmp_path)})
    args = owner_args(**{field: "   "})
    if field == "owner":
        args.user = args.owner = "   "
    with pytest.raises(ValueError, match="Nonempty exact owner"):
        bind_inspector(args)
    assert not (tmp_path / "luminary" / "inspector.json").exists()


def test_binding_is_not_persisted_without_owner_consent(tmp_path, monkeypatch, capsys):
    native_profile(tmp_path, monkeypatch)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
    assert bind_inspector(owner_args()) == 1
    assert "Cancelled; no binding changed." in capsys.readouterr().out
    assert not (tmp_path / "luminary" / "inspector.json").exists()


def test_approved_binding_is_written_for_the_exact_record_scope(tmp_path, monkeypatch):
    native_profile(tmp_path, monkeypatch)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    assert bind_inspector(owner_args()) == 0
    path = tmp_path / "luminary" / "inspector.json"
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "owner_user_id": "native-owner",
        "record_scope": {"user_id": "native-owner", "workspace_id": "hermes", "agent_id": "work"},
    }
    assert [entry.name for entry in path.parent.iterdir()] == ["inspector.json"]


def test_approved_binding_replaces_a_stale_scope_file(tmp_path, monkeypatch):
    native_profile(tmp_path, monkeypatch)
    path = tmp_path / "luminary" / "inspector.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"owner_user_id": "stale", "record_scope": {}}), encoding="utf-8")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr("builtins.input", lambda prompt: "Y")
    assert bind_inspector(owner_args()) == 0
    assert json.loads(path.read_text(encoding="utf-8"))["owner_user_id"] == "native-owner"


@pytest.fixture
def hermes_home(tmp_path, monkeypatch):
    constants = types.ModuleType("hermes_constants")
    constants.get_hermes_home = lambda: tmp_path
    monkeypatch.setitem(sys.modules, "hermes_constants", constants)
    return tmp_path


def test_configure_lists_declared_fields_without_writing(hermes_home, hermes_config_sdk, capsys):
    config = hermes_home / "config.yaml"
    config.write_text("memory:\n  provider: other\n", encoding="utf-8")
    assert configure(argparse.Namespace(values=[], secrets=[])) == 0
    out = capsys.readouterr().out
    assert "mode" in out and "--set KEY=VALUE" in out
    assert config.read_text(encoding="utf-8") == "memory:\n  provider: other\n"
    assert not (hermes_home / "luminary" / "config.json").exists()


@pytest.mark.parametrize("assignment", ["mode", "unknown_field=1", "llm_api_key=leak", "mode=invalid-choice"])
def test_configure_rejects_undeclared_secret_or_invalid_options(hermes_home, hermes_config_sdk, assignment):
    with pytest.raises(ValueError):
        configure(argparse.Namespace(values=[assignment], secrets=[]))


def test_configure_rejects_fields_that_are_not_secret(hermes_home, hermes_config_sdk):
    with pytest.raises(ValueError, match="declared secret field"):
        configure(argparse.Namespace(values=[], secrets=["mode"]))
    with pytest.raises(ValueError, match="declared secret field"):
        configure(argparse.Namespace(values=[], secrets=["unknown"]))


def test_secret_entry_requires_an_interactive_owner_terminal(hermes_home, hermes_config_sdk, monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
    with pytest.raises(PermissionError, match="interactive native owner terminal"):
        configure(argparse.Namespace(values=[], secrets=["llm_api_key"]))


def test_configure_persists_typed_values_and_secrets_separately(tmp_path, hermes_config_sdk, monkeypatch):
    import hermes_constants
    from hermes_cli import config as native_config
    from hermes_cli import secret_prompt

    monkeypatch.setattr(hermes_constants, "get_hermes_home", lambda: tmp_path)
    monkeypatch.setattr(native_config, "get_hermes_home", lambda: tmp_path)
    monkeypatch.setattr(secret_prompt, "masked_secret_prompt", lambda prompt: "test-secret-value")
    monkeypatch.setenv("LUMINARY_LLM_API_KEY", "")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    assert configure(argparse.Namespace(values=["auto_retain=false", "recall_limit=7"],
                                        secrets=["llm_api_key"])) == 0
    stored = json.loads((tmp_path / "luminary" / "config.json").read_text(encoding="utf-8"))
    assert (stored["auto_retain"], stored["recall_limit"]) == (False, 7)
    assert "llm_api_key" not in stored
    assert native_config.load_env()["LUMINARY_LLM_API_KEY"] == "test-secret-value"


def test_configure_skips_blank_secret_entries(hermes_home, hermes_config_sdk, monkeypatch):
    saved = {}
    secret_module = types.ModuleType("hermes_cli.secret_prompt")
    secret_module.masked_secret_prompt = lambda prompt: ""
    config_module = types.ModuleType("hermes_cli.config")
    config_module.save_env_value = lambda key, value: saved.__setitem__(key, value)
    monkeypatch.setitem(sys.modules, "hermes_cli.secret_prompt", secret_module)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", config_module)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    assert configure(argparse.Namespace(values=["recall_limit=3"], secrets=["llm_api_key"])) == 0
    assert saved == {}


def test_registered_commands_are_ordinary_cli_entrypoints():
    parser = argparse.ArgumentParser()
    register_cli(parser)
    bind = parser.parse_args(["inspector-bind", "--session", "s1", "--owner", "o",
                              "--user", "u", "--workspace", "w", "--agent", "a"])
    assert bind.func is bind_inspector
    assert (bind.session, bind.owner, bind.user, bind.workspace, bind.agent) == ("s1", "o", "u", "w", "a")
    settings = parser.parse_args(["configure", "--set", "recall_limit=7", "--secret", "llm_api_key"])
    assert settings.func is configure
    assert (settings.values, settings.secrets) == (["recall_limit=7"], ["llm_api_key"])
