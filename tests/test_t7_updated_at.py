from datetime import datetime

from luminary_memory.api import MemoryClient


class _FakeEngine:
    def embed(self, t: str) -> list[float]:
        return [0.1] * 384


def _parse(s: str) -> datetime:
    return datetime.fromisoformat(s)


def test_update_auto_bumps_updated_at(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "t.db"), engine=_FakeEngine())
    mid = c.ingest("original content for T7")
    assert mid is not None
    m = c.get(mid)
    assert m is not None
    # make before stale so we can detect bump
    m.updated_at = "2000-01-01T00:00:00+00:00"
    m.content = "edited content for T7 bump check"
    c.update(m)
    got = c.get(mid)
    assert got is not None
    assert _parse(got.updated_at) > _parse("2000-01-01T00:00:00+00:00")


def test_recall_access_bump_does_not_change_updated_at(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "t.db"), engine=_FakeEngine())
    mid = c.ingest("recall access bump must not touch updated_at")
    assert mid is not None
    m = c.get(mid)
    assert m is not None
    stamp = m.updated_at
    c.recall("access bump")
    got = c.get(mid)
    assert got is not None
    assert got.updated_at == stamp
