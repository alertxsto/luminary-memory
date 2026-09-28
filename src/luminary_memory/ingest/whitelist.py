from __future__ import annotations

import re


class WhitelistFilter:
    """Content allowlist for ingestion.

    A configured allowlist must fail closed. An unparsable or blank pattern is
    a configuration error, not a pattern that silently disappears: dropping it
    would widen the policy the operator asked for, and an allowlist that ends
    up empty would then accept everything.
    """

    def __init__(self, patterns: list[str] | None = None, min_length: int = 3):
        self.min_length = min_length
        compiled: list[re.Pattern] = []
        for p in (patterns or []):
            if p is None or not str(p).strip():
                raise ValueError(f"invalid ingest allowlist pattern: {p!r}")
            try:
                compiled.append(re.compile(p, re.IGNORECASE))
            except re.error as exc:
                raise ValueError(f"invalid ingest allowlist pattern: {p!r}") from exc
        self._patterns = compiled
        # Distinguish "no policy configured" from "policy configured but
        # nothing compiled". The latter can no longer happen because invalid
        # patterns raise, but the flag keeps the distinction explicit.
        self.configured = bool(patterns)

    def accepts(self, text: str) -> bool:
        if not text.strip():
            return False
        if len(text.strip()) < self.min_length:
            return False
        if not self._patterns:
            return True
        return any(p.search(text) for p in self._patterns)
