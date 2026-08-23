"""Independent, versioned gold-set loader for accuracy evaluation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def load_gold(path: str | Path) -> tuple[dict[str, Any], list[dict], list[dict]]:
    """Load ``meta``, memory fixtures, and query cases from JSONL.

    Relevance labels live in the fixture, never in the retriever's output.
    That makes the benchmark useful for detecting false positives and
    abstention failures instead of merely measuring self-consistency.
    """
    source = Path(path).read_bytes()
    meta: dict[str, Any] = {}
    memories: list[dict] = []
    cases: list[dict] = []
    for raw_line in source.decode("utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        item = json.loads(line)
        record_type = item.get("type")
        if record_type == "meta":
            meta = item
        elif record_type == "memory":
            memories.append(item)
        elif record_type == "case":
            cases.append(item)
        else:
            raise ValueError(f"unknown gold record type: {record_type!r}")
    if meta.get("format") != "luminary-memory-gold":
        raise ValueError("unsupported gold-set format")
    if not memories or not cases:
        raise ValueError("gold set must contain at least one memory and one case")
    meta = dict(meta)
    meta["sha256"] = hashlib.sha256(source).hexdigest()
    return meta, memories, cases
