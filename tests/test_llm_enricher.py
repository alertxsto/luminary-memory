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
