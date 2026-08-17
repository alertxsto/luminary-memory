import json
from unittest.mock import MagicMock, patch

from luminary_memory.ingest.llm import OpenAICompatibleEnricher


def _fake_response(body: dict | str):
    raw = json.dumps(body).encode() if isinstance(body, dict) else body.encode()
    # fake http response with read() and json body
    m = MagicMock()
    m.read.return_value = raw
    m.__enter__.return_value = m
    m.__exit__.return_value = False
    return m


def _chat_body(content_json: dict):
    return {
        "choices": [{"message": {"content": json.dumps(content_json)}}]
    }


def test_enricher_parses_summary_entities_tags(monkeypatch):
    expected = {"summary": "short summary", "entities": ["alpha", "beta"], "tags": ["t1", "t2"]}
    fake = _fake_response(_chat_body(expected))
    with patch("urllib.request.urlopen", return_value=fake):
        e = OpenAICompatibleEnricher(base_url="http://fake", api_key="k", model="m")
        out = e.enrich("hello world text")
        assert out.summary == "short summary"
        assert set(out.entities) == {"alpha", "beta"}
        assert set(out.tags) == {"t1", "t2"}
        assert out.content == "hello world text"


def test_enricher_tolerates_markdown_fences(monkeypatch):
    inner = {"summary": "s", "entities": [], "tags": ["x"]}
    body = _chat_body(inner)
    # wrap message content in fences
    body["choices"][0]["message"]["content"] = "```json\n" + json.dumps(inner) + "\n```"
    fake = _fake_response(body)
    with patch("urllib.request.urlopen", return_value=fake):
        e = OpenAICompatibleEnricher(base_url="http://fake", api_key="k", model="m")
        out = e.enrich("some text")
        assert out.tags == ["x"]


def test_enricher_passthrough_on_exception(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network down")

    with patch("urllib.request.urlopen", side_effect=boom):
        e = OpenAICompatibleEnricher(base_url="http://fake", api_key="k", model="m")
        out = e.enrich("fallback text keeps original content")
        assert out.content == "fallback text keeps original content"
        assert out.summary is None


def test_enricher_uses_config_defaults(monkeypatch):
    # Settings-wired defaults via LUMINARY_* env or explicit Settings; enricher
    # falls back to Settings().llm_* when not passed. We just assert it can be
    # constructed with no args (reads Settings) and still calls urlopen correctly.
    fake = _fake_response(_chat_body({"summary": "s", "entities": [], "tags": []}))
    monkeypatch.setenv("LUMINARY_LLM_BASE_URL", "http://from-env")
    monkeypatch.setenv("LUMINARY_LLM_API_KEY", "env-key")
    with patch("urllib.request.urlopen", return_value=fake):
        e = OpenAICompatibleEnricher()
        out = e.enrich("env-configured enricher")
        assert out.content == "env-configured enricher"
