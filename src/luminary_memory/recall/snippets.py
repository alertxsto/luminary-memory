from __future__ import annotations


def extract_snippet(content: str, query: str, width: int = 120) -> str:
    text = content or ""
    q = (query or "").strip()
    if not q:
        return text[:width].strip()

    lower = text.lower()
    # Find first occurrence of any query term (split on whitespace).
    terms = [t for t in q.lower().split() if t]
    pos = -1
    hit = ""
    for t in terms:
        idx = lower.find(t)
        if idx != -1 and (pos == -1 or idx < pos):
            pos = idx
            hit = t
    if pos == -1:
        return text[:width].strip()

    half = width // 2
    start = max(0, pos - half)
    end = min(len(text), pos + len(hit) + half)
    # Expand to word boundaries when possible.
    while start > 0 and text[start] not in (" ", "\n", "\t"):
        start -= 1
    while end < len(text) and text[end] not in (" ", "\n", "\t"):
        end += 1
    snippet = text[start:end].strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return snippet
