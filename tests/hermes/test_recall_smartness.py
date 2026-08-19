"""v0.2.18 recall smartness: score floor, skipped-as-duplicates counter, and
tool recall dedup against core."""

import json
from types import SimpleNamespace

from luminary_memory.hermes.provider import LuminaryMemoryProvider, _apply_min_score


def _init_provider(tmp_path):
    p = LuminaryMemoryProvider()
    p.initialize("s1", hermes_home=str(tmp_path), platform="cli", agent_identity="test")
    return p


def _fake(mid, content):
    return SimpleNamespace(id=mid, content=content, importance=0.9, tags=[])


# --------------------------------------------------------------------------- #
# Score floor
# --------------------------------------------------------------------------- #


def test_apply_min_score_drops_below_floor():
    low = _fake(1, "weak match")
    high = _fake(2, "strong match")
    mems, scores = _apply_min_score([low, high], [0.1, 0.9], 0.5)
    assert len(mems) == 1 and scores == [0.9]
    assert mems[0].content == "strong match"


def test_apply_min_score_never_empties():
    low = _fake(1, "only result")
    mems, scores = _apply_min_score([low], [0.1], 0.9)
    assert len(mems) == 1 and scores == [0.1], "floor must never empty recall"


def test_apply_min_score_off_when_zero():
    mem = _fake(1, "x")
    mems, _ = _apply_min_score([mem], [0.01], 0.0)
    assert len(mems) == 1


# --------------------------------------------------------------------------- #
# Skipped-as-duplicates counter
# --------------------------------------------------------------------------- #


def test_recall_block_reports_skipped_duplicates(tmp_path):
    p = _init_provider(tmp_path)
    dup_id, dup_content = 7, "same as core"
    with p._prefetch_lock:
        p._injected_ids = {dup_id}
        p._injected_contents = {hash(dup_content)}
    out = p._format_recall_block(
        [_fake(dup_id, dup_content), _fake(9, "a fresh fact")], [0.9, 0.8]
    )
    assert "a fresh fact" in out
    assert "(1 skipped as duplicates)" in out
    p.shutdown()


# --------------------------------------------------------------------------- #
# Tool recall dedup against core
# --------------------------------------------------------------------------- #


def test_tool_recall_dedups_against_core(tmp_path, monkeypatch):
    p = _init_provider(tmp_path)
    p._client.ingest("core rule always use tables", tags=[p._core_tag()], source="test")

    core_mem = _fake(101, "core rule always use tables")
    extra_mem = _fake(202, "the deploy target is the staging cluster.")
    result = SimpleNamespace(memories=[core_mem, extra_mem], scores=[0.95, 0.7])
    monkeypatch.setattr(p._client, "recall", lambda *a, **k: result)

    payload = json.loads(p.handle_tool_call("luminary_recall", {"query": "q"}))
    contents = [m["content"] for m in payload["memories"]]
    assert "core rule always use tables" not in contents, "core duplicate leaked into tool"
    assert any("deploy target" in c for c in contents)
    p.shutdown()