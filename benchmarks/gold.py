"""Independent, versioned gold-set loader for accuracy evaluation."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

_TIME_FIELDS = ("observed_at", "valid_from", "valid_to")


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def anchor_time(memories: list[dict]) -> datetime | None:
    """Return the newest timestamp in the fixture.

    Fixtures store absolute dates, but recall scores decay with wall-clock age.
    Rebasing the fixture against this anchor keeps evaluation repeatable on any
    run date without editing the versioned fixture.
    """
    stamps = [
        stamp
        for item in memories
        for stamp in (_parse_timestamp(item.get(field)) for field in _TIME_FIELDS)
        if stamp is not None
    ]
    return max(stamps) if stamps else None


def rebase_timestamps(memories: list[dict], delta: timedelta) -> list[dict]:
    """Shift every fixture timestamp by ``delta``; return new records."""
    rebased: list[dict] = []
    for item in memories:
        record = dict(item)
        for field in _TIME_FIELDS:
            parsed = _parse_timestamp(record.get(field))
            if parsed is not None:
                record[field] = (parsed + delta).isoformat()
        rebased.append(record)
    return rebased


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
