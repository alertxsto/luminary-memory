from __future__ import annotations

import re


class WhitelistFilter:
    def __init__(self, patterns: list[str] | None = None, min_length: int = 3):
        self.min_length = min_length
        compiled: list[re.Pattern] = []
        if patterns is None or not patterns:
            self._patterns = compiled
            return
        for p in patterns:
            if not isinstance(p, str) or not p.strip():
                raise ValueError(f"invalid ingest allowlist pattern: {p!r}")
            try:
                compiled.append(re.compile(p, re.IGNORECASE))
            except re.error as exc:
                raise ValueError(f"invalid ingest allowlist pattern: {p!r}") from exc
        self._patterns = compiled

    def accepts(self, text: str) -> bool:
        if not text.strip():
            return False
        if len(text.strip()) < self.min_length:
            return False
        if not self._patterns:
            return True
        return any(p.search(text) for p in self._patterns)
