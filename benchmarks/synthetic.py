from __future__ import annotations

import random

_TEMPLATES = [
    "The project uses {tech} for {purpose}.",
    "Decision: we will {decision} for the next sprint.",
    "User preference: {pref}.",
    "Fix: {fix} resolves {issue}.",
    "Note: {note}.",
]

_TECH = ["postgres", "sqlite", "pgvector", "fastembed", "typer", "rich"]
_PURPOSE = ["vector search", "keyword indexing", "CLI output", "embedding"]
_DECISION = ["migrate to pgvector", "keep sqlite default", "enable HNSW"]
_PREF = ["dark mode", "vim keybindings", "compact output"]
_FIX = ["sanitize FTS query", "bump updated_at", "clamp limit"]
_ISSUE = ["syntax injection", "stale timestamp", "limit 0 semantics"]
_NOTE = ["deploy target is staging", "recall budget is 4096", "graph uses co-occurrence"]


def generate_memories(n: int = 500, seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    out: list[dict] = []
    for i in range(n):
        t = rng.choice(_TEMPLATES)
        content = t.format(
            tech=rng.choice(_TECH),
            purpose=rng.choice(_PURPOSE),
            decision=rng.choice(_DECISION),
            pref=rng.choice(_PREF),
            fix=rng.choice(_FIX),
            issue=rng.choice(_ISSUE),
            note=rng.choice(_NOTE),
        )
        # Ensure some overlap for relevance labels.
        tags = rng.sample(["infra", "product", "memory", "cli"], k=rng.randint(0, 2))
        out.append({"content": f"{content} id:{i}", "tags": tags})
    return out


def generate_queries(n: int = 5, seed: int = 99) -> list[dict]:
    rng = random.Random(seed)
    queries = [
        ("postgres vector search", [0]),
        ("deploy target staging", [1]),
        ("sanitize FTS", [2]),
        ("user preference dark mode", [3]),
        ("graph co-occurrence", [4]),
    ]
    # Return first n with relevance hints (indices into synthetic set are illustrative).
    return [{"query": q, "relevant_idx": rel} for q, rel in queries[:n]]
