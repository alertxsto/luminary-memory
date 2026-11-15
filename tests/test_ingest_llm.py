"""Tests for the OpenAI-compatible LLM enricher (ingest/llm.py)."""
import json
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
        import requests

        with patch.object(enricher, "_call_llm", side_effect=requests.ConnectionError("boom")):
            result = enricher.enrich("some text")
        assert result.content == "some text"
        assert result.worth_saving is True
        assert result.error == "ConnectionError"

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
        self._data = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestCallLlm:
    def test_returns_choices_content(self, enricher):
        resp = _FakeResp({"choices": [{"message": {"content": "the answer"}}]})
        with patch("requests.post", return_value=resp) as mock:
            content = enricher._call_llm([{"role": "user", "content": "hi"}])
        assert content == "the answer"
        # URL + auth + user-agent
        args = mock.call_args.args
        kwargs = mock.call_args.kwargs
        assert args[0] == "https://example.com/v1/chat/completions"
        assert kwargs["headers"]["Authorization"] == "Bearer test-key"
        ua = kwargs["headers"].get("User-Agent") or kwargs["headers"].get("user-agent")
        assert ua and "luminary-memory" in ua

    def test_empty_choices_returns_empty(self, enricher):
        resp = _FakeResp({"choices": []})
        with patch("requests.post", return_value=resp):
            assert enricher._call_llm([{"role": "user", "content": "hi"}]) == ""

    def test_missing_message_content_returns_empty(self, enricher):
        resp = _FakeResp({"choices": [{"message": {}}]})
        with patch("requests.post", return_value=resp):
            assert enricher._call_llm([{"role": "user", "content": "hi"}]) == ""

    def test_http_error_propagates(self, enricher):
        import requests

        with patch("requests.post", side_effect=requests.HTTPError("500 err")), pytest.raises(requests.HTTPError):
            enricher._call_llm([{"role": "user", "content": "hi"}])

    def test_transport_error_log_does_not_expose_exception_text(self, enricher, caplog):
        import requests

        with patch("requests.post", side_effect=requests.ConnectionError("secret prompt test-key")), \
                patch("time.sleep"), pytest.raises(requests.ConnectionError):
            enricher._call_llm([])
        assert "secret prompt" not in caplog.text
        assert "test-key" not in caplog.text

    def test_usage_aggregates_enveloped_and_root_provider_values(self, enricher):
        responses = [
            _FakeResp({"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}}),
            _FakeResp({"data": {"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 1, "total_tokens": 8}}}),
        ]
        with patch("requests.post", side_effect=responses):
            enricher._call_llm([{"role": "user", "content": "private prompt"}])
            enricher._call_llm([])
        snapshot = enricher.usage_snapshot()
        assert snapshot == {
            "calls": 2, "attempts": 2, "prompt_tokens": 10,
            "completion_tokens": 3, "total_tokens": 13,
        }
        assert "private" not in repr(snapshot)
        assert "test-key" not in repr(snapshot)

    def test_usage_is_unknown_for_failed_retry_and_missing_fields(self, enricher):
        import requests

        response = _FakeResp({"data": {"choices": []}, "usage": {
            "prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7,
        }})
        with patch("requests.post", side_effect=[requests.ConnectionError("private"), response]), \
                patch("time.sleep"):
            enricher._call_llm([])
        assert enricher.usage_snapshot() == {
            "calls": 1, "attempts": 2, "prompt_tokens": None,
            "completion_tokens": None, "total_tokens": None,
        }

    def test_usage_envelope_conflict_and_invalid_values_are_unknown(self, enricher):
        response = _FakeResp({
            "usage": {"prompt_tokens": 3, "completion_tokens": -1, "total_tokens": 4},
            "data": {"choices": [], "usage": {
                "prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5,
            }},
        })
        with patch("requests.post", return_value=response):
            enricher._call_llm([])
        assert enricher.usage_snapshot() == {
            "calls": 1, "attempts": 1, "prompt_tokens": None,
            "completion_tokens": None, "total_tokens": None,
        }

    def test_usage_missing_after_known_response_is_not_zero(self, enricher):
        with patch("requests.post", side_effect=[
            _FakeResp({"choices": [], "usage": {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5}}),
            _FakeResp({"choices": []}),
        ]):
            enricher._call_llm([])
            enricher._call_llm([])
        assert enricher.usage_snapshot()["total_tokens"] is None

    def test_outer_envelope_usage_is_not_lost(self, enricher):
        with patch("requests.post", return_value=_FakeResp({
            "data": {"choices": []},
            "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
        })):
            enricher._call_llm([])
        assert enricher.usage_snapshot()["total_tokens"] == 3



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

    def test_review_requests_source_proposals_from_available_metadata(self, enricher):
        from luminary_memory.types import Memory

        memory = Memory(id=1, content="old fact", source_id="episode-1",
                        evidence_quote="original source words")
        with patch.object(enricher, "_call_llm", return_value='{"actions": []}') as call:
            assert enricher.review_memories([memory]) == '{"actions": []}'
        system, user = call.call_args.args[0]
        assert "source_id" in system["content"]
        assert "evidence_quote" in system["content"]
        assert "confirmed" not in system["content"]
        assert "episode-1" in user["content"]
        assert "original source words" in user["content"]

    def test_review_no_base_url_returns_empty(self):
        e = OpenAICompatibleEnricher(base_url="", api_key="", model="m")
        assert e.review_memories([MagicMock(id=1, content="x")]) == "{}"

    def test_review_network_error_returns_empty(self, enricher):
        import requests

        with patch.object(enricher, "_call_llm", side_effect=requests.ConnectionError("boom")):
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
