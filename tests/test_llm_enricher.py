def test_call_llm_sends_max_tokens(tmp_path, monkeypatch):
    """The enricher must send max_tokens in the request body (issue #8:
    Command Code returns empty content without it)."""
    import json as _json
    from unittest.mock import patch as _patch

    from luminary_memory.ingest.llm import OpenAICompatibleEnricher

    captured = {}

    class _FakeResp:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self):
            return _json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()

    class _FakeUrlopen:
        def __call__(self, req, timeout=None):
            captured["body"] = _json.loads(req.data.decode())
            return _FakeResp()

    e = OpenAICompatibleEnricher(
        base_url="https://fake.example/v1", api_key="k", model="m", max_tokens=512
    )
    with _patch("urllib.request.urlopen", _FakeUrlopen()):
        out = e._call_llm([{"role": "user", "content": "hi"}])
    assert out == "ok"
    assert captured["body"]["max_tokens"] == 512
def test_rule_keywords_configurable():
    """Rule keywords/importance come from settings (no hardcode)."""
    import os
    from unittest.mock import patch as _patch

    from luminary_memory.config import Settings

    with _patch.dict(os.environ, {"LUMINARY_RULE_KEYWORDS": "NEVER,ALWAYS,MUST", "LUMINARY_RULE_IMPORTANCE": "0.85"}):
        s = Settings()
        assert "NEVER" in s.rule_keywords
        assert "ALWAYS" in s.rule_keywords
        assert s.rule_importance == 0.85


def test_rule_importance_only_from_curated_summary():
    """A raw transcript that merely mentions a rule keyword must NOT be
    flagged as a rule; only the LLM's curated summary can be."""
    import json as _json
    from unittest.mock import patch as _patch

    from luminary_memory.ingest.llm import OpenAICompatibleEnricher

    class _FakeResp:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self):
            # LLM returns a summary that is NOT a rule, even though the raw
            # turn text contains "PLAN".
            return _json.dumps({
                "choices": [{"message": {"content": _json.dumps({
                    "worth_saving": True,
                    "summary": "User delegated plan progress check to Command Code CLI",
                    "entities": ["plan"],
                    "tags": ["planning"],
                })}}],
            }).encode()

    class _FakeUrlopen:
        def __call__(self, req, timeout=None):
            return _FakeResp()

    e = OpenAICompatibleEnricher(
        base_url="https://fake.example/v1", api_key="k", model="m",
        rule_keywords="MUST,ALWAYS,NEVER",
    )
    with _patch("urllib.request.urlopen", _FakeUrlopen()):
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
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self):
            return _json.dumps({
                "choices": [{"message": {"content": _json.dumps({
                    "worth_saving": True,
                    "summary": "User asked about the deploy status report",
                    "entities": ["report"],
                    "tags": ["status"],
                })}}],
            }).encode()

    class _FakeUrlopen:
        def __call__(self, req, timeout=None):
            return _FakeResp()

    e = OpenAICompatibleEnricher(
        base_url="https://fake.example/v1", api_key="k", model="m",
        rule_keywords="MUST,ALWAYS,NEVER",
    )
    # Raw transcript literally contains "must" but summary is benign.
    with _patch("urllib.request.urlopen", _FakeUrlopen()):
        out = e.enrich("User: we must check CI before merging\nAssistant: got it")
    assert out.importance is None, "raw must in transcript must not pin a rule"


def test_rule_importance_from_rule_summary():
    """A curated summary that IS an instruction gets rule importance."""
    import json as _json
    from unittest.mock import patch as _patch

    from luminary_memory.ingest.llm import OpenAICompatibleEnricher

    class _FakeResp:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self):
            return _json.dumps({
                "choices": [{"message": {"content": _json.dumps({
                    "worth_saving": True,
                    "summary": "User must always use markdown tables in Telegram replies",
                    "entities": ["table"],
                    "tags": ["formatting"],
                })}}],
            }).encode()

    class _FakeUrlopen:
        def __call__(self, req, timeout=None):
            return _FakeResp()

    e = OpenAICompatibleEnricher(
        base_url="https://fake.example/v1", api_key="k", model="m",
        rule_keywords="MUST,ALWAYS,NEVER",
    )
    with _patch("urllib.request.urlopen", _FakeUrlopen()):
        out = e.enrich("User: always use markdown tables in Telegram replies")
    assert out.importance == e.rule_importance
    assert out.importance == 0.9


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
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self):
            return _json.dumps({
                "data": {
                    "choices": [{"message": {"content": _json.dumps({
                        "worth_saving": True,
                        "summary": "Deploy target moved to production cluster",
                        "entities": ["production cluster"],
                        "tags": ["deploy"],
                    })}}],
                }
            }).encode()

    class _FakeUrlopen:
        def __call__(self, req, timeout=None):
            return _FakeResp()

    e = OpenAICompatibleEnricher(
        base_url="https://fake.example/v1", api_key="k", model="m",
    )
    with _patch("urllib.request.urlopen", _FakeUrlopen()):
        out = e.enrich("deploy target changed")
    assert out.summary == "Deploy target moved to production cluster"
    assert out.worth_saving is True
    assert out.entities == ["production cluster"]


def test_unwrap_data_envelope_plain_shape():
    """An endpoint that does NOT wrap in a 'data' envelope must keep working
    (backward compatible), reading choices straight from the payload root."""
    import json as _json
    from unittest.mock import patch as _patch

    from luminary_memory.ingest.llm import OpenAICompatibleEnricher

    class _FakeResp:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self):
            return _json.dumps({
                "choices": [{"message": {"content": "plain ok"}}],
            }).encode()

    class _FakeUrlopen:
        def __call__(self, req, timeout=None):
            return _FakeResp()

    e = OpenAICompatibleEnricher(
        base_url="https://fake.example/v1", api_key="k", model="m",
    )
    with _patch("urllib.request.urlopen", _FakeUrlopen()):
        out = e._call_llm([{"role": "user", "content": "hi"}])
    assert out == "plain ok"


def test_call_llm_retries_on_transient_error():
    """Verify that a transient network error triggers a 1x retry that can succeed."""
    import json as _json
    from unittest.mock import patch as _patch

    from luminary_memory.ingest.llm import OpenAICompatibleEnricher

    attempts = 0

    class _RetryUrlopen:
        def __call__(self, req, timeout=None):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise OSError("temporary glitch")

            class _FakeResp:
                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

                def read(self):
                    return _json.dumps({
                        "choices": [{"message": {"content": "retry succeeded"}}],
                    }).encode()

            return _FakeResp()

    e = OpenAICompatibleEnricher(
        base_url="https://fake.example/v1", api_key="k", model="m",
    )
    with _patch("urllib.request.urlopen", _RetryUrlopen()), \
         _patch("time.sleep"):
        out = e._call_llm([{"role": "user", "content": "hi"}])
    assert attempts == 2
    assert out == "retry succeeded"

