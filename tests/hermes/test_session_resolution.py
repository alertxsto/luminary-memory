"""Hermes native session resolution: no frontend scope, no guessed profile."""
from __future__ import annotations

import sys
import types

import pytest


def install_hermes(monkeypatch, tmp_path, *, profile="work", row=None):
    constants = types.ModuleType("hermes_constants")
    constants.get_hermes_home = lambda: tmp_path
    constants.profile_name_for_home = lambda home: profile if str(home) == str(tmp_path) else None
    state = types.ModuleType("hermes_state")

    class SessionDB:
        def __init__(self, *, read_only):
            assert read_only is True

        def get_session(self, session_id):
            return row(session_id) if callable(row) else row

        def close(self):
            pass

    state.SessionDB = SessionDB
    monkeypatch.setitem(sys.modules, "hermes_constants", constants)
    monkeypatch.setitem(sys.modules, "hermes_state", state)


@pytest.mark.parametrize("session_ref", ["", "   ", None, 5, "s" * 513])
def test_only_a_real_session_reference_is_accepted(tmp_path, monkeypatch, session_ref):
    from luminary_memory.hermes.inspector import native_session_context

    install_hermes(monkeypatch, tmp_path, row=lambda session: {"id": session, "cwd": str(tmp_path)})
    with pytest.raises(PermissionError, match="existing native Hermes session"):
        native_session_context(session_ref)


def test_unknown_session_is_denied(tmp_path, monkeypatch):
    from luminary_memory.hermes.inspector import native_session_context

    install_hermes(monkeypatch, tmp_path, row=lambda session: None)
    with pytest.raises(PermissionError, match="unavailable in this profile"):
        native_session_context("s1")


def test_a_session_without_a_workspace_is_denied(tmp_path, monkeypatch):
    from luminary_memory.hermes.inspector import native_session_context

    install_hermes(monkeypatch, tmp_path, row=lambda session: {"id": session, "cwd": "  "})
    with pytest.raises(PermissionError, match="no recorded workspace"):
        native_session_context("s1")


def test_an_unresolved_profile_is_denied(tmp_path, monkeypatch):
    from luminary_memory.hermes.inspector import native_session_context

    install_hermes(monkeypatch, tmp_path, profile="", row=lambda session: {"id": session, "cwd": str(tmp_path)})
    with pytest.raises(PermissionError, match="unresolved"):
        native_session_context("s1")


def test_a_session_recorded_under_another_profile_is_denied(tmp_path, monkeypatch):
    from luminary_memory.hermes.inspector import native_session_context

    install_hermes(monkeypatch, tmp_path, row=lambda session: {
        "id": session, "cwd": str(tmp_path), "profile_name": "personal"})
    with pytest.raises(PermissionError, match="disagrees with the session"):
        native_session_context("s1")


def test_legacy_session_maps_only_the_native_workspace_and_profile(tmp_path, monkeypatch):
    from luminary_memory.hermes.inspector import native_session_context

    install_hermes(monkeypatch, tmp_path, row=lambda session: {
        "id": session, "cwd": str(tmp_path / "project"), "source": "cli"})
    native = native_session_context("s1")
    assert native == {"workspace": str(tmp_path / "project"), "session_id": "s1",
                      "profile_id": str(tmp_path.resolve()), "agent_id": "work"}
    assert "user_id" not in native and "workspace_id" not in native


def test_blank_native_user_id_is_not_treated_as_an_owner(tmp_path, monkeypatch):
    from luminary_memory.hermes.inspector import native_session_context

    install_hermes(monkeypatch, tmp_path, row=lambda session: {
        "id": session, "cwd": str(tmp_path), "profile_name": "work", "user_id": "   "})
    assert "user_id" not in native_session_context("s1")


def test_complete_native_identity_maps_scope_without_the_cwd(tmp_path, monkeypatch):
    from luminary_memory.hermes.inspector import native_session_context

    install_hermes(monkeypatch, tmp_path, row=lambda session: {
        "id": session, "cwd": str(tmp_path), "profile_name": "work", "user_id": "native-owner"})
    native = native_session_context("s1")
    assert (native["user_id"], native["workspace_id"]) == ("native-owner", "hermes")


def test_complete_native_scope_needs_no_binding_file(tmp_path):
    from luminary_memory.hermes.inspector import provider_record_scope

    native = {"profile_id": str(tmp_path), "agent_id": "work", "user_id": "owner",
              "workspace_id": "hermes", "workspace": str(tmp_path)}
    assert provider_record_scope(native) == {"user_id": "owner", "workspace_id": "hermes", "agent_id": "work"}


def test_legacy_scope_without_a_binding_is_refused(tmp_path):
    from luminary_memory.hermes.inspector import provider_record_scope

    with pytest.raises(PermissionError, match="inspector-bind"):
        provider_record_scope({"profile_id": str(tmp_path), "agent_id": "work"})


@pytest.mark.parametrize("binding", ["not-json", "[]", '{"owner_user_id": "owner"}',
                                     '{"owner_user_id": "owner", "record_scope": {"user_id": "u"}}'])
def test_a_corrupt_or_partial_binding_is_refused(tmp_path, binding):
    from luminary_memory.hermes.inspector import provider_record_scope

    directory = tmp_path / "luminary"
    directory.mkdir()
    (directory / "inspector.json").write_text(binding, encoding="utf-8")
    with pytest.raises(PermissionError, match="inspector-bind|binding"):
        provider_record_scope({"profile_id": str(tmp_path), "agent_id": "work"})


def test_a_binding_must_agree_with_the_native_profile_and_owner(tmp_path):
    import json

    from luminary_memory.hermes.inspector import provider_record_scope

    directory = tmp_path / "luminary"
    directory.mkdir()
    path = directory / "inspector.json"
    scope = {"user_id": "owner", "workspace_id": "hermes", "agent_id": "work"}
    path.write_text(json.dumps({"owner_user_id": "owner", "record_scope": scope}), encoding="utf-8")
    assert provider_record_scope({"profile_id": str(tmp_path), "agent_id": "work"}) == scope
    with pytest.raises(PermissionError, match="disagrees with native provider profile or owner"):
        provider_record_scope({"profile_id": str(tmp_path), "agent_id": "other"})
    path.write_text(json.dumps({"owner_user_id": "someone-else", "record_scope": scope}), encoding="utf-8")
    with pytest.raises(PermissionError, match="disagrees with native provider profile or owner"):
        provider_record_scope({"profile_id": str(tmp_path), "agent_id": "work"})


def test_a_binding_cannot_contradict_a_complete_native_mapping(tmp_path):
    import json

    from luminary_memory.hermes.inspector import provider_record_scope

    directory = tmp_path / "luminary"
    directory.mkdir()
    (directory / "inspector.json").write_text(json.dumps({
        "owner_user_id": "owner",
        "record_scope": {"user_id": "owner", "workspace_id": "elsewhere", "agent_id": "work"},
    }), encoding="utf-8")
    with pytest.raises(PermissionError, match="disagrees with the native session mapping"):
        provider_record_scope({"profile_id": str(tmp_path), "agent_id": "work", "user_id": "owner",
                               "workspace_id": "hermes", "workspace": str(tmp_path)})


def test_blank_scope_values_are_unowned_not_silently_reattributed(tmp_path):
    import json

    from luminary_memory.hermes.inspector import provider_record_scope

    directory = tmp_path / "luminary"
    directory.mkdir()
    (directory / "inspector.json").write_text(json.dumps({
        "owner_user_id": "owner",
        "record_scope": {"user_id": "", "workspace_id": "hermes", "agent_id": "work"},
    }), encoding="utf-8")
    with pytest.raises(PermissionError, match="unowned"):
        provider_record_scope({"profile_id": str(tmp_path), "agent_id": "work"})
