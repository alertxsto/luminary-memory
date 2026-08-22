from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class EnrichedContent:
    content: str
    summary: str | None = None
    entities: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    worth_saving: bool = True
    importance: float | None = None  # explicit importance hint (rules get high)
    # Optional structured claims.  The legacy summary fields remain for
    # compatibility; validated claims give the writer a canonical key and a
    # grounded evidence quote instead of treating an embedding as truth.
    claims: list[dict] = field(default_factory=list)


class LLMEnricher:
    def enrich(self, text: str) -> EnrichedContent:
        raise NotImplementedError

    def review_memories(self, memories: list) -> str:
        """Return a JSON actions payload for curating *memories*.

        Each memory has ``id`` and ``content``. The default implementation
        calls :meth:`enrich`; subclasses may override for a dedicated prompt.
        """
        import json as _json

        items = "\n".join(
            f'- {{"id": {m.id}, "content": {_json.dumps(str(getattr(m, "content", ""))[:300])}}}'
            for m in memories
        )
        prompt = (
            "Review this memory store. For each item decide: \"keep\", \"update\" "
            "(with replacement content), or \"delete\" (obsolete, contradicted, or "
            "duplicate). Return STRICT JSON: {\"actions\": [{\"id\": N, \"action\": "
            "\"keep|update|delete\", \"content\": \"new content if update\"}]}. "
            "No extra keys, no markdown.\n\nMemories:\n" + items
        )
        return self.enrich(prompt).content


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
        max_tokens: int | None = None,
        rule_keywords: str | None = None,
        rule_importance: float | None = None,
    ):
        from luminary_memory.config import Settings

        s = Settings()
        self.base_url = (base_url if base_url is not None else s.llm_base_url or "").rstrip("/")
        self.api_key = api_key if api_key is not None else s.llm_api_key
        self.model = model if model is not None else s.llm_model
        self.timeout = int(timeout if timeout is not None else s.llm_timeout)
        self.max_tokens = int(max_tokens if max_tokens is not None else s.llm_max_tokens)
        self.rule_keywords = rule_keywords if rule_keywords is not None else s.rule_keywords
        self.rule_importance = float(rule_importance if rule_importance is not None else s.rule_importance)

    def _call_llm(self, messages: list[dict]) -> str:
        """Call the OpenAI-compatible endpoint, return the assistant content."""
        import urllib.request

        url = f"{self.base_url}/chat/completions"
        body = json.dumps({
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": self.max_tokens,
        }).encode()
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "luminary-memory",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        for attempt in range(2):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read()
                    payload = json.loads(raw.decode() if isinstance(raw, (bytes, bytearray)) else str(raw))
                    # Some OpenAI-compatible gateways (e.g. the cline gateway) wrap the
                    # standard ChatCompletion shape inside a top-level "data" envelope:
                    #   {"data": {"choices": [...]}}
                    # Unwrap it so we always read "choices" from the payload root.
                    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
                        payload = payload["data"]
                    try:
                        choices = payload.get("choices") or []
                        if choices:
                            return (choices[0].get("message") or {}).get("content") or ""
                    except Exception:  # noqa: BLE001, S110
                        pass
                    return ""
            except Exception as exc:
                if attempt == 0:
                    import time
                    time.sleep(0.3)
                    continue
                logger.warning("enricher call failed after retry: %s", exc)
                raise
        return ""

    def enrich(self, text: str) -> EnrichedContent:
        if not self.base_url:
            return EnrichedContent(content=text)
        try:
            content_str = self._call_llm(
                [
                    {
                        "role": "system",
                        "content": (
                            "You are a memory curation helper for an AI agent's long-term memory. "
                            "Given a conversation turn (User/Assistant), decide whether it contains "
                            "durable, useful facts worth remembering — preferences, decisions, "
                            "environment details, project conventions, instructions. "
                            "A fact is worth saving if it will still matter days or weeks from now. "
                            "Be selective, not permissive: save only NEW durable facts. "
                            "If the turn repeats something already known (same preference, same "
                            "decision, same convention), do NOT save a duplicate. "
                            "Skip pure work-log ('done', 'pushed', 'fixed', 'deployed') that carries "
                            "no durable fact, and skip chit-chat, greetings, and meta-conversation "
                            "about the assistant itself. "
                            "When a turn contains both work-log and a real new fact, save ONLY the "
                            "fact, summarized tightly. "
                            "One fact per entry. If a turn has multiple distinct facts, keep the "
                            "most durable one and summarize it; do not dump the whole turn. "
                            "Return STRICT JSON with exactly these keys:\n"
                            "- worth_saving (boolean): true only when a NEW durable fact exists; "
                            "false for pure work-log, chit-chat, duplicates, or meta-talk.\n"
                            "- summary (string): if worth_saving is true, a concise factual summary "
                            "in the same language as the turn (e.g. 'User prefers X', 'Deploy target "
                            "is Y', 'Project publishes only via Trusted Publisher'). If false, an "
                            "empty string.\n"
                            "- entities (list of strings): key nouns/names mentioned. Empty if false.\n"
                            "- tags (list of strings): 1-3 short tags. Empty if false.\n"
                            "- claims (list): atomic claims with subject, predicate, object, "
                            "polarity, confidence, evidence_quote, and optional valid_from/valid_to. "
                            "The evidence_quote MUST be copied from the turn. Empty if false.\n"
                            "No extra keys, no markdown."
                        ),
                    },
                    {"role": "user", "content": text},
                ]
            )
            data = _parse_enrichment_payload(content_str)
            summary = data.get("summary")
            entities = data.get("entities") or []
            tags = data.get("tags") or []
            claims = data.get("claims") or []
            worth = data.get("worth_saving")
            # Normalize to expected types.
            if not isinstance(entities, list):
                entities = []
            if not isinstance(tags, list):
                tags = []
            if not isinstance(claims, list):
                claims = []
            if not isinstance(summary, str):
                summary = None
            # Auto-importance for rules: only a *curated summary* that reads
            # like an instruction ("must", "never", "always", "do not", etc.)
            # is a durable rule the agent must not forget. Keywords are
            # configurable via LUMINARY_RULE_KEYWORDS (English defaults).
            #
            # The rule check runs against the summary (the LLM's distilled
            # fact), never the raw transcript. A raw turn that merely mentions
            # a rule keyword is conversation, not a rule — flagging it would
            # pin noise as high-importance. When enrichment failed (no
            # summary), there is no curated fact at all, so the memory cannot
            # be a rule.
            summary_s = summary if summary and summary.strip() else ""
            rule_keywords = (
                s.strip().upper()
                for s in self.rule_keywords.split(",")
                if s.strip()
            )
            importance: float | None = None
            if summary_s and any(kw in summary_s.upper() for kw in rule_keywords):
                importance = self.rule_importance

            validated_claims: list[dict] = []
            for claim in claims:
                if not isinstance(claim, dict):
                    continue
                subject = str(claim.get("subject") or "").strip()
                predicate = str(claim.get("predicate") or "").strip()
                obj = str(claim.get("object") or "").strip()
                quote = str(claim.get("evidence_quote") or "").strip()
                polarity = str(claim.get("polarity") or "positive").strip().lower()
                if not subject or not predicate or not obj or not quote:
                    continue
                if quote not in text:
                    continue
                if polarity not in {"positive", "negative", "unknown"}:
                    continue
                try:
                    claim_confidence = max(0.0, min(1.0, float(claim.get("confidence", 1.0))))
                except (TypeError, ValueError):
                    continue
                validated_claims.append(
                    {
                        "subject": subject,
                        "predicate": predicate,
                        "object": obj,
                        "polarity": polarity,
                        "confidence": claim_confidence,
                        "evidence_quote": quote,
                        "observed_at": claim.get("observed_at"),
                        "valid_from": claim.get("valid_from"),
                        "valid_to": claim.get("valid_to"),
                    }
                )

            return EnrichedContent(
                content=text,
                summary=summary if summary and summary.strip() else None,
                entities=[str(x) for x in entities if isinstance(x, str) and x.strip()],
                tags=[str(x).strip() for x in tags if isinstance(x, str) and x.strip()],
                worth_saving=bool(worth) if worth is not None else True,
                importance=importance,
                claims=validated_claims,
            )
        except Exception:  # noqa: BLE001 -- enrichment is best-effort
            return EnrichedContent(content=text)

    def review_memories(self, memories: list) -> str:
        """Curate the store: return a JSON actions payload (keep/update/delete)."""
        if not self.base_url:
            return "{}"
        try:
            import json as _json

            items = "\n".join(
                f'- {{"id": {m.id}, "content": {_json.dumps(str(getattr(m, "content", ""))[:300])}}}'
                for m in memories
            )
            return self._call_llm(
                [
                    {
                        "role": "system",
                        "content": (
                            "You are a memory curator for an AI agent's long-term memory store. "
                            "Review each memory and decide: \"keep\", \"update\" (provide new "
                            "content), or \"delete\" (obsolete, contradicted, or duplicate). "
                            "Return STRICT JSON: {\"actions\": [{\"id\": N, \"action\": "
                            "\"keep|update|delete\", \"content\": \"new content if update\"}]}. "
                            "No extra keys, no markdown."
                        ),
                    },
                    {"role": "user", "content": items},
                ]
            )
        except Exception:  # noqa: BLE001 -- curation is best-effort
            return "{}"
