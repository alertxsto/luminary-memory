from datetime import UTC, datetime, timedelta

from luminary_memory.backends.sqlite import SQLiteBackend
from luminary_memory.recall.temporal import compute_temporal_score, temporal_recall
from luminary_memory.types import Memory


def test_compute_temporal_score_newer_beats_older():
    now = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
    newer = Memory(content="recent", created_at=(now - timedelta(hours=1)).isoformat(),
                   access_count=0)
    older = Memory(content="old", created_at=(now - timedelta(hours=100)).isoformat(),
                   access_count=0)
    assert compute_temporal_score(newer, now=now) > compute_temporal_score(older, now=now)


def test_compute_temporal_score_frequently_accessed_beats_rarely():
    now = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
    ts = now.isoformat()
    frequent = Memory(content="frequent", created_at=ts, access_count=10)
    rare = Memory(content="rare", created_at=ts, access_count=0)
    assert compute_temporal_score(frequent, now=now) > compute_temporal_score(rare, now=now)


def test_temporal_recall_ranks_by_recency_and_activity(tmp_path):
    b = SQLiteBackend(str(tmp_path / "t.db"))
    now = datetime.now(UTC)
    b.add(Memory(content="oldest", created_at=(now - timedelta(days=10)).isoformat(),
                 access_count=0))
    b.add(Memory(content="newest", created_at=now.isoformat(), access_count=0))
    b.add(Memory(content="popular", created_at=(now - timedelta(hours=5)).isoformat(),
                 access_count=20))
    res = temporal_recall(b, limit=10)
    scored = {m.content: score for m, score, _ in res}
    assert scored["newest"] > scored["oldest"]
    assert res[0][2] == "temporal"


def test_temporal_recall_respects_limit(tmp_path):
    b = SQLiteBackend(str(tmp_path / "t.db"))
    for i in range(5):
        b.add(Memory(content=f"item {i}", access_count=i))
    res = temporal_recall(b, limit=2)
    assert len(res) == 2


def test_temporal_recall_empty_store_returns_empty(tmp_path):
    from luminary_memory.backends.sqlite import SQLiteBackend
    b = SQLiteBackend(str(tmp_path / "t.db"))
    assert temporal_recall(b, limit=10) == []
