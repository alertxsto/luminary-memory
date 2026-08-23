def test_call_llm_sends_max_tokens(tmp_path, monkeypatch):
    """The enricher must send max_tokens in the request body (issue #8:
    Command Code returns empty content without it)."""
    from unittest.mock import patch as _patch

    from luminary_memory.ingest.llm import OpenAICompatibleEnricher

    captured = {}

    class _FakeResp:
        def raise_for_status(self):
            return None
        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    class _FakePost:
        def __call__(self, url, json=None, headers=None, timeout=None):
            captured["body"] = json
            captured["url"] = url
            captured["headers"] = headers
            return _FakeResp()

    e = OpenAICompatibleEnricher(
        base_url="https://fake.example/v1", api_key="k", model="m", max_tokens=512
    )
    with _patch("requests.post", _FakePost()):
        out = e._call_llm([{"role": "user", "content": "hi"}])
    assert out == "ok"
    assert captured["body"]["max_tokens"] == 512


def test_importance_is_not_inferred_from_language_markers():
    """Durability must come from structured signals, not prose markers."""
    from luminary_memory.ingest.llm import OpenAICompatibleEnricher

    enricher = OpenAICompatibleEnricher(
        base_url="https://fake.example/v1",
        api_key="k",
        model="m",
        rule_keywords="MUST,ALWAYS,NEVER",
    )
    assert not hasattr(enricher, "rule_keywords")


def test_rule_importance_only_from_curated_summary():
    """A raw transcript that merely mentions a rule keyword must NOT be
    flagged as a rule; only the LLM's curated summary can be."""
    import json as _json
    from unittest.mock import patch as _patch

    from luminary_memory.ingest.llm import OpenAICompatibleEnricher

    class _FakeResp:
        def raise_for_status(self):
            return None
        def json(self):
            # LLM returns a summary that is NOT a rule, even though the raw
            # turn text contains "PLAN".
            return {
                "choices": [{"message": {"content": _json.dumps({
                    "worth_saving": True,
                    "summary": "User delegated plan progress check to Command Code CLI",
                    "entities": ["plan"],
                    "tags": ["planning"],
                })}}]
            }

    class _FakePost:
        def __call__(self, url, json=None, headers=None, timeout=None):
            return _FakeResp()

    e = OpenAICompatibleEnricher(
        base_url="https://fake.example/v1", api_key="k", model="m",
        rule_keywords="MUST,ALWAYS,NEVER",
    )
    with _patch("requests.post", _FakePost()):
        out = e.enrich("User: we must check before pushing anything\nAssistant: sure, checking now")
    # Raw text contains "must" (a rule keyword) but the curated summary does
    # not read like an instruction -> must NOT be flagged.
    assert out.importance is None, "raw mention of a rule keyword must not flag a rule"
    assert out.summary == "User delegated plan progress check to Command Code CLI"


def test_raw_rule_keyword_in_transcript_not_flagged():
    """Regression: a raw transcript that happens to contain a rule keyword
    (e.g. 'must') must not be pinned as a rule when the curated summary is
    not an instruction."""
    import json as _json
    from unittest.mock import patch as _patch

    from luminary_memory.ingest.llm import OpenAICompatibleEnricher

    class _FakeResp:
        def raise_for_status(self):
            return None
        def json(self):
            return {
                "choices": [{"message": {"content": _json.dumps({
                    "worth_saving": True,
                    "summary": "User asked about the deploy status report",
                    "entities": ["report"],
                    "tags": ["status"],
                })}}]
            }

    class _FakePost:
        def __call__(self, url, json=None, headers=None, timeout=None):
            return _FakeResp()

    e = OpenAICompatibleEnricher(
        base_url="https://fake.example/v1", api_key="k", model="m",
        rule_keywords="MUST,ALWAYS,NEVER",
    )
    # Raw transcript literally contains "must" but summary is benign.
    with _patch("requests.post", _FakePost()):
        out = e.enrich("User: we must check CI before merging\nAssistant: got it")
    assert out.importance is None, "raw must in transcript must not pin a rule"


def test_rule_like_summary_still_uses_normal_importance_estimation():
    """A summary's wording does not implicitly pin it."""
    import json as _json
    from unittest.mock import patch as _patch

    from luminary_memory.ingest.llm import OpenAICompatibleEnricher

    class _FakeResp:
        def raise_for_status(self):
            return None
        def json(self):
            return {
                "choices": [{"message": {"content": _json.dumps({
                    "worth_saving": True,
                    "summary": "User must always use markdown tables in Telegram replies",
                    "entities": ["table"],
                    "tags": ["formatting"],
                })}}]
            }

    class _FakePost:
        def __call__(self, url, json=None, headers=None, timeout=None):
            return _FakeResp()

    e = OpenAICompatibleEnricher(
        base_url="https://fake.example/v1", api_key="k", model="m",
        rule_keywords="MUST,ALWAYS,NEVER",
    )
    with _patch("requests.post", _FakePost()):
        out = e.enrich("User: always use markdown tables in Telegram replies")
    assert out.importance is None


def test_unwrap_data_envelope():
    """Regression: some OpenAI-compatible gateways (e.g. the cline gateway)
    wrap the standard ChatCompletion shape under a top-level 'data' key:
        {"data": {"choices": [...]}}
    The enricher must unwrap it and still read the assistant content. Without
    this, enrich() silently returns an empty summary and curation deadlocks
    ('no curated summary' in the retain path)."""
    import json as _json
    from unittest.mock import patch as _patch

    from luminary_memory.ingest.llm import OpenAICompatibleEnricher

    class _FakeResp:
        def raise_for_status(self):
            return None
        def json(self):
            return {
                "data": {
                    "choices": [{"message": {"content": _json.dumps({
                        "worth_saving": True,
                        "summary": "Deploy target moved to production cluster",
                        "entities": ["production cluster"],
                        "tags": ["deploy"],
                    })}}],
                }
            }

    class _FakePost:
        def __call__(self, url, json=None, headers=None, timeout=None):
            return _FakeResp()

    e = OpenAICompatibleEnricher(
        base_url="https://fake.example/v1", api_key="k", model="m",
    )
    with _patch("requests.post", _FakePost()):
        out = e.enrich("deploy target changed")
    assert out.summary == "Deploy target moved to production cluster"
    assert out.worth_saving is True
    assert out.entities == ["production cluster"]


def test_unwrap_data_envelope_plain_shape():
    """An endpoint that does NOT wrap in a 'data' envelope must keep working
    (backward compatible), reading choices straight from the payload root."""
    from unittest.mock import patch as _patch

    from luminary_memory.ingest.llm import OpenAICompatibleEnricher

    class _FakeResp:
        def raise_for_status(self):
            return None
        def json(self):
            return {
                "choices": [{"message": {"content": "plain ok"}}],
            }

    class _FakePost:
        def __call__(self, url, json=None, headers=None, timeout=None):
            return _FakeResp()

    e = OpenAICompatibleEnricher(
        base_url="https://fake.example/v1", api_key="k", model="m",
    )
    with _patch("requests.post", _FakePost()):
        out = e._call_llm([{"role": "user", "content": "hi"}])
    assert out == "plain ok"


def test_call_llm_retries_on_transient_error():
    """Verify that a transient network error triggers a 1x retry that can succeed."""
    from unittest.mock import patch as _patch

    import requests

    from luminary_memory.ingest.llm import OpenAICompatibleEnricher

    attempts = 0

    class _RetryPost:
        def __call__(self, url, json=None, headers=None, timeout=None):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise requests.ConnectionError("temporary glitch")

            class _FakeResp:
                def raise_for_status(self):
                    return None
                def json(self):
                    return {
                        "choices": [{"message": {"content": "retry succeeded"}}],
                    }

            return _FakeResp()

    e = OpenAICompatibleEnricher(
        base_url="https://fake.example/v1", api_key="k", model="m",
    )
    with _patch("requests.post", _RetryPost()), \
         _patch("time.sleep"):
        out = e._call_llm([{"role": "user", "content": "hi"}])
    assert attempts == 2
    assert out == "retry succeeded"


def test_turn_review_parser_is_candidate_and_evidence_bounded():
    import json as _json

    from luminary_memory.ingest.llm import parse_turn_review_payload

    turn = "User: I switched to the beta model.\nAssistant: I will remember that."
    raw = _json.dumps(
        {
            "captures": [
                {
                    "content": "The user prefers the beta model.",
                    "evidence_quote": "I switched to the beta model.",
                    "claim": {
                        "subject": "user",
                        "predicate": "preferred_model",
                        "object": "beta",
                        "polarity": "positive",
                        "evidence_quote": "I switched to the beta model.",
                    },
                },
                {
                    "content": "This must be rejected.",
                    "evidence_quote": "invented evidence",
                },
            ],
            "actions": [
                {
                    "memory_id": 7,
                    "action": "supersede",
                    "content": "The user prefers the beta model.",
                    "evidence_quote": "I switched to the beta model.",
                },
                {
                    "memory_id": 999,
                    "action": "retract",
                    "evidence_quote": "I switched to the beta model.",
                },
            ],
        }
    )

    parsed = parse_turn_review_payload(raw, turn, candidate_ids={7})

    assert len(parsed["captures"]) == 1
    assert parsed["captures"][0]["claims"][0]["object"] == "beta"
    assert len(parsed["actions"]) == 1
    assert parsed["actions"][0]["memory_id"] == 7
    assert parsed["rejected"] == 2


def test_turn_review_parser_rejects_partial_invalid_claims():
    import json as _json

    from luminary_memory.ingest.llm import parse_turn_review_payload

    turn = "User: I use the stable channel."
    parsed = parse_turn_review_payload(
        _json.dumps(
            {
                "captures": [
                    {
                        "content": "The user uses the stable channel.",
                        "evidence_quote": "I use the stable channel.",
                        "claims": [
                            {
                                "subject": "user",
                                "predicate": "channel",
                                "object": "stable",
                                "evidence_quote": "I use the stable channel.",
                            },
                            {
                                "subject": "user",
                                "predicate": "channel",
                                "object": "invented",
                                "evidence_quote": "not present",
                            },
                        ],
                    }
                ],
                "actions": [],
            }
        ),
        turn,
    )

    assert parsed["captures"] == []
    assert parsed["rejected"] == 1


def test_enrich_retries_on_truncated_reply():
    """A truncated JSON reply (worth_saving with no summary) triggers a retry."""
    import json as _json
    from unittest.mock import patch as _patch

    from luminary_memory.ingest.llm import OpenAICompatibleEnricher

    calls = {"n": 0}

    class _FlakyPost:
        def __call__(self, url, json=None, headers=None, timeout=None):
            calls["n"] += 1
            if calls["n"] == 1:
                # HTTP 200 but truncated JSON body.
                return type("R", (), {
                    "raise_for_status": lambda self: None,
                    "json": lambda self: {"choices": [{"message": {"content": '{\n  "worth_saving":'}}]},
                })()
            return type("R", (), {
                "raise_for_status": lambda self: None,
                "json": lambda self: {"choices": [{"message": {"content": _json.dumps({
                    "worth_saving": True,
                    "summary": "User deployed app to Vercel",
                    "entities": ["Vercel"],
                    "tags": ["deploy"],
                })}}]},
            })()

    e = OpenAICompatibleEnricher(
        base_url="https://fake.example/v1", api_key="k", model="m",
    )
    with _patch("requests.post", _FlakyPost()), _patch("time.sleep"):
        out = e.enrich("User: gw deploy app ke Vercel")
    assert calls["n"] == 2
    assert out.summary == "User deployed app to Vercel"
    assert out.error is None


def test_enrich_returns_error_after_two_truncated_replies():
    """Two consecutive truncated replies surface an explicit error, not a silent drop."""
    from unittest.mock import patch as _patch

    from luminary_memory.ingest.llm import OpenAICompatibleEnricher

    class _AlwaysTruncated:
        def __call__(self, url, json=None, headers=None, timeout=None):
            return type("R", (), {
                "raise_for_status": lambda self: None,
                "json": lambda self: {"choices": [{"message": {"content": '{\n  "worth_saving":'}}]},
            })()

    e = OpenAICompatibleEnricher(
        base_url="https://fake.example/v1", api_key="k", model="m",
    )
    with _patch("requests.post", _AlwaysTruncated()), _patch("time.sleep"):
        out = e.enrich("User: gw deploy app ke Vercel")
    assert out.error == "unusable_reply"
    assert out.summary is None
