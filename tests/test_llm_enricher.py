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

    with _patch.dict(os.environ, {"LUMINARY_RULE_KEYWORDS": "JANGAN PERNAH", "LUMINARY_RULE_IMPORTANCE": "0.85"}):
        s = Settings()
        assert "JANGAN PERNAH" in s.rule_keywords
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
        rule_keywords="JANGAN,WAJIB,HARUS",
    )
    with _patch("urllib.request.urlopen", _FakeUrlopen()):
        out = e.enrich("User: bikin PLAN dong kalo gitu\nAssistant: ok gw buatin plan")
    # Raw text contains "PLAN" but it is not in rule_keywords, and the curated
    # summary does not read like an instruction -> must NOT be flagged.
    assert out.importance is None, "raw mention of a rule keyword must not flag a rule"
    assert out.summary == "User delegated plan progress check to Command Code CLI"


def test_raw_rule_keyword_in_transcript_not_flagged():
    """Regression: a raw transcript that happens to contain a rule keyword
    (e.g. 'WAJIB') must not be pinned as a rule when the curated summary is
    not an instruction. This is exactly the id 205/206 pollution case."""
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
        rule_keywords="JANGAN,WAJIB,HARUS",
    )
    # Raw transcript literally contains "WAJIB" but summary is benign.
    with _patch("urllib.request.urlopen", _FakeUrlopen()):
        out = e.enrich("User: WAJIB cek dulu ya kalo mau push\nAssistant: siap, gw cek")
    assert out.importance is None, "raw WAJIB in transcript must not pin a rule"


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
                    "summary": "User WAJIB pakai markdown table di Telegram",
                    "entities": ["table"],
                    "tags": ["formatting"],
                })}}],
            }).encode()

    class _FakeUrlopen:
        def __call__(self, req, timeout=None):
            return _FakeResp()

    e = OpenAICompatibleEnricher(
        base_url="https://fake.example/v1", api_key="k", model="m",
        rule_keywords="JANGAN,WAJIB,HARUS",
    )
    with _patch("urllib.request.urlopen", _FakeUrlopen()):
        out = e.enrich("User: WAJIB pakai markdown table di telegram ya")
    assert out.importance == e.rule_importance
    assert out.importance == 0.9
