"""Deep tests for Luminary's provider-owned incremental memory reviewer."""

from __future__ import annotations

import json
import time

from luminary_memory.hermes.provider import LuminaryMemoryProvider


class _FakeEngine:
    def embed(self, text: str) -> list[float]:
        return [float((sum(map(ord, text)) % 97) + 1), float(len(text) + 1), 1.0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]


def _provider(tmp_path, monkeypatch, enricher_type, callbacks=None) -> LuminaryMemoryProvider:
    import luminary_memory.ingest.llm as llm_module

    monkeypatch.setattr(llm_module, "OpenAICompatibleEnricher", enricher_type)
    provider = LuminaryMemoryProvider()
    provider.initialize(
        "session-1",
        hermes_home=str(tmp_path),
        platform="cli",
        agent_identity="test-agent",
        status_callback=(callbacks if callbacks is not None else []).append,
    )
    provider._client.engine = _FakeEngine()
    provider._config.update(
        {
            "ingest_llm": True,
            "llm_base_url": "test",
            "llm_model": "test",
            "retain_every_n_turns": 1,
        }
    )
    return provider


def _wait(provider: LuminaryMemoryProvider, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while provider._retain_queue.unfinished_tasks and time.monotonic() < deadline:
        time.sleep(0.02)
    assert provider._retain_queue.unfinished_tasks == 0


def _claim(object_value: str, quote: str) -> dict:
    return {
        "subject": "user",
        "predicate": "preferred_model",
        "object": object_value,
        "polarity": "positive",
        "confidence": 0.95,
        "evidence_quote": quote,
    }


def test_reviewer_captures_fact_when_normal_episode_gate_abstains(tmp_path, monkeypatch):
    calls = []
    statuses = []

    class _Reviewer:
        def __init__(self, *args, **kwargs):
            pass

        def enrich(self, text):
            from luminary_memory.ingest.llm import EnrichedContent

            return EnrichedContent(content=text, worth_saving=False)

        def review_turn(self, turn, memories):
            calls.append((turn, [memory.id for memory in memories]))
            return json.dumps(
                {
                    "captures": [
                        {
                            "content": "The user prefers the slate theme.",
                            "evidence_quote": "I prefer the slate theme.",
                            "tags": ["preference"],
                            "importance": 0.8,
                            "confidence": 0.98,
                            "claim": {
                                "subject": "user",
                                "predicate": "preferred_theme",
                                "object": "slate",
                                "polarity": "positive",
                                "confidence": 0.98,
                                "evidence_quote": "I prefer the slate theme.",
                            },
                        }
                    ],
                    "actions": [],
                }
            )

    provider = _provider(tmp_path, monkeypatch, _Reviewer, statuses)
    provider.sync_turn(
        "I prefer the slate theme.",
        "Understood; I will use it.",
        session_id="session-1",
    )
    _wait(provider)

    memories = provider._client.list(limit=0)
    assert len(memories) == 1
    assert memories[0].source == "hermes-curator"
    assert memories[0].content == "The user prefers the slate theme."
    assert memories[0].evidence_quote == "I prefer the slate theme."
    assert calls and calls[0][1] == []
    assert statuses == ["🌙 Luminary — self-improvement: saved 1"]
    provider.shutdown()


def test_reviewer_supersedes_conflicting_claim_with_new_evidence(tmp_path, monkeypatch):
    state = {"target_id": None}
    statuses = []

    class _Reviewer:
        def __init__(self, *args, **kwargs):
            pass

        def enrich(self, text):
            from luminary_memory.ingest.llm import EnrichedContent

            return EnrichedContent(content=text, worth_saving=False)

        def review_turn(self, turn, memories):
            target = next(memory for memory in memories if memory.id == state["target_id"])
            assert target.status == "active"
            return json.dumps(
                {
                    "captures": [],
                    "actions": [
                        {
                            "memory_id": target.id,
                            "action": "supersede",
                            "content": "The preferred model is Beta.",
                            "evidence_quote": "I switched to Beta.",
                            "reason": "The current turn explicitly changes the preference.",
                            "claim": _claim("Beta", "I switched to Beta."),
                        }
                    ],
                }
            )

    provider = _provider(tmp_path, monkeypatch, _Reviewer, statuses)
    old_id = provider._client.ingest(
        "The preferred model is Alpha.",
        source="seed",
        metadata={"claims": [_claim("Alpha", "The preferred model is Alpha.")]},
        enrich=False,
        evidence_quote="The preferred model is Alpha.",
        source_text="The preferred model is Alpha.",
    )
    assert old_id is not None
    state["target_id"] = old_id

    provider.sync_turn("I switched to Beta.", "Confirmed.", session_id="session-1")
    _wait(provider)

    old = provider._client.backend.get(old_id)
    active = [memory for memory in provider._client.list(limit=0) if memory.id != old_id]
    assert old is not None and old.status == "superseded"
    assert len(active) == 1
    assert active[0].content == "The preferred model is Beta."
    assert active[0].claim_key == old.claim_key
    assert active[0].evidence_quote == "I switched to Beta."
    assert provider._client.backend.conn.execute(
        "SELECT COUNT(*) FROM memory_events WHERE event_type = 'supersede'"
    ).fetchone()[0] >= 1
    assert statuses == ["🌙 Luminary — self-improvement: updated 1"]
    provider.shutdown()


def test_reviewer_applies_retraction_and_keeps_unsafe_supersessions_as_noops(
    tmp_path, monkeypatch
):
    statuses = []
    ids = {}

    class _Reviewer:
        def __init__(self, *args, **kwargs):
            pass

        def enrich(self, text):
            from luminary_memory.ingest.llm import EnrichedContent

            return EnrichedContent(content=text, worth_saving=False)

        def review_turn(self, turn, memories):
            assert {memory.id for memory in memories} >= {
                ids["plain"],
                ids["claim"],
                ids["retract"],
            }
            mismatched_claim = _claim("Gamma", "I retract the old note.")
            mismatched_claim["predicate"] = "different_claim"
            return json.dumps(
                {
                    "captures": [],
                    "actions": [
                        {"memory_id": ids["plain"], "action": "keep"},
                        {
                            "memory_id": ids["plain"],
                            "action": "supersede",
                            "content": "A replacement without a claim key.",
                            "evidence_quote": "I retract the old note.",
                        },
                        {
                            "memory_id": ids["claim"],
                            "action": "supersede",
                            "content": "The preferred model is Gamma.",
                            "evidence_quote": "I retract the old note.",
                            "claim": mismatched_claim,
                        },
                        {
                            "memory_id": ids["retract"],
                            "action": "retract",
                            "evidence_quote": "I retract the old note.",
                            "reason": "The current turn explicitly invalidates it.",
                        },
                    ],
                }
            )

    provider = _provider(tmp_path, monkeypatch, _Reviewer, statuses)
    ids["plain"] = provider._client.ingest(
        "A plain note without a structured claim.",
        source="seed",
        enrich=False,
        evidence_quote="A plain note without a structured claim.",
    )
    ids["claim"] = provider._client.ingest(
        "The preferred model is Alpha.",
        source="seed",
        metadata={"claims": [_claim("Alpha", "The preferred model is Alpha.")]},
        enrich=False,
        evidence_quote="The preferred model is Alpha.",
        source_text="The preferred model is Alpha.",
    )
    ids["retract"] = provider._client.ingest(
        "The old note remains active.",
        source="seed",
        enrich=False,
        evidence_quote="The old note remains active.",
    )

    provider.sync_turn("I retract the old note.", "Understood.")
    _wait(provider)

    assert provider._client.backend.get(ids["plain"]).status == "active"
    assert provider._client.backend.get(ids["claim"]).status == "active"
    assert provider._client.backend.get(ids["retract"]).status == "deleted"
    assert statuses == ["🌙 Luminary — self-improvement: retracted 1"]
    provider.shutdown()


def test_reviewer_does_not_capture_conflicting_claim_without_explicit_action(tmp_path, monkeypatch):
    statuses = []

    class _Reviewer:
        def __init__(self, *args, **kwargs):
            pass

        def enrich(self, text):
            from luminary_memory.ingest.llm import EnrichedContent

            return EnrichedContent(content=text, worth_saving=False)

        def review_turn(self, turn, memories):
            return json.dumps(
                {
                    "captures": [
                        {
                            "content": "The preferred model is Beta.",
                            "evidence_quote": "I now prefer Beta.",
                            "claim": _claim("Beta", "I now prefer Beta."),
                        }
                    ],
                    "actions": [],
                }
            )

    provider = _provider(tmp_path, monkeypatch, _Reviewer, statuses)
    old_id = provider._client.ingest(
        "The preferred model is Alpha.",
        source="seed",
        metadata={"claims": [_claim("Alpha", "The preferred model is Alpha.")]},
        enrich=False,
        evidence_quote="The preferred model is Alpha.",
        source_text="The preferred model is Alpha.",
    )
    provider.sync_turn("I now prefer Beta.", "Recorded.")
    _wait(provider)

    memories = provider._client.list(limit=0)
    assert len(memories) == 1
    assert memories[0].id == old_id
    assert memories[0].status == "active"
    assert statuses == []
    provider.shutdown()


def test_invalid_review_payload_cannot_mutate_and_writer_recovers(tmp_path, monkeypatch):
    calls = {"count": 0}
    statuses = []

    class _Reviewer:
        def __init__(self, *args, **kwargs):
            pass

        def enrich(self, text):
            from luminary_memory.ingest.llm import EnrichedContent

            return EnrichedContent(content=text, worth_saving=False)

        def review_turn(self, turn, memories):
            calls["count"] += 1
            if calls["count"] == 1:
                return json.dumps(
                    {
                        "captures": [
                            {
                                "content": "Untrusted fact",
                                "evidence_quote": "not in this turn",
                            }
                        ],
                        "actions": [
                            {
                                "memory_id": 999999,
                                "action": "retract",
                                "evidence_quote": "not in this turn",
                            }
                        ],
                    }
                )
            return json.dumps(
                {
                    "captures": [
                        {
                            "content": "The user selected the long-run test mode.",
                            "evidence_quote": "I selected long-run test mode.",
                        }
                    ],
                    "actions": [],
                }
            )

    provider = _provider(tmp_path, monkeypatch, _Reviewer, statuses)
    provider.sync_turn("The first turn is not trusted.", "No change.", session_id="session-1")
    provider.sync_turn("I selected long-run test mode.", "Recorded.", session_id="session-1")
    _wait(provider)

    memories = provider._client.list(limit=0)
    assert len(memories) == 1
    assert memories[0].content == "The user selected the long-run test mode."
    assert calls["count"] == 2
    assert statuses == ["🌙 Luminary — self-improvement: saved 1"]
    assert provider._writer_thread is not None and provider._writer_thread.is_alive()
    provider.shutdown()


def test_reviewer_exception_is_isolated_and_does_not_log_turn_content(tmp_path, monkeypatch):
    calls = {"count": 0}

    class _Reviewer:
        def __init__(self, *args, **kwargs):
            pass

        def enrich(self, text):
            from luminary_memory.ingest.llm import EnrichedContent

            return EnrichedContent(content=text, worth_saving=False)

        def review_turn(self, turn, memories):
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("review backend failed")
            return json.dumps(
                {
                    "captures": [
                        {
                            "content": "The user selected recovery mode.",
                            "evidence_quote": "I selected recovery mode.",
                        }
                    ],
                    "actions": [],
                }
            )

    provider = _provider(tmp_path, monkeypatch, _Reviewer)
    provider.sync_turn("First turn contains private-review-marker-1.", "Ignored.")
    provider.sync_turn("I selected recovery mode.", "Recorded.")
    _wait(provider)

    memories = provider._client.list(limit=0)
    assert calls["count"] == 2
    assert len(memories) == 1
    assert memories[0].content == "The user selected recovery mode."
    assert provider._writer_thread is not None and provider._writer_thread.is_alive()
    provider.shutdown()

    log_text = (tmp_path / "luminary" / "luminary.log").read_text(encoding="utf-8")
    assert "memory.review.failed" in log_text
    assert "private-review-marker-1" not in log_text


def test_reviewer_respects_exact_scope_and_does_not_touch_other_agent(tmp_path, monkeypatch):
    state = {"foreign_id": None}

    class _Reviewer:
        def __init__(self, *args, **kwargs):
            pass

        def enrich(self, text):
            from luminary_memory.ingest.llm import EnrichedContent

            return EnrichedContent(content=text, worth_saving=False)

        def review_turn(self, turn, memories):
            assert all(memory.id != state["foreign_id"] for memory in memories)
            return json.dumps({"captures": [], "actions": []})

    provider = _provider(tmp_path, monkeypatch, _Reviewer)
    from luminary_memory.api import MemoryClient

    foreign_client = MemoryClient(
        settings=provider._client.settings,
        engine=_FakeEngine(),
        scope={"agent_id": "other-agent"},
    )
    foreign_id = foreign_client.ingest(
        "A fact belonging to another agent.",
        source="foreign",
        evidence_quote="A fact belonging to another agent.",
        enrich=False,
    )
    foreign_client.close()
    state["foreign_id"] = foreign_id
    provider.sync_turn("A local turn with no mutation.", "Okay.", session_id="session-1")
    _wait(provider)

    foreign = provider._client.backend.get(foreign_id)
    assert foreign is not None and foreign.status == "active"
    provider.shutdown()


def test_reviewer_serializes_after_normal_retain_and_deduplicates_repeated_capture(
    tmp_path, monkeypatch
):
    seen = []

    class _Reviewer:
        def __init__(self, *args, **kwargs):
            pass

        def enrich(self, text):
            from luminary_memory.ingest.llm import EnrichedContent

            return EnrichedContent(
                content=text,
                summary="The user chose the stable channel.",
                worth_saving=True,
            )

        def review_turn(self, turn, memories):
            seen.append([memory.content for memory in memories])
            return json.dumps(
                {
                    "captures": [
                        {
                            "content": "The user chose the stable channel.",
                            "evidence_quote": "I chose the stable channel.",
                        }
                    ],
                    "actions": [],
                }
            )

    provider = _provider(tmp_path, monkeypatch, _Reviewer)
    provider.sync_turn("I chose the stable channel.", "Confirmed.", session_id="session-1")
    provider.sync_turn("I chose the stable channel.", "Confirmed.", session_id="session-1")
    _wait(provider)

    memories = provider._client.list(limit=0)
    assert len(memories) == 1
    assert memories[0].source == "hermes"
    assert seen and all("The user chose the stable channel." in batch for batch in seen)
    provider.shutdown()


def test_reviewer_survives_long_run_of_turns_without_duplicate_growth(tmp_path, monkeypatch):
    calls = []

    class _Reviewer:
        def __init__(self, *args, **kwargs):
            pass

        def enrich(self, text):
            from luminary_memory.ingest.llm import EnrichedContent

            return EnrichedContent(content=text, worth_saving=False)

        def review_turn(self, turn, memories):
            calls.append(turn)
            marker = turn.split("fact-", 1)[1].split(".", 1)[0]
            return json.dumps(
                {
                    "captures": [
                        {
                            "content": f"Durable fact {marker} remains relevant.",
                            "evidence_quote": f"Remember fact-{marker}.",
                        }
                    ],
                    "actions": [],
                }
            )

    provider = _provider(tmp_path, monkeypatch, _Reviewer)
    for index in range(120):
        provider.sync_turn(
            f"Remember fact-{index}.",
            "Acknowledged.",
            session_id="session-1",
        )
    _wait(provider, timeout=30.0)

    memories = provider._client.list(limit=0)
    assert len(calls) == 120
    assert len(memories) == 120
    assert provider._writer_thread is not None and provider._writer_thread.is_alive()
    assert len({memory.content for memory in memories}) == 120
    provider.shutdown()
