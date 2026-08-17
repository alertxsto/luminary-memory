from __future__ import annotations

import json
import re
from dataclasses import dataclass, field


@dataclass
class EnrichedContent:
    content: str
    summary: str | None = None
    entities: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    worth_saving: bool = True


class LLMEnricher:
    def enrich(self, text: str) -> EnrichedContent:
        raise NotImplementedError


class NoopEnricher(LLMEnricher):
    def enrich(self, text: str) -> EnrichedContent:
        return EnrichedContent(content=text)


_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)


def _strip_fences(s: str) -> str:
    m = _FENCE_RE.search(s)
    return m.group(1).strip() if m else s.strip()


def _parse_enrichment_payload(raw: str) -> dict:
    raw = _strip_fences(raw)
    # Try strict JSON first, then best-effort substring extraction.
    try:
        return json.loads(raw)
    except Exception:  # noqa: BLE001, S110
        pass
    # Extract first {...} block.
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except Exception:  # noqa: BLE001, S110
            pass
    return {}


class OpenAICompatibleEnricher(LLMEnricher):
    """Provider-agnostic enricher over any OpenAI-compatible chat/completions endpoint.

    Uses stdlib ``urllib.request`` so no new runtime dependency is introduced.
    Any failure (network, timeout, malformed body) returns a passthrough
    ``EnrichedContent`` with the original text.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
    ):
        from luminary_memory.config import Settings

        s = Settings()
        self.base_url = (base_url if base_url is not None else s.llm_base_url or "").rstrip("/")
        self.api_key = api_key if api_key is not None else s.llm_api_key
        self.model = model if model is not None else s.llm_model
        self.timeout = int(timeout if timeout is not None else s.llm_timeout)

    def enrich(self, text: str) -> EnrichedContent:
        if not self.base_url:
            return EnrichedContent(content=text)
        try:
            import urllib.request

            url = f"{self.base_url}/chat/completions"
            body = json.dumps(
                {
                    "model": self.model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You are a memory curation helper for an AI agent's long-term memory. "
                                "Given a conversation turn (User/Assistant), decide whether it contains "
                                "durable, useful facts worth remembering — preferences, decisions, "
                                "environment details, project conventions, instructions. "
                                "Return STRICT JSON with exactly these keys:\n"
                                "- worth_saving (boolean): true only if the turn contains a durable, "
                                "non-obvious fact. false for chit-chat, greetings, trivial "
                                "acknowledgements, or one-off questions.\n"
                                "- summary (string): if worth_saving is true, a concise factual summary "
                                "in the same language as the turn (e.g. 'User prefers X', 'Deploy target "
                                "is Y'). If false, an empty string.\n"
                                "- entities (list of strings): key nouns/names mentioned. Empty if false.\n"
                                "- tags (list of strings): 1-3 short tags. Empty if false.\n"
                                "No extra keys, no markdown."
                            ),
                        },
                        {"role": "user", "content": text},
                    ],
                    "temperature": 0,
                }
            ).encode()
            headers = {
                "Content-Type": "application/json",
                "User-Agent": "luminary-memory/0.2.1",
            }
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                payload = json.loads(raw.decode() if isinstance(raw, (bytes, bytearray)) else str(raw))
                # OpenAI shape: choices[0].message.content is a JSON string.
                content_str = ""
                try:
                    choices = payload.get("choices") or []
                    if choices:
                        content_str = (choices[0].get("message") or {}).get("content") or ""
                except Exception:  # noqa: BLE001
                    content_str = ""
                data = _parse_enrichment_payload(content_str)
                summary = data.get("summary")
                entities = data.get("entities") or []
                tags = data.get("tags") or []
                worth = data.get("worth_saving")
                # Normalize to expected types.
                if not isinstance(entities, list):
                    entities = []
                if not isinstance(tags, list):
                    tags = []
                if not isinstance(summary, str):
                    summary = None
                return EnrichedContent(
                    content=text,
                    summary=summary if summary and summary.strip() else None,
                    entities=[str(x) for x in entities if isinstance(x, str) and x.strip()],
                    tags=[str(x).strip() for x in tags if isinstance(x, str) and x.strip()],
                    worth_saving=bool(worth) if worth is not None else True,
                )
        except Exception:  # noqa: BLE001 -- enrichment is best-effort
            return EnrichedContent(content=text)
