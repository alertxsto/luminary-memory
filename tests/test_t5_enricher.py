import json
from unittest.mock import MagicMock, patch

from luminary_memory.ingest.llm import OpenAICompatibleEnricher


def _fake_response(body: dict | str):
    raw = body if isinstance(body, dict) else json.loads(body)
    # fake requests response with json() and raise_for_status()
    m = MagicMock()
    m.json.return_value = raw
    m.raise_for_status.return_value = None
    return m


def _chat_body(content_json: dict):
    return {
        "choices": [{"message": {"content": json.dumps(content_json)}}]
    }


def test_enricher_parses_summary_entities_tags(monkeypatch):
    expected = {"summary": "short summary", "entities": ["alpha", "beta"], "tags": ["t1", "t2"]}
    fake = _fake_response(_chat_body(expected))
    with patch("requests.post", return_value=fake):
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
    with patch("requests.post", return_value=fake):
        e = OpenAICompatibleEnricher(base_url="http://fake", api_key="k", model="m")
        out = e.enrich("some text")
        assert out.tags == ["x"]


def test_enricher_passthrough_on_exception(monkeypatch):
    import requests

    def boom(*a, **k):
        raise requests.ConnectionError("network down")

    with patch("requests.post", side_effect=boom):
        e = OpenAICompatibleEnricher(base_url="http://fake", api_key="k", model="m")
        out = e.enrich("fallback text keeps original content")
        assert out.content == "fallback text keeps original content"
        assert out.summary is None


def test_enricher_uses_config_defaults(monkeypatch):
    # Settings-wired defaults via LUMINARY_* env or explicit Settings; enricher
    # falls back to Settings().llm_* when not passed. We just assert it can be
    # constructed with no args (reads Settings) and still calls requests.post correctly.
    fake = _fake_response(_chat_body({"summary": "s", "entities": [], "tags": []}))
    monkeypatch.setenv("LUMINARY_LLM_BASE_URL", "http://from-env")
    monkeypatch.setenv("LUMINARY_LLM_API_KEY", "env-key")
    with patch("requests.post", return_value=fake):
        e = OpenAICompatibleEnricher()
        out = e.enrich("env-configured enricher")
        assert out.content == "env-configured enricher"
