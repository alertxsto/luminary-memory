from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from luminary_memory.backends.base import MemoryBackend

EXPORT_FORMAT = "luminary-memory-export"
EXPORT_VERSION = 1


def _mem_to_dict(m) -> dict:
    return {
        "content": m.content,
        "tags": list(m.tags or []),
        "metadata": dict(m.metadata or {}),
        "source": m.source,
        "importance": float(m.importance),
        "ttl_seconds": m.ttl_seconds,
        "created_at": m.created_at,
        "updated_at": m.updated_at,
        "last_accessed_at": m.last_accessed_at,
        "access_count": int(m.access_count),
        "embedding": list(m.embedding) if m.embedding is not None else None,
    }


def export_memories(
    backend: MemoryBackend,
    path: str | Path,
    include_embeddings: bool = True,
) -> dict:
    memories = backend.all()
    payload = {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "memories": [
            {**_mem_to_dict(m), **({} if include_embeddings else {"embedding": None})}
            for m in memories
        ],
    }
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2))
    return {"count": len(memories), "path": str(p)}


def import_memories(
    backend: MemoryBackend,
    path: str | Path,
    *,
    engine=None,
    recompute_embeddings: bool = True,
) -> dict:
    p = Path(path)
    payload = json.loads(p.read_text())

    # Normalize: versioned wrapper (dict) vs bare list.
    if isinstance(payload, dict):
        memories_data = payload.get("memories") or []
    elif isinstance(payload, list):
        memories_data = payload
    else:
        memories_data = []

    # Build Memory objects; optionally recompute embeddings when absent.
    from luminary_memory.types import Memory

    memories: list[Memory] = []
    for d in memories_data:
        emb = d.get("embedding")
        if emb is None and recompute_embeddings and engine is not None:
            try:
                emb = engine.embed(d.get("content") or "")
            except Exception:  # noqa: BLE001
                emb = None
        m = Memory(
            content=d.get("content") or "",
            tags=list(d.get("tags") or []),
            metadata=dict(d.get("metadata") or {}),
            source=d.get("source"),
            importance=float(d.get("importance") if d.get("importance") is not None else 0.5),
            ttl_seconds=d.get("ttl_seconds"),
            created_at=d.get("created_at") or "",
            updated_at=d.get("updated_at") or "",
            last_accessed_at=d.get("last_accessed_at"),
            access_count=int(d.get("access_count") or 0),
            embedding=list(emb) if isinstance(emb, (list, tuple)) else None,
        )
        memories.append(m)

    if not memories:
        return {"imported": 0}

    # Dedup guard: skip memories whose content already exists in the store.
    # Prevents bulk imports (e.g. MEMORY.md/USER.md merges) from creating
    # duplicate entries.
    existing_contents: set[str] = set()
    try:
        for existing in backend.all():
            c = getattr(existing, "content", None)
            if c:
                existing_contents.add(c.strip().lower())
    except Exception:  # noqa: BLE001 -- dedup is best-effort
        existing_contents = set()

    deduped: list[Memory] = []
    skipped_dups = 0
    for m in memories:
        key = (m.content or "").strip().lower()
        if key and key in existing_contents:
            skipped_dups += 1
            continue
        existing_contents.add(key)
        deduped.append(m)

    if not deduped:
        return {"imported": 0, "skipped_duplicates": skipped_dups}

    # Prefer batch path when available.
    add_many = getattr(backend, "add_many", None)
    if callable(add_many):
        ids = add_many(deduped)
    else:
        ids = [backend.add(m) for m in deduped]
    _ = ids
    result: dict = {"imported": len(deduped)}
    if skipped_dups:
        result["skipped_duplicates"] = skipped_dups
    return result
