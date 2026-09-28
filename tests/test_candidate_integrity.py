from datetime import UTC, datetime, timedelta, timezone

from luminary_memory.backends.sqlite import SQLiteBackend
from luminary_memory.recall.graph import graph_recall, index_memory_entities
from luminary_memory.recall.semantic import _expand_query
from luminary_memory.recall.temporal import temporal_recall
from luminary_memory.types import Memory


def _store(tmp_path):
    return SQLiteBackend(str(tmp_path / "candidate.db"))


def test_expired_and_future_rows_do_not_exhaust_keyword_or_temporal_top_k(tmp_path):
    backend = _store(tmp_path)
    now = datetime.now(UTC)
    old = (now - timedelta(days=3)).isoformat()
    expired = (now - timedelta(days=1)).isoformat()
    future = (now + timedelta(days=1)).isoformat()
    active_id = backend.add(Memory(content="blueprint approved", created_at=old, observed_at=old, embedding=[1, 0]))
    for _ in range(2):
        backend.add(Memory(content="blueprint blueprint blueprint", observed_at=now.isoformat(),
                           valid_to=expired, embedding=[1, 0]))
    backend.add(Memory(content="blueprint blueprint blueprint", observed_at=now.isoformat(),
                       valid_from=future, embedding=[1, 0]))
    backend.add(Memory(content="blueprint blueprint blueprint", observed_at=now.isoformat(),
                       valid_from="not-a-timestamp", embedding=[1, 0]))
    assert [m.id for m, _ in backend.keyword_search("blueprint", limit=1)] == [active_id]
    assert [m.id for m, _, _ in temporal_recall(backend, limit=1)] == [active_id]
    assert [m.id for m, _ in backend.vector_search([1, 0], limit=1)] == [active_id]
    assert [mid for mid, _, _ in backend.temporal_scan(limit=1)] == [active_id]
    backend.close()


def test_graph_and_query_expansion_ignore_expired_edges_and_rules(tmp_path):
    backend = _store(tmp_path)
    expired = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    for content in ("alpha secretproject", "alpha secretmanual"):
        mid = backend.add(Memory(content=content, valid_to=expired, importance=0.99))
        row = backend.get(mid)
        index_memory_entities(backend, row)
    assert graph_recall(backend, "alpha") == []
    assert _expand_query(backend, "alpha") == "alpha"
    backend.close()


def test_last_selected_entity_has_graph_relationship(tmp_path):
    backend = _store(tmp_path)
    content = "alpha bravo charlie delta echo foxtrot golf hotel india juliet"
    mid = backend.add(Memory(content=content))
    index_memory_entities(backend, backend.get(mid))
    assert [m.id for m, _, _ in graph_recall(backend, "juliet")] == [mid]
    # No indexed entity may be orphaned by an edge cap.
    orphans = backend.conn.execute(
        "SELECT e.name FROM entities e WHERE NOT EXISTS ("
        "SELECT 1 FROM relations r WHERE r.source_id = e.id AND r.memory_id = ?) AND e.name = 'juliet'",
        (mid,),
    ).fetchall()
    assert not orphans
    backend.close()


def test_graph_index_prioritizes_tag_and_text_order_without_orphan_entities(tmp_path):
    backend = _store(tmp_path)
    tokens = [f"token{i:03d}" for i in range(120)]
    mid = backend.add(Memory(content=" ".join(tokens), tags=["priority"]))
    index_memory_entities(backend, backend.get(mid))
    indexed = {
        row["name"] for row in backend.conn.execute(
            "SELECT DISTINCT e.name FROM entities e "
            "JOIN relations r ON r.source_id = e.id WHERE r.memory_id = ?", (mid,)
        )
    }
    assert {"priority", "token000", "token015"} <= indexed
    assert len(indexed) <= 17
    assert indexed == {row["name"] for row in backend.conn.execute("SELECT name FROM entities")}
    assert [m.id for m, _, _ in graph_recall(backend, "token015")] == [mid]
    backend.close()


def test_validity_uses_utc_offsets_and_preserves_administrative_listing(tmp_path):
    backend = _store(tmp_path)
    now = datetime.now(UTC)
    expired = (now - timedelta(hours=2)).astimezone(timezone(timedelta(hours=-7))).isoformat()
    future = (now + timedelta(hours=2)).astimezone(timezone(timedelta(hours=8))).isoformat()
    invalid = backend.add(Memory(content="validity bounded", valid_to="broken-date"))
    past = backend.add(Memory(content="validity bounded", valid_to=expired))
    waiting = backend.add(Memory(content="validity bounded", valid_from=future))
    current = backend.add(Memory(content="validity bounded", valid_from=(
        now - timedelta(hours=1)).isoformat(), valid_to=(
        now + timedelta(hours=1)).isoformat()))
    assert [m.id for m, _ in backend.keyword_search("validity bounded")] == [current]
    assert {m.id for m in backend.recent()} == {invalid, past, waiting, current}
    backend.close()


def test_nonfinite_integer_cells_do_not_break_read_or_search(tmp_path):
    backend = _store(tmp_path)
    mid = backend.add(Memory(content="robust integer decode"))
    backend.conn.execute("UPDATE memories SET ttl_seconds = '1e999', access_count = 'NaN' WHERE id = ?", (mid,))
    backend.conn.commit()
    for row in (backend.get(mid), backend.all()[0], backend.keyword_search("robust")[0][0]):
        assert row.ttl_seconds is None
        assert row.access_count == 0
    assert backend.temporal_scan()[0][2] == 0
    backend.close()


def test_tag_lookup_matches_json_element_exactly(tmp_path):
    backend = _store(tmp_path)
    wrong = backend.add(Memory(content="not a wildcard match", tags=["core"]))
    wanted = backend.add(Memory(content="literal wildcard tag", tags=["co%re"]))
    underscore = backend.add(Memory(content="literal underscore tag", tags=["co_re"]))
    assert [m.id for m in backend.by_tag_top("co%re", 1)] == [wanted]
    assert [m.id for m in backend.by_tag_top("co_re", 1)] == [underscore]
    assert [m.id for m in backend.by_tag_top("core", 1)] == [wrong]
    backend.close()
