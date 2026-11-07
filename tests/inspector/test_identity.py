from dataclasses import replace

import pytest

from luminary_memory.inspector.identity import resolve_context


def test_forged_identity_cannot_select_other_project(scenario):
    for forged in ({"user_id": "bob"}, {"workspace_id": "project-b"}, {"store_id": "foreign"}):
        result = scenario.request("browse", **forged)
        assert result.status == "denied"
        assert result.data is None
    forged = replace(scenario.context, user_id="bob")
    assert scenario.request("browse", context=forged).status == "denied"


def test_project_alias_requires_explicit_binding(scenario):
    alias = dict(scenario.native, host_id="host-b")
    with pytest.raises(PermissionError):
        resolve_context(scenario.client, alias)
    preview = scenario.preview("bind_location", location={field: alias[field] for field in ("workspace", "host_id", "profile_id")})
    assert scenario.commit(preview).status == "ok"
    bound = resolve_context(scenario.client, alias)
    assert bound.project_id == scenario.context.project_id
    assert scenario.request("browse", context=bound).data["items"][0]["id"] == scenario.own_id
    with pytest.raises(PermissionError):
        resolve_context(scenario.client, dict(alias, profile_id="unapproved"))


@pytest.mark.parametrize("missing", ["user_id", "workspace", "agent_id", "session_id", "host_id", "profile_id"])
def test_missing_native_identity_never_falls_back(scenario, missing):
    native = dict(scenario.native)
    del native[missing]
    with pytest.raises((ValueError, PermissionError)):
        resolve_context(scenario.client, native)


def test_other_owner_cannot_initialize_existing_store(scenario):
    with pytest.raises(PermissionError):
        resolve_context(scenario.client, dict(scenario.native, user_id="bob"), initialize=True)
