from __future__ import annotations

import re


class WhitelistFilter:
    def __init__(self, patterns: list[str] | None = None, min_length: int = 3):
        self.min_length = min_length
        self._patterns = [re.compile(p, re.IGNORECASE) for p in (patterns or [])]

    def accepts(self, text: str) -> bool:
        if not text.strip():
            return False
        if len(text.strip()) < self.min_length:
            return False
        if not self._patterns:
            return True
        return any(p.search(text) for p in self._patterns)
