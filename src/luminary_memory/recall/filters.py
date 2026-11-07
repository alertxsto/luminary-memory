"""Language-neutral filtering of transport/transcript artifacts at retrieval."""
from __future__ import annotations

import re

_STRUCTURAL_ARTIFACT_RE = re.compile(
    r"```|</?[ \t]*[A-Za-z][^>]{0,200}>|&&|={3,}|(?<!\|)\|(?!\|)",
    re.IGNORECASE,
)


def is_noise_memory(content: str) -> bool:
    """Reject dense structural dumps, not vocabulary, short facts or code terms."""
    text = (content or "").strip()
    if not text or not any(character.isalnum() for character in text):
        return True
    if text.count("```") >= 2:
        return True
    markers = _STRUCTURAL_ARTIFACT_RE.findall(text)
    return len(markers) >= 2 and len(markers) / max(len(text.split()), 1) >= 0.25
