"""Summary must reflect authorized data without recall/model side effects."""
import json


def test_summary_exact_scope_and_refresh_are_read_only(scenario):
    before = scenario.snapshot()
    result = scenario.request("summary")
    assert result.status == "ok", result.to_dict()
    assert result.data["totals"]["memories"] == 1
    assert result.data["totals"]["active"] == 1
    assert result.data["totals"]["conflicted"] == 0
    assert not any(marker in json.dumps(result.to_dict()) for marker in ("BOB_SECRET", "PEER_SECRET", "OTHER_SECRET", "GLOBAL_SECRET"))
    assert result.as_of
    assert scenario.snapshot() == before


def test_summary_does_not_call_ingestion_or_model(scenario, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Summary must not invoke recall, ingestion or model explanation")
    monkeypatch.setattr(scenario.client, "recall", forbidden)
    monkeypatch.setattr(scenario.client, "ingest", forbidden)
    monkeypatch.setattr(scenario.client.engine, "embed", forbidden)
    result = scenario.request("summary")
    assert result.status == "ok"
    assert result.data["totals"]["memories"] == 1


def test_summary_timestamp_bounds_follow_authorized_instants_not_text_order(scenario):
    from luminary_memory.types import Memory

    backend = scenario.client.backend
    with backend.transaction():
        backend._sql("UPDATE memories SET created_at=?,updated_at=? WHERE id=?",
                     ("2025-03-01T01:00:00.123456+07:00", "2025-03-02T01:00:00.123456+07:00", scenario.own_id))
        backend._sql("UPDATE memories SET created_at=?,updated_at=? WHERE id=?",
                     ("2050-01-01T00:00:00+00:00", "2050-01-01T00:00:00+00:00", scenario.foreign_id))
    conflict = backend.add(Memory(content="A conflicted scoped fact", status="conflicted",
        created_at="2025-02-28T20:00:00+00:00", updated_at="2025-03-01T20:00:00+00:00", **scenario.client.scope))
    deleted = backend.add(Memory(content="A retracted scoped fact", status="deleted",
        created_at="2025-03-01T00:00:00+00:00", updated_at="2025-03-02T00:00:00+00:00", **scenario.client.scope))
    result = scenario.request("summary")
    assert result.status == "ok", result.to_dict()
    assert result.data["totals"] == {"memories": 3, "active": 1, "candidate": 0,
                                    "conflicted": 1, "superseded": 0, "expired": 0, "deleted": 1}
    assert result.data["time_range"] == {
        "status": "available", "created_from": "2025-02-28T18:00:00.123456+00:00",
        "created_to": "2025-03-01T00:00:00.000000+00:00",
        "updated_from": "2025-03-01T18:00:00.123456+00:00",
        "updated_to": "2025-03-02T00:00:00.000000+00:00",
    }
    for memory_id in (scenario.own_id, conflict, deleted):
        backend.delete(memory_id)
    empty = scenario.request("summary")
    assert empty.data["totals"]["memories"] == 0
    assert empty.data["time_range"] == {"status": "empty", "created_from": None,
                                      "created_to": None, "updated_from": None, "updated_to": None}


def test_summary_marks_legacy_invalid_sqlite_timestamps_as_partial(scenario):
    import pytest

    if hasattr(scenario.client.backend, "_psycopg"):
        pytest.skip("PostgreSQL's typed timestamp columns reject malformed stored dates")
    backend = scenario.client.backend
    with backend.transaction():
        backend._sql("UPDATE memories SET created_at=? WHERE id=?", ("legacy-invalid-date", scenario.own_id))
    before = scenario.snapshot()
    result = scenario.request("summary")
    assert result.status == "ok", result.to_dict()
    assert result.data["totals"]["memories"] == 1
    assert result.data["time_range"]["status"] == "partial"
    assert result.data["time_range"]["created_from"] is None
    assert result.data["time_range"]["created_to"] is None
    assert result.data["time_range"]["updated_from"] == result.data["time_range"]["updated_to"]
    assert result.data["time_range"]["updated_from"] is not None
    assert any(issue["kind"] == "invalid_stored_timestamp" for issue in result.data["issues"])
    assert scenario.snapshot() == before
