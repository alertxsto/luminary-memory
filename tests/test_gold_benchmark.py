"""Gold-benchmark measurement invariants.

These cover the evaluation harness itself: repeatable scoring across run dates,
and the distinction between a grounded row and a relevant one.
"""

from datetime import UTC, datetime, timedelta

from benchmarks.gold import anchor_time, rebase_timestamps
from benchmarks.run_benchmarks import _evaluate_gold
from luminary_memory.types import Memory, RecallResult


def _memory(content: str, memory_id: int, *, source: str | None = None) -> dict:
    return {
        "type": "memory",
        "key": content,
        "content": content,
        "source": source,
        "scope": {"user_id": "u1"},
        "observed_at": "2026-08-10T10:00:00+00:00",
        "valid_from": "2026-08-01T00:00:00+00:00",
        "valid_to": "2026-08-20T00:00:00+00:00",
    }


def test_rebase_preserves_relative_ages_and_shifts_all_fields():
    memories = [
        _memory("older", 1),
        {**_memory("newest", 2), "observed_at": "2026-08-20T00:00:00+00:00"},
    ]
    anchor = anchor_time(memories)
    assert anchor == datetime(2026, 8, 20, tzinfo=UTC)

    delta = datetime(2031, 1, 1, tzinfo=UTC) - anchor
    rebased = rebase_timestamps(memories, delta)

    assert rebased[1]["observed_at"].startswith("2031-01-01T00:00:00")
    older = datetime.fromisoformat(rebased[0]["observed_at"])
    newest = datetime.fromisoformat(rebased[1]["observed_at"])
    original_older = datetime.fromisoformat(memories[0]["observed_at"])
    original_newest = datetime.fromisoformat(memories[1]["observed_at"])
    # Relative age is what drives decay scores, so it must survive the shift.
    assert newest - older == original_newest - original_older
    # Validity windows shift by the same delta, so a fixture cannot silently
    # turn every row expired or future-dated just because the run date moved.
    assert datetime.fromisoformat(rebased[0]["valid_to"]) - datetime.fromisoformat(
        rebased[0]["valid_from"]
    ) == timedelta(days=19)
    assert rebased[0]["valid_from"].endswith("+00:00")


def test_rebase_leaves_untimed_records_untouched():
    record = {"type": "memory", "key": "no-clock", "content": "x"}
    rebased = rebase_timestamps([record], timedelta(days=1))
    assert rebased[0] == record


class _StubClient:
    """Minimal client double: ingest maps content to a fixed id, recall replays."""

    def __init__(self, ids: dict[str, int], replies: dict[str, list[Memory]]):
        self._ids = ids
        self._replies = replies

    def ingest(self, content: str, **_kwargs) -> int:
        return self._ids[content]

    def recall(self, query: str, **_kwargs) -> RecallResult:
        memories = self._replies[query]
        return RecallResult(
            memories=memories,
            scores=[1.0] * len(memories),
            strategies_hit=["semantic"],
            status="ok",
            reason=None,
            confidence=0.9,
        )

    def close(self) -> None:
        pass


def test_grounded_but_irrelevant_row_counts_as_a_wrong_hit():
    # The store holds the answer and an unrelated but fully sourced URL row.
    # Evidence grounding must not be able to hide the wrong row.
    ids = {"deploy target is production": 1, "canonical API reference": 2}
    reply = [
        Memory(id=2, content="canonical API reference", source="https://docs.test"),
        Memory(id=1, content="deploy target is production", source="runbook"),
    ]
    client = _StubClient(ids, {"Where is the deploy target?": reply})
    memories = [_memory("deploy target is production", 1), _memory("canonical API reference", 2)]
    cases = [
        {
            "type": "case",
            "key": "deploy",
            "query": "Where is the deploy target?",
            "scope": {"user_id": "u1"},
            "relevant": ["deploy target is production"],
            "no_answer": False,
        }
    ]

    report = _evaluate_gold(client, memories, cases)

    case = report["case_results"][0]
    assert case["wrong_hit_ids"] == [2]
    assert case["hit_count"] == 1
    assert report["wrong_hit_rows"] == 1
    assert report["wrong_hit_rate"] == 1.0
    # Every returned row carries a source, yet one of them is a quality
    # failure: the two numbers must stay independent.
    assert report["source_grounded_rate"] == 1.0


def test_clean_answer_case_reports_no_wrong_hits():
    ids = {"deploy target is production": 1}
    client = _StubClient(ids, {"Where is the deploy target?": [Memory(id=1, content="deploy target is production", source="runbook")]})
    memories = [_memory("deploy target is production", 1)]
    cases = [
        {
            "type": "case",
            "key": "deploy",
            "query": "Where is the deploy target?",
            "scope": {"user_id": "u1"},
            "relevant": ["deploy target is production"],
            "no_answer": False,
        }
    ]

    report = _evaluate_gold(client, memories, cases)

    assert report["case_results"][0]["wrong_hit_ids"] == []
    assert report["wrong_hit_rate"] == 0.0
    assert report["recall@10"] == 1.0
