"""Shared rule-keyword matching with token-safe boundaries."""

from __future__ import annotations

import re
from collections.abc import Iterable


def contains_rule_keyword(text: str, keywords: str | Iterable[str] | None) -> bool:
    """Return whether *text* contains a configured whole word/phrase.

    Rule keywords are usually imperative words (``MUST``, ``NEVER``) or
    phrases (``DO NOT``). Plain substring matching creates false positives such
    as ``must`` inside ``mustard``; boundary matching preserves phrase support
    without pinning unrelated prose.
    """
    if not text or not keywords:
        return False
    values = keywords.split(",") if isinstance(keywords, str) else keywords
    for value in values:
        phrase = str(value or "").strip()
        if phrase and re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text, re.IGNORECASE):
            return True
    return False
