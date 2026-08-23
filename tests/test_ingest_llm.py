"""Tests for the OpenAI-compatible LLM enricher (ingest/llm.py)."""
import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from luminary_memory.ingest.llm import (
    EnrichedContent,
    LLMEnricher,
    NoopEnricher,
    OpenAICompatibleEnricher,
)


@pytest.fixture
def enricher():
    return OpenAICompatibleEnricher(
        base_url="https://example.com/v1",
        api_key="test-key",
        model="test-model",
        timeout=5,
    )


class TestEnrich:
    def test_empty_base_url_falls_back_to_verbatim(self):
        e = OpenAICompatibleEnricher(base_url="", api_key="", model="m")
        result = e.enrich("hello world")
        assert result.content == "hello world"
        assert result.summary is None
        assert result.worth_saving is True  # default

    def test_enrich_parses_payload(self, enricher):
        payload = json.dumps(
            {
                "worth_saving": True,
                "summary": "User prefers dark mode",
                "entities": ["dark mode", "user"],
                "tags": ["preference", "ui"],
            }
        )
        with patch.object(enricher, "_call_llm", return_value=payload) as mock:
            result = enricher.enrich("User: gw suka dark mode")
        mock.assert_called_once()
        assert result.summary == "User prefers dark mode"
        assert result.entities == ["dark mode", "user"]
        assert result.tags == ["preference", "ui"]
        assert result.worth_saving is True

    def test_enrich_not_worth_saving(self, enricher):
        payload = json.dumps({"worth_saving": False, "summary": "", "entities": [], "tags": []})
        with patch.object(enricher, "_call_llm", return_value=payload):
            result = enricher.enrich("User: ok thanks")
        assert result.worth_saving is False
        assert result.summary is None

    def test_enrich_malformed_json_keeps_verbatim(self, enricher):
        with patch.object(enricher, "_call_llm", return_value="not json at all"):
            result = enricher.enrich("some text")
        assert result.content == "some text"

    def test_enrich_network_error_falls_back(self, enricher):
        with patch.object(enricher, "_call_llm", side_effect=urllib.error.URLError("boom")):
            result = enricher.enrich("some text")
        assert result.content == "some text"
        assert result.worth_saving is True
        assert result.error == "URLError"

    def test_enrich_wrong_types_normalized(self, enricher):
        payload = json.dumps({"worth_saving": "yes", "summary": 123, "entities": "nope", "tags": None})
        with patch.object(enricher, "_call_llm", return_value=payload):
            result = enricher.enrich("text")
        assert result.worth_saving is True  # truthy string
        assert result.summary is None  # non-str dropped
        assert result.entities == []
        assert result.tags == []


class _FakeResp:
    def __init__(self, payload: dict):
        self._data = json.dumps(payload).encode()

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestCallLlm:
    def test_returns_choices_content(self, enricher):
        resp = _FakeResp({"choices": [{"message": {"content": "the answer"}}]})
        with patch("urllib.request.urlopen", return_value=resp) as mock:
            content = enricher._call_llm([{"role": "user", "content": "hi"}])
        assert content == "the answer"
        # URL + auth + user-agent
        req = mock.call_args.args[0]
        assert req.full_url == "https://example.com/v1/chat/completions"
        assert req.headers["Authorization"] == "Bearer test-key"
        # urllib normalizes header keys (User-Agent -> User-agent)
        ua = req.headers.get("User-Agent") or req.headers.get("User-agent") or req.headers.get("user-agent")
        assert ua and "luminary-memory" in ua

    def test_empty_choices_returns_empty(self, enricher):
        resp = _FakeResp({"choices": []})
        with patch("urllib.request.urlopen", return_value=resp):
            assert enricher._call_llm([{"role": "user", "content": "hi"}]) == ""

    def test_missing_message_content_returns_empty(self, enricher):
        resp = _FakeResp({"choices": [{"message": {}}]})
        with patch("urllib.request.urlopen", return_value=resp):
            assert enricher._call_llm([{"role": "user", "content": "hi"}]) == ""

    def test_http_error_propagates(self, enricher):
        with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError(
            "url", 500, "err", {}, None
        )), pytest.raises(urllib.error.HTTPError):
            enricher._call_llm([{"role": "user", "content": "hi"}])


class TestReviewMemories:
    def test_review_returns_actions_json(self, enricher):
        payload = json.dumps(
            {"actions": [{"id": 1, "action": "delete"}, {"id": 2, "action": "keep"}]}
        )
        with patch.object(enricher, "_call_llm", return_value=payload) as mock:
            out = enricher.review_memories([MagicMock(id=1, content="old fact"), MagicMock(id=2, content="good")])
        assert json.loads(out)["actions"][0]["id"] == 1
        # system prompt mentions curator, user message contains the items
        messages = mock.call_args.args[0]
        assert "curator" in messages[0]["content"]
        assert '"id": 1' in messages[1]["content"]

    def test_review_no_base_url_returns_empty(self):
        e = OpenAICompatibleEnricher(base_url="", api_key="", model="m")
        assert e.review_memories([MagicMock(id=1, content="x")]) == "{}"

    def test_review_network_error_returns_empty(self, enricher):
        with patch.object(enricher, "_call_llm", side_effect=urllib.error.URLError("boom")):
            assert enricher.review_memories([MagicMock(id=1, content="x")]) == "{}"


class TestNoopEnricher:
    def test_noop_passthrough(self):
        e = NoopEnricher()
        result = e.enrich("raw text")
        assert result.content == "raw text"
        assert result.worth_saving is True
        assert isinstance(result, EnrichedContent)


class TestLLMEnricherBase:
    def test_review_memories_default_impl_uses_enrich(self):
        """Base class review_memories builds the prompt and calls enrich()."""
        class _E(LLMEnricher):
            def enrich(self, text):
                return EnrichedContent(content=text, summary=None)

        e = _E()
        m1 = type("M", (), {"id": 1, "content": "fact one"})()
        m2 = type("M", (), {"id": 2, "content": "fact two"})()
        out = e.review_memories([m1, m2])
        assert '"id": 1' in out
        assert '"id": 2' in out
        assert "fact one" in out

    def test_enrich_not_implemented(self):
        e = LLMEnricher()
        try:
            e.enrich("x")
        except NotImplementedError:
            pass
        else:
            raise AssertionError("base enrich must raise NotImplementedError")
