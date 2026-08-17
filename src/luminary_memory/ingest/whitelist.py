from __future__ import annotations

import re


class WhitelistFilter:
    def __init__(self, patterns: list[str] | None = None, min_length: int = 3):
        self.min_length = min_length
        compiled: list[re.Pattern] = []
        for p in (patterns or []):
            try:
                compiled.append(re.compile(p, re.IGNORECASE))
            except re.error:
                # Invalid regex from user config: ignore the pattern rather
                # than crashing at construction time.
                continue
        self._patterns = compiled

    def accepts(self, text: str) -> bool:
        if not text.strip():
            return False
        if len(text.strip()) < self.min_length:
            return False
        if not self._patterns:
            return True
        return any(p.search(text) for p in self._patterns)
