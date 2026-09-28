"""Behavioral regressions for scoped export/import and claim lineage."""

import json

import pytest

from luminary_memory.backends.sqlite import SQLiteBackend
from luminary_memory.export import export_memories, import_memories
from luminary_memory.types import Memory


def _payload(tmp_path, rows):
    path = tmp_path / "backup.json"
    path.write_text(json.dumps({"memories": rows}), encoding="utf-8")
    return path


def _by_content(backend):
    return {memory.content: memory for memory in backend.all()}


def test_h5_import_keeps_same_text_in_distinct_full_ownership_scopes(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "destination.db"))
    rows = [
        {"content": "same durable fact", "user_id": "alice", "workspace_id": "w1"},
        {"content": "same durable fact", "user_id": "bob", "workspace_id": "w1"},
        {"content": "same durable fact", "user_id": "alice", "workspace_id": "w2"},
        {"content": "same durable fact", "user_id": "alice", "workspace_id": "w1", "agent_id": "bot"},
        {"content": "same durable fact", "user_id": "alice", "workspace_id": "w1", "session_id": "s2"},
    ]
    path = _payload(tmp_path, rows)
    assert import_memories(backend, path) == {"imported": len(rows)}
    assert {
        (m.user_id, m.workspace_id, m.agent_id, m.session_id)
        for m in backend.all()
    } == {
        ("alice", "w1", None, None),
        ("bob", "w1", None, None),
        ("alice", "w2", None, None),
        ("alice", "w1", "bot", None),
        ("alice", "w1", None, "s2"),
    }
    assert import_memories(backend, path) == {"imported": 0, "skipped_duplicates": len(rows)}
    backend.close()


def test_h6_forward_parent_maps_to_new_id_and_deduplicated_parent(tmp_path):
    source = SQLiteBackend(str(tmp_path / "source.db"))
    parent_id = source.add(Memory(content="old employer", user_id="alice", status="superseded"))
    source.add(Memory(content="new employer", user_id="alice", supersedes_id=parent_id))
    path = tmp_path / "lineage.json"
    export_memories(source, path, scope={"user_id": "alice"}, include_global=False)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert all(isinstance(m.get("id"), int) for m in payload["memories"])
    # A child before its ancestor must resolve even if the ancestor already exists.
    payload["memories"].reverse()
    path.write_text(json.dumps(payload), encoding="utf-8")

    destination = SQLiteBackend(str(tmp_path / "destination.db"))
    unrelated_id = destination.add(Memory(content="not a parent", user_id="bob"))
    assert unrelated_id == parent_id
    result = import_memories(destination, path)
    assert result["imported"] == 2
    restored = _by_content(destination)
    assert restored["new employer"].supersedes_id == restored["old employer"].id
    assert restored["new employer"].supersedes_id != unrelated_id
    source.close()
    destination.close()


def test_h6_active_dedup_parent_maps_to_existing_row_in_exact_scope(tmp_path):
    destination = SQLiteBackend(str(tmp_path / "destination.db"))
    foreign_id = destination.add(Memory(content="shared original", user_id="bob"))
    existing_id = destination.add(Memory(content="shared original", user_id="alice"))
    path = _payload(tmp_path, [
        {"id": 42, "content": "updated original", "user_id": "alice", "supersedes_id": 41},
        {"id": 41, "content": "shared original", "user_id": "alice"},
    ])
    result = import_memories(destination, path)
    assert result == {"imported": 1, "skipped_duplicates": 1}
    assert _by_content(destination)["updated original"].supersedes_id == existing_id
    assert existing_id != foreign_id
    destination.close()


@pytest.mark.parametrize("rows", [
    [{"content": "orphan", "id": 5, "supersedes_id": 1}],
    [{"content": "legacy orphan", "supersedes_id": 1}],
    [
        {"id": 2, "content": "alice child", "user_id": "alice", "supersedes_id": 1},
        {"id": 1, "content": "bob parent", "user_id": "bob"},
    ],
])
def test_h6_unresolved_or_cross_scope_parent_rejected_before_writing(tmp_path, rows):
    destination = SQLiteBackend(str(tmp_path / "destination.db"))
    destination.add(Memory(content="unrelated existing row"))
    path = _payload(tmp_path, rows)
    with pytest.raises(ValueError, match="supersedes|parent|lineage"):
        import_memories(destination, path)
    assert [m.content for m in destination.all()] == ["unrelated existing row"]
    destination.close()


def test_h6_dedup_cannot_collapse_parent_and_child_into_self_reference(tmp_path):
    destination = SQLiteBackend(str(tmp_path / "destination.db"))
    path = _payload(tmp_path, [
        {"id": 2, "content": "identical active fact", "supersedes_id": 1},
        {"id": 1, "content": "identical active fact"},
    ])
    with pytest.raises(ValueError, match="supersedes_id"):
        import_memories(destination, path)
    assert destination.all() == []
    destination.close()


def test_h6_legacy_no_ids_without_lineage_still_imports(tmp_path):
    destination = SQLiteBackend(str(tmp_path / "destination.db"))
    assert import_memories(destination, _payload(tmp_path, [{"content": "legacy fact"}])) == {"imported": 1}
    assert destination.all()[0].supersedes_id is None
    destination.close()


@pytest.mark.parametrize("status", ["superseded", "deleted", "active"])
def test_m3_import_keeps_structured_claim_lifecycle_with_memory(tmp_path, status):
    source = SQLiteBackend(str(tmp_path / f"source-{status}.db"))
    content = f"Alice works at {status} company"
    quote = content
    valid_to = "2024-01-02T00:00:00+00:00" if status != "active" else None
    metadata = {"claims": [{
        "subject": "Alice", "predicate": "employer", "object": status,
        "evidence_quote": quote, "confidence": 0.9,
    }]}
    memory_id = source.add(Memory(content=content, metadata=metadata, status=status, valid_to=valid_to))
    source.add_claim(memory_id, {**metadata["claims"][0], "status": status, "valid_to": valid_to})
    source_claim = source.conn.execute(
        "SELECT status, valid_to FROM claims WHERE memory_id = ?", (memory_id,)
    ).fetchone()
    assert tuple(source_claim) == (status, valid_to)
    path = tmp_path / f"{status}.json"
    export_memories(source, path)
    destination = SQLiteBackend(str(tmp_path / f"destination-{status}.db"))
    assert import_memories(destination, path)["imported"] == 1
    restored = destination.all()[0]
    assert restored.status == status
    restored_claim = destination.conn.execute(
        "SELECT status, valid_to FROM claims WHERE memory_id = ?", (restored.id,)
    ).fetchone()
    assert tuple(restored_claim) == (status, valid_to)
    source.close()
    destination.close()
