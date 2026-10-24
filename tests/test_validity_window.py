"""Recall must not return a fact whose validity window has closed.

`valid_to` in the past means the store has moved on: the fact described a state
that no longer holds. Returning it is worse than abstaining, because the answer
looks current and carries valid-looking provenance.

Status and validity are different axes. A row can be `status="active"` (never
superseded, never deleted) and still be out of its validity window.
"""

from __future__ import annotations

import math

from luminary_memory.api import MemoryClient
from luminary_memory.config import Settings

DIM = 16

EXPIRED = "Project Luminary deploy target is staging."
CURRENT = "Project Luminary deploy target is production."
QUESTION = "Where does Luminary deploy?"

PAST = "2020-01-01T00:00:00+00:00"
LONG_AGO = "2019-12-31T00:00:00+00:00"


def _unit(*components: float) -> list[float]:
    vector = [0.0] * DIM
    for index, value in enumerate(components):
        vector[index] = value
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector]


class _Engine:
    """The expired row is the closest match, so only validity can exclude it."""

    def embed(self, text: str) -> list[float]:
        probe = str(text or "").casefold()
        if probe.startswith(EXPIRED.casefold()):
            return _unit(1.0, 0.02)
        if probe.startswith(CURRENT.casefold()):
            return _unit(1.0, 0.30)
        return _unit(1.0)


def _client(tmp_path) -> MemoryClient:
    return MemoryClient(
        settings=Settings(
            db_path=str(tmp_path / "validity.db"),
            strict_recall=True,
            evidence_required=True,
            rule_auto_replace=False,
        ),
        engine=_Engine(),
    )


def test_expired_fact_is_not_returned_even_when_it_is_the_best_match(tmp_path):
    client = _client(tmp_path)
    try:
        client.ingest(
            EXPIRED,
            source="runbook",
            evidence_quote="deploy target is staging",
            observed_at=PAST,
            valid_to=PAST,
        )
        client.ingest(
            CURRENT,
            source="runbook",
            evidence_quote="deploy target is production",
            observed_at=LONG_AGO,
        )

        result = client.recall(QUESTION, limit=10, strict=True)

        contents = [memory.content for memory in result.memories]
        assert EXPIRED not in contents, (
            "a fact whose valid_to has passed was returned as current"
        )
        assert CURRENT in contents
    finally:
        client.close()


def test_expired_fact_is_not_returned_in_permissive_mode_either(tmp_path):
    # Permissive mode relaxes the confidence gate, not correctness: an expired
    # fact is wrong in both modes.
    client = _client(tmp_path)
    try:
        client.ingest(
            EXPIRED,
            source="runbook",
            evidence_quote="deploy target is staging",
            observed_at=PAST,
            valid_to=PAST,
        )
        result = client.recall(QUESTION, limit=10, strict=False)

        assert EXPIRED not in [memory.content for memory in result.memories]
    finally:
        client.close()


def test_not_yet_valid_fact_is_not_returned(tmp_path):
    client = _client(tmp_path)
    try:
        client.ingest(
            EXPIRED,
            source="runbook",
            evidence_quote="deploy target is staging",
            valid_from="2999-01-01T00:00:00+00:00",
        )
        result = client.recall(QUESTION, limit=10, strict=False)

        assert EXPIRED not in [memory.content for memory in result.memories]
    finally:
        client.close()


def test_row_without_a_validity_window_is_still_returned(tmp_path):
    # The common case: no valid_from/valid_to means the fact is simply current.
    client = _client(tmp_path)
    try:
        client.ingest(CURRENT, source="runbook", evidence_quote="deploy target is production")
        result = client.recall(QUESTION, limit=10, strict=True)

        assert CURRENT in [memory.content for memory in result.memories]
    finally:
        client.close()
