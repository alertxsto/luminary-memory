from __future__ import annotations

import json
import logging
import math
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
    importance: float | None = None  # explicit structured importance hint
    # Optional structured claims.  The legacy summary fields remain for
    # compatibility; validated claims give the writer a canonical key and a
    # grounded evidence quote instead of treating an embedding as truth.
    claims: list[dict] = field(default_factory=list)
    # A transport/parse failure is distinct from a valid "nothing durable"
    # decision. Keeping that distinction lets the provider report reality
    # without promoting the raw turn into durable memory.
    error: str | None = None


class LLMEnricher:
    def enrich(self, text: str) -> EnrichedContent:
        raise NotImplementedError

    def review_turn(self, turn: str, memories: list) -> str:
        """Return a grounded reconciliation payload for one completed turn.

        This is deliberately a separate contract from :meth:`enrich`.  The
        enrichment pass decides whether the current turn deserves a memory;
        the review pass compares the turn with scoped candidates and may
        propose an explicitly evidenced capture, supersession, or retraction.
        Providers that do not implement incremental review safely no-op.
        """
        return "{}"

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


def _review_unit_score(value, default: float = 1.0) -> float:
    try:
        score = float(value)
        return max(0.0, min(1.0, score)) if math.isfinite(score) else default
    except (TypeError, ValueError):
        return default


def _normalize_review_claim(claim, turn_text: str) -> dict | None:
    """Validate a claim proposed by the incremental reviewer.

    Evidence is the security boundary here: a claim is usable only when its
    quote is copied from the current turn.  No vocabulary, language, or
    keyword policy belongs in this parser.
    """
    if not isinstance(claim, dict):
        return None
    subject = str(claim.get("subject") or "").strip()
    predicate = str(claim.get("predicate") or "").strip()
    obj = str(claim.get("object") or "").strip()
    quote = str(claim.get("evidence_quote") or "").strip()
    polarity = str(claim.get("polarity") or "positive").strip().lower()
    if not subject or not predicate or not obj or not quote:
        return None
    if len(subject) > 300 or len(predicate) > 300 or len(obj) > 500 or len(quote) > 1000:
        return None
    if quote not in turn_text or polarity not in {"positive", "negative", "unknown"}:
        return None
    return {
        "subject": subject,
        "predicate": predicate,
        "object": obj,
        "polarity": polarity,
        "confidence": _review_unit_score(claim.get("confidence"), default=1.0),
        "evidence_quote": quote,
        "observed_at": claim.get("observed_at"),
        "valid_from": claim.get("valid_from"),
        "valid_to": claim.get("valid_to"),
    }


def parse_turn_review_payload(
    raw: str,
    turn_text: str,
    candidate_ids: set[int] | None = None,
) -> dict:
    """Return only structurally valid, evidence-grounded review decisions.

    The LLM is untrusted input.  This function constrains IDs to the candidate
    set, bounds payload sizes, and requires every mutating decision to cite the
    current turn verbatim.  It intentionally does not classify prose by
    language or by hardcoded words.
    """
    data = _parse_enrichment_payload(raw)
    if not isinstance(data, dict):
        return {"captures": [], "actions": [], "rejected": 1}

    allowed_ids = {int(value) for value in candidate_ids or set()}
    rejected = 0
    captures: list[dict] = []
    raw_captures = data.get("captures") or []
    if not isinstance(raw_captures, list):
        raw_captures = []
        rejected += 1
    for item in raw_captures:
        if not isinstance(item, dict):
            rejected += 1
            continue
        content_value = item.get("content")
        evidence_value = item.get("evidence_quote")
        content = content_value.strip() if isinstance(content_value, str) else ""
        evidence_quote = evidence_value.strip() if isinstance(evidence_value, str) else ""
        if (
            not content
            or len(content) > 2000
            or not evidence_quote
            or len(evidence_quote) > 1000
            or evidence_quote not in turn_text
        ):
            rejected += 1
            continue
        tags_value = item.get("tags") or []
        tags = []
        if isinstance(tags_value, list):
            for tag in tags_value[:8]:
                if isinstance(tag, str) and tag.strip():
                    tags.append(tag.strip()[:100])
        claims_value = item.get("claims")
        if claims_value is None and isinstance(item.get("claim"), dict):
            claims_value = [item["claim"]]
        if claims_value is None:
            claims_value = []
        if not isinstance(claims_value, list):
            rejected += 1
            continue
        claims = []
        invalid_claim = False
        for claim in claims_value[:4]:
            normalized = _normalize_review_claim(claim, turn_text)
            if normalized is not None:
                claims.append(normalized)
            else:
                invalid_claim = True
        if invalid_claim:
            rejected += 1
            continue
        captures.append(
            {
                "content": content,
                "evidence_quote": evidence_quote,
                "tags": list(dict.fromkeys(tags)),
                "importance": _review_unit_score(item.get("importance"), default=0.5),
                "confidence": _review_unit_score(item.get("confidence"), default=1.0),
                "claims": claims,
            }
        )

    actions: list[dict] = []
    raw_actions = data.get("actions") or []
    if not isinstance(raw_actions, list):
        raw_actions = []
        rejected += 1
    for item in raw_actions:
        if not isinstance(item, dict):
            rejected += 1
            continue
        try:
            memory_id = int(item.get("memory_id", item.get("id")))
        except (TypeError, ValueError):
            rejected += 1
            continue
        if candidate_ids is not None and memory_id not in allowed_ids:
            rejected += 1
            continue
        action = str(item.get("action") or "").strip().lower()
        if action == "keep":
            actions.append({"memory_id": memory_id, "action": "keep"})
            continue
        evidence_value = item.get("evidence_quote")
        evidence_quote = evidence_value.strip() if isinstance(evidence_value, str) else ""
        reason_value = item.get("reason")
        reason = reason_value.strip()[:500] if isinstance(reason_value, str) else ""
        if action == "supersede":
            content_value = item.get("content")
            content = content_value.strip() if isinstance(content_value, str) else ""
            if (
                not content
                or len(content) > 2000
                or not evidence_quote
                or len(evidence_quote) > 1000
                or evidence_quote not in turn_text
            ):
                rejected += 1
                continue
            claim = None
            if isinstance(item.get("claim"), dict):
                claim = _normalize_review_claim(item["claim"], turn_text)
                if claim is None:
                    rejected += 1
                    continue
            actions.append(
                {
                    "memory_id": memory_id,
                    "action": "supersede",
                    "content": content,
                    "evidence_quote": evidence_quote,
                    "reason": reason,
                    "claim": claim,
                }
            )
            continue
        if action == "retract":
            if not evidence_quote or len(evidence_quote) > 1000 or evidence_quote not in turn_text:
                rejected += 1
                continue
            actions.append(
                {
                    "memory_id": memory_id,
                    "action": "retract",
                    "evidence_quote": evidence_quote,
                    "reason": reason,
                }
            )
            continue
        rejected += 1

    return {"captures": captures, "actions": actions, "rejected": rejected}


class OpenAICompatibleEnricher(LLMEnricher):
    """Provider-agnostic enricher over any OpenAI-compatible chat/completions endpoint.

    Uses ``requests`` for the HTTP transport (browser-like User-Agent and
    connection pooling). Any failure (network, timeout, malformed body)
    returns the original text with an explicit error marker. The provider
    can then keep the turn in its session ledger without confusing an
    outage with a valid curation decision.
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
        # Keep the legacy constructor arguments accepted for compatibility,
        # but never infer importance from prose or language-specific markers.
        # Importance must come from a structured caller value or the normal
        # estimator applied by MemoryClient.
        _ = (rule_keywords, rule_importance, s)

    def _call_llm(self, messages: list[dict]) -> str:
        """Call the OpenAI-compatible endpoint, return the assistant content."""
        import requests

        url = f"{self.base_url}/chat/completions"
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": self.max_tokens,
        }
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "luminary-memory/3 (+https://github.com/alertxsto/luminary-memory)",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        for attempt in range(2):
            try:
                resp = requests.post(
                    url,
                    json=body,
                    headers=headers,
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                payload = resp.json()
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
            except requests.RequestException as exc:
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
                importance=None,
                claims=validated_claims,
            )
        except Exception as exc:
            logger.warning("memory enricher failed: %s", type(exc).__name__, exc_info=True)
            return EnrichedContent(content=text, error=type(exc).__name__)

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

    def review_turn(self, turn: str, memories: list) -> str:
        """Reconcile a completed turn against a small scoped memory window."""
        if not self.base_url:
            return "{}"
        try:
            candidates = [
                {
                    "id": int(memory.id),
                    "content": str(getattr(memory, "content", ""))[:800],
                    "status": str(getattr(memory, "status", "active")),
                    "claim_key": getattr(memory, "claim_key", None),
                    "tags": list(getattr(memory, "tags", []) or [])[:8],
                    "confidence": getattr(memory, "confidence", None),
                }
                for memory in memories
                if getattr(memory, "id", None) is not None
            ]
            return self._call_llm(
                [
                    {
                        "role": "system",
                        "content": (
                            "You are an incremental long-term memory curator. Compare one "
                            "completed conversation turn with the candidate memories. Extract "
                            "only durable facts, preferences, decisions, identity, constraints, "
                            "or project conventions that are directly supported by the current "
                            "turn. Do not save greetings, transient work logs, assistant meta-talk, "
                            "or duplicates. A current turn may correct an existing claim only when "
                            "the correction is explicit. Never infer a mutation from similarity. "
                            "Every capture or mutation must include an exact substring from the "
                            "current turn as evidence_quote. Actions may target only candidate IDs. "
                            "Use supersede for a newer value of an existing claim and retract only "
                            "when the current turn explicitly invalidates it. Keep means no change. "
                            "Return STRICT JSON with exactly two arrays: captures and actions. "
                            "Schema: {\"captures\":[{\"content\":\"durable fact\","
                            "\"evidence_quote\":\"exact current-turn substring\",\"tags\":[],"
                            "\"importance\":0.0,\"confidence\":0.0,\"claim\":{\"subject\":\"\","
                            "\"predicate\":\"\",\"object\":\"\",\"polarity\":\"positive|negative|unknown\","
                            "\"confidence\":0.0,\"evidence_quote\":\"exact substring\"}}],"
                            "\"actions\":[{\"memory_id\":0,\"action\":\"keep|supersede|retract\","
                            "\"content\":\"new fact for supersede\",\"evidence_quote\":\"exact substring\","
                            "\"reason\":\"brief reason\",\"claim\":{}}]}. Omit claim when not needed. "
                            "No markdown, no extra keys."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {"turn": turn, "candidate_memories": candidates},
                            ensure_ascii=False,
                        ),
                    },
                ]
            )
        except Exception:  # noqa: BLE001 -- curation is best-effort
            return "{}"
