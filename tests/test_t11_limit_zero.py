from luminary_memory.api import MemoryClient
from luminary_memory.cli import _clamp_limit
from luminary_memory.config import Settings
from luminary_memory.types import Memory


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


def test_recall_limit_zero_returns_all_distinct_hits_past_dedup_window(tmp_path):
    class ConstantEngine:
        def embed(self, text):
            return [1.0, 0.0]

    c = MemoryClient(
        settings=Settings(db_path=str(tmp_path / "t.db"), query_planner=False,
                          recall_cliff_threshold=1.0, token_budget=100_000),
        engine=ConstantEngine(),
    )
    ids = c.backend.add_many([
        Memory(content=f"item unique token{i:04d}", embedding=[1.0, 0.0])
        for i in range(501)
    ])
    res = c.recall("item", limit=0)
    assert {m.id for m in res.memories} == set(ids)
    assert len(res.memories) == len(res.scores) == len(res.fused_scores) == 501
    c.close()
