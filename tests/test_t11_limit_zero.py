from luminary_memory.api import MemoryClient
from luminary_memory.cli import _clamp_limit


def test_api_list_limit_zero_returns_all(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "t.db"))
    c.ingest("first memory for limit-zero API")
    c.ingest("second memory for limit-zero API")
    c.ingest("third memory for limit-zero API")
    assert len(c.list(limit=0)) == 3
    assert len(c.list(limit=0, offset=0)) == 3


def test_api_list_negative_limit_raises(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "t.db"))
    import pytest

    with pytest.raises(ValueError):
        c.list(limit=-1)


def test_cli_clamp_limit_zero_is_unlimited():
    assert _clamp_limit(0) is None


def test_cli_clamp_limit_negative_raises():
    import pytest

    with pytest.raises(ValueError):
        _clamp_limit(-1)


def test_cli_clamp_limit_positive_unchanged():
    assert _clamp_limit(5) == 5
    assert _clamp_limit(1) == 1


def test_recall_limit_zero_returns_not_clamped(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "t.db"))
    c.ingest("deploy target is staging cluster")
    c.ingest("deploy infra uses kubernetes")
    res = c.recall("deploy", limit=0)
    # limit 0 = unlimited, so should return all relevant ids
    assert len(res.memories) >= 1
