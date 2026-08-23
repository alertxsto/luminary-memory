import sqlite3

import pytest

from luminary_memory.backends.sqlite import SQLiteBackend
from luminary_memory.types import Memory


def _mk(tmp_path):
    return SQLiteBackend(str(tmp_path / "t.db"))

def test_add_and_get(tmp_path):
    b = _mk(tmp_path)
    mid = b.add(Memory(content="The sky is blue", tags=["nature"]))
    m = b.get(mid)
    assert m is not None and m.content == "The sky is blue"
    assert b.count() == 1


def test_non_unique_integrity_error_is_not_treated_as_duplicate(tmp_path):
    b = _mk(tmp_path)
    b.add(Memory(content="same content", content_hash="same-hash"))

    with pytest.raises(sqlite3.IntegrityError, match="NOT NULL"):
        b.add_with_status(Memory(content=None, content_hash="same-hash"))  # type: ignore[arg-type]
    assert b.count() == 1
    b.close()


def test_batch_non_unique_integrity_error_rolls_back_all_rows(tmp_path):
    b = _mk(tmp_path)
    valid = Memory(content="batch valid")
    invalid = Memory(content=None)  # type: ignore[arg-type]

    with pytest.raises(sqlite3.IntegrityError, match="NOT NULL"):
        b.add_many([valid, invalid])
    assert b.count() == 0
    b.close()


def test_keyword_search_ranks(tmp_path):
    b = _mk(tmp_path)
    b.add(Memory(content="database indexing with sqlite fts5"))
    b.add(Memory(content="making a sandwich for lunch"))
    res = b.keyword_search("sqlite fts5", limit=5)
    assert res and res[0][0].content.startswith("database")


def test_close_from_other_thread_does_not_crash(tmp_path):
    """close() called from a different thread than the connection owner must
    not raise (regression for provider writer-thread shutdown)."""
    import threading

    from luminary_memory.backends.sqlite import SQLiteBackend

    holder: dict = {}

    def create_in_thread():
        b = SQLiteBackend(str(tmp_path / "t.db"))
        # connection created on THIS thread
        b.conn.execute("SELECT 1").fetchone()
        holder["backend"] = b

    t = threading.Thread(target=create_in_thread)
    t.start()
    t.join()
    b = holder["backend"]
    # Connection was created in another thread; closing here must not crash.
    b.close()  # should not raise
def test_thread_local_connections(tmp_path):
    """Connections are thread-local: recall from a background thread must not
    raise ProgrammingError (regression: provider prefetch recall crashed)."""
    import threading

    from luminary_memory.api import MemoryClient

    class _E:
        def embed(self, t): return [0.1, 0.1, 0.1]
        def embed_batch(self, ts): return [[0.1, 0.1, 0.1] for _ in ts]

    c = MemoryClient(db_path=str(tmp_path / "tl.db"), engine=_E())
    c.ingest("deploy target production", tags=["deploy"])
    c.ingest("banana smoothie recipe", tags=["food"])

    result = {}

    def worker():
        res = c.recall("deploy", limit=10)
        result["n"] = len(res.memories)

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert result["n"] == 1  # recall from other thread worked
    c.close()


def test_top_by_importance_lean_and_ordered(tmp_path):
    """top_by_importance returns top-N by importance desc, then access desc,
    without decoding embedding blobs."""
    b = _mk(tmp_path)
    b.add(Memory(content="low value fact", importance=0.3))
    b.add(Memory(content="medium fact", importance=0.6, access_count=5))
    b.add(Memory(content="high rule", importance=0.95, access_count=1))
    b.add(Memory(content="high rule 2", importance=0.9, access_count=9))

    top = b.top_by_importance(2, min_importance=0.5)
    assert [m.content for m in top] == ["high rule", "high rule 2"]
    # embeddings are not loaded (lean scan) — memory has no embedding attr set
    assert all(getattr(m, "embedding", None) is None for m in top)
    # min_importance filters below-threshold (0.3 excluded)
    top_all = b.top_by_importance(10, min_importance=0.5)
    assert len(top_all) == 3
    assert all(m.importance >= 0.5 for m in top_all)


def test_recent_episodes_are_ordered_and_exactly_scoped(tmp_path):
    b = _mk(tmp_path)
    b.record_episode(
        "s1-old",
        "older current-session turn",
        source="hermes-session",
        metadata={"sequence": 1},
        user_id="user-1",
        session_id="s1",
    )
    b.record_episode(
        "s2",
        "other session turn",
        source="hermes-session",
        metadata={"sequence": 9},
        user_id="user-1",
        session_id="s2",
    )
    b.record_episode(
        "s1-new",
        "newer current-session turn",
        source="hermes-session",
        metadata={"sequence": 2},
        user_id="user-1",
        session_id="s1",
    )

    rows = b.recent_episodes(
        limit=10,
        scope={"user_id": "user-1", "session_id": "s1"},
        include_global=False,
    )
    assert [row["id"] for row in rows] == ["s1-new", "s1-old"]
    assert all(row["session_id"] == "s1" for row in rows)
    assert rows[0]["metadata"]["sequence"] == 2
    b.close()


def test_touch_memories_batches_access(tmp_path):
    b = _mk(tmp_path)
    a = b.add(Memory(content="fact one"))
    bb = b.add(Memory(content="fact two"))
    cid = b.add(Memory(content="untouched"))

    b.touch_memories([a, bb])
    touched = {m.id: m.access_count for m in b.all()}
    assert touched[a] == 1
    assert touched[bb] == 1
    assert touched[cid] == 0  # untouched stays 0

    b.touch_memories([a])
    assert {m.id: m.access_count for m in b.all()}[a] == 2


def test_delete_many_batches(tmp_path):
    b = _mk(tmp_path)
    ids = [b.add(Memory(content=f"fact {i}")) for i in range(4)]
    assert b.count() == 4
    b.delete_many(ids[:3])
    assert b.count() == 1
    assert b.get(ids[3]) is not None


def test_claim_and_claim_evidence_insert_roll_back_together(tmp_path):
    b = _mk(tmp_path)
    memory_id = b.add(Memory(content="claim transaction source"))
    b.conn.execute(
        """
        CREATE TRIGGER fail_claim_evidence
        BEFORE INSERT ON claim_evidence
        BEGIN
            SELECT RAISE(ABORT, 'forced claim evidence failure');
        END
        """
    )
    b.conn.commit()

    claim = {
        "subject": "project:luminary",
        "predicate": "deploy_target",
        "object": "staging",
        "evidence_quote": "deploy target is staging",
    }
    with pytest.raises(sqlite3.IntegrityError, match="forced claim evidence failure"):
        b.add_claim(memory_id, claim)
    assert b.conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 0

    b.conn.execute("DROP TRIGGER fail_claim_evidence")
    b.conn.commit()
    b.add_claim(memory_id, claim)
    assert b.conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 1
    assert b.conn.execute("SELECT COUNT(*) FROM claim_evidence").fetchone()[0] == 1
    b.close()


def test_update_importances_bulk(tmp_path):
    b = _mk(tmp_path)
    ids = [b.add(Memory(content=f"fact {i}", importance=0.3)) for i in range(3)]
    b.update_importances([(0.9, ids[0]), (0.5, ids[1])])
    by_id = {m.id: m.importance for m in b.all()}
    assert by_id[ids[0]] == 0.9
    assert by_id[ids[1]] == 0.5
    assert by_id[ids[2]] == 0.3  # untouched


def test_scan_embeddings_matrix_shape(tmp_path):
    b = _mk(tmp_path)
    for i in range(3):
        b.add(Memory(content=f"fact {i}", embedding=[float(i), 0.0, 0.0]))
    mid, mat = b.scan_embeddings_matrix()
    assert len(mid) == 3
    assert mat.shape == (3, 3)
    assert mat.dtype.name == "float32"


def test_scan_embeddings_ignores_corrupt_and_mixed_dimensions(tmp_path):
    b = _mk(tmp_path)
    good_id = b.add(Memory(content="good", embedding=[1.0, 0.0, 0.0]))
    b.add(Memory(content="old model", embedding=[1.0, 0.0]))
    b.conn.execute(
        "INSERT INTO memories (content, embedding) VALUES (?, ?)",
        ("corrupt", b"not-a-float32-vector"),
    )
    b.conn.commit()

    ids, matrix = b.scan_embeddings_matrix()
    assert ids == [good_id]
    assert matrix.shape == (1, 3)


def test_corrupt_legacy_row_degrades_to_safe_defaults(tmp_path):
    b = _mk(tmp_path)
    mid = b.add(Memory(content="repairable row", embedding=[1.0, 0.0]))
    b.conn.execute(
        "UPDATE memories SET metadata='[]', tags='{}', importance='NaN', "
        "confidence='broken', access_count='broken', embedding=? WHERE id=?",
        (b"x", mid),
    )
    b.conn.commit()

    memory = b.get(mid)
    assert memory is not None
    assert memory.metadata == {}
    assert memory.tags == []
    assert memory.importance == 0.5
    assert memory.confidence == 1.0
    assert memory.access_count == 0
    assert memory.embedding is None
    assert b.all()[0].embedding is None


def test_large_batch_helpers_chunk_sqlite_parameters(tmp_path):
    b = _mk(tmp_path)
    memories = [Memory(content=f"chunked memory {i}", importance=0.3) for i in range(1200)]
    ids = b.add_many(memories)
    assert len(b.get_many(ids)) == 1200

    b.touch_memories(ids)
    b.update_importances([(0.4, mid) for mid in ids])
    assert b.get(ids[-1]).access_count == 1
    assert b.get(ids[0]).importance == 0.4

    b.delete_many(ids)
    assert b.count() == 0


def test_by_tag_top_returns_core_memories_in_stable_insert_order(tmp_path):
    b = _mk(tmp_path)
    b.add(Memory(content="rule tabel wajib", tags=["core"], importance=0.9))
    b.add(Memory(content="rule em dash", tags=["core"], importance=0.95))
    b.add(Memory(content="fakta biasa", tags=["other"], importance=0.3))
    b.add(Memory(content="core-x mirip", tags=["core-x"], importance=0.99))

    top = b.by_tag_top("core", 10)
    contents = [m.content for m in top]
    assert "rule em dash" in contents
    assert "rule tabel wajib" in contents
    assert "fakta biasa" not in contents
    assert "core-x mirip" not in contents, "core-x tag must not match core"
    # Core membership is not a relevance leaderboard. Its order is stable
    # insertion order even when importance changes.
    assert [m.content for m in top[:2]] == ["rule tabel wajib", "rule em dash"]


def test_by_tag_top_order_does_not_change_when_importance_changes(tmp_path):
    b = _mk(tmp_path)
    first = b.add(Memory(content="first core rule", tags=["core"], importance=0.1))
    second = b.add(Memory(content="second core rule", tags=["core"], importance=0.9))

    m = b.get(first)
    m.importance = 0.99
    b.update(m)

    assert [m.id for m in b.by_tag_top("core", 2)] == [first, second]


def test_by_tag_top_respects_limit(tmp_path):
    b = _mk(tmp_path)
    for i in range(5):
        b.add(Memory(content=f"rule {i}", tags=["core"], importance=0.9))
    assert len(b.by_tag_top("core", 3)) == 3


# ============================================================================
# Extended backend coverage (Phase 3 — T3.x)
# ============================================================================

def test_fts_sanitize_neutralizes_injection(tmp_path):
    from luminary_memory.backends.sqlite import _sanitize_fts_query

    for nasty in ['o*r NEAR "x"', '();--', 'alpha OR beta', 'quote "q" xy', 'plus - minus']:
        safe = _sanitize_fts_query(nasty)
        # empty stays the empty-phrase sentinel; otherwise every term is
        # wrapped in quotes and joined by OR so FTS5 operators can't leak.
        assert safe == '" "' or (safe.startswith('"') and safe.endswith('"') and " OR " in safe), \
            f"unsafe output for {nasty!r}: {safe!r}"
    assert _sanitize_fts_query("") == '" "'
    assert _sanitize_fts_query("   ") == '" "'


def test_keyword_fts_syncs_through_update_and_delete(tmp_path):
    b = _mk(tmp_path)
    mid = b.add(Memory(content="original dog text", tags=[]))
    assert b.keyword_search("dog", limit=5)
    b.update(Memory(id=mid, content="now about cats", tags=[], importance=0.5))
    assert not b.keyword_search("dog", limit=5)
    assert b.keyword_search("cats", limit=5)
    b.delete(mid)
    assert not b.keyword_search("cat", limit=5)
    assert b.count() == 0


def test_keyword_search_or_join_multi_term(tmp_path):
    b = _mk(tmp_path)
    b.add(Memory(content="laporan pakai tabel", tags=[]))
    b.add(Memory(content="resep smoothie pisang", tags=[]))
    # multi-word query: FTS5 OR join matches a memory containing ANY term
    hits = b.keyword_search("laporan tabel", limit=10)
    assert any("tabel" in m.content for m, _ in hits), "OR join must surface partial-term match"


def test_keyword_search_unlimited_and_zero(tmp_path):
    b = _mk(tmp_path)
    for i in range(4):
        b.add(Memory(content=f"shared keyword token-{i}", tags=[]))
    assert len(b.keyword_search("shared")) >= 4  # limit=None
    assert len(b.keyword_search("shared", limit=None)) == 4
    assert len(b.keyword_search("shared", limit=0)) <= 4


def test_vector_search_ordering_and_limits(tmp_path):
    b = _mk(tmp_path)
    b.add(Memory(content="a", embedding=[1.0, 0.0]))
    b.add(Memory(content="b", embedding=[0.9, 0.1]))
    b.add(Memory(content="c", embedding=[0.0, 1.0]))
    q = [1.0, 0.0]
    top = b.vector_search(q, limit=2)
    assert len(top) == 2
    assert top[0][0].content == "a"  # closest to q
    assert {m.content for m, _ in top} == {"a", "b"}

    full = b.vector_search(q, limit=None)
    assert [m.content for m, _ in full] == ["a", "b", "c"]
    # backend level: limit=0 is zero results (the API maps 0 -> None/unlimited)
    assert b.vector_search(q, limit=0) == []
    assert b.vector_search([0.0, 0.0]) == []  # degenerate zero query


def test_vector_search_single_row_and_large_limit(tmp_path):
    b = _mk(tmp_path)
    b.add(Memory(content="solo", embedding=[0.5, 0.5]))
    res = b.vector_search([0.5, 0.5], limit=100)
    assert len(res) == 1 and res[0][0].content == "solo"


def test_by_tags_multi_and_corrupt(tmp_path):
    b = _mk(tmp_path)
    b.add(Memory(content="m1", tags=["database", "prod"]))
    b.add(Memory(content="m2", tags=["database"]))
    b.add(Memory(content="m3", tags=["frontend"]))
    assert len(b.by_tags(["database"])) == 2
    assert len(b.by_tags(["prod", "frontend"])) == 2  # m1(prod) + m3(frontend); m2 neither
    assert b.by_tags([]) == set()

    # corrupt JSON tag blob must not crash; treated as having no tags
    b.conn.execute("UPDATE memories SET tags='{corrupt' WHERE content='m3'")
    b.conn.commit()
    assert b.by_tags(["frontend"]) == set()


def test_temporal_scan_lightweight(tmp_path):
    b = _mk(tmp_path)
    b.add(Memory(content="fact one", tags=["x"], access_count=2))
    rows = b.temporal_scan()
    assert len(rows) == 1
    mid, created, acc = rows[0]
    assert mid is not None and created and acc == 2
    assert not hasattr(rows[0], "metadata")  # tuple, not Memory


def test_scan_embeddings_pair_matches_matrix(tmp_path):
    b = _mk(tmp_path)
    for i in range(3):
        b.add(Memory(content=f"f{i}", embedding=[float(i), float(i + 1)]))
    ids_pair, vecs = b.scan_embeddings()
    ids_mat, mat = b.scan_embeddings_matrix()
    assert ids_pair == ids_mat
    assert mat.shape == (3, 2)
    # float32 round-trip preserves values within tolerance
    for m, row in zip(vecs, mat, strict=True):
        for a, bb in zip(m, row, strict=True):
            assert abs(a - bb) < 1e-6


def test_recent_pagination_edge(tmp_path):
    b = _mk(tmp_path)
    b.add(Memory(content="oldest", created_at="2026-01-01T00:00:00+00:00"))
    b.add(Memory(content="newest", created_at="2026-02-01T00:00:00+00:00"))
    newest = b.recent(limit=1)
    assert newest[0].content == "newest"
    assert len(b.recent(limit=0)) == 2  # unlimited
    assert len(b.recent(limit=10, offset=5)) == 0


def test_embedding_roundtrip_preserves_values(tmp_path):
    b = _mk(tmp_path)
    vec = [0.1, -0.5, 0.33, 1.0]
    mid = b.add(Memory(content="vec", embedding=vec))
    got = b.get(mid)
    assert got is not None and got.embedding is not None
    for a, target in zip(got.embedding, vec, strict=True):
        assert abs(a - target) < 1e-6


def test_concurrent_recall_and_ingest(tmp_path):
    import threading

    from luminary_memory.api import MemoryClient

    class _E:
        def embed(self, t): return [len(t) % 10, 0.0, 0.0]
        def embed_batch(self, ts): return [[len(t) % 10, 0.0, 0.0] for t in ts]

    c = MemoryClient(db_path=str(tmp_path / "cc.db"), engine=_E())
    for i in range(5):
        c.ingest(f"deploy target host-{i}", tags=["infra"])
    errors: list[Exception] = []

    def worker():
        try:
            c.recall("deploy", limit=5)
            c.ingest("banana smoothie", tags=["food"])
            c.recall("deploy host", limit=5)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, f"cross-thread backend ops must not raise: {errors}"
    c.close()
