"""Compatibility matcher for caller-supplied phrases.

This module is intentionally vocabulary-agnostic. The matcher is retained
for callers that already provide their own terms; it is not used to decide
whether a memory is durable, important, or authoritative.
"""

from __future__ import annotations

import re
from collections.abc import Iterable


def contains_rule_keyword(text: str, keywords: str | Iterable[str] | None) -> bool:
    """Return whether *text* contains a configured whole word/phrase.

    Plain substring matching creates false positives when a short configured
    term appears inside a larger token; boundary matching preserves phrase
    support without assigning meaning to the matched vocabulary.

    This compatibility helper is not part of the active durability or
    importance pipeline.
    """
    if not text or not keywords:
        return False
    values = keywords.split(",") if isinstance(keywords, str) else keywords
    for value in values:
        phrase = str(value or "").strip()
        if phrase and re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text, re.IGNORECASE):
            return True
    return False
