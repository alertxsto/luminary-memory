from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from luminary_memory.scope import memory_matches_scope, normalize_scope

if TYPE_CHECKING:
    from luminary_memory.backends.base import MemoryBackend

logger = logging.getLogger(__name__)

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
        "user_id": m.user_id,
        "session_id": m.session_id,
        "workspace_id": m.workspace_id,
        "agent_id": m.agent_id,
        "observed_at": m.observed_at,
        "valid_from": m.valid_from,
        "valid_to": m.valid_to,
        "status": m.status,
        "confidence": float(m.confidence),
        "evidence_quote": m.evidence_quote,
        "source_id": m.source_id,
        "claim_key": m.claim_key,
        "supersedes_id": m.supersedes_id,
        "content_hash": m.content_hash,
        "needs_reindex": bool(m.needs_reindex),
    }


def export_memories(
    backend: MemoryBackend,
    path: str | Path,
    include_embeddings: bool = True,
    scope: dict | None = None,
    include_global: bool = True,
) -> dict:
    normalized_scope = normalize_scope(scope)
    memories = [
        m for m in backend.all()
        # Backups must retain conflicted/superseded history as well as active
        # rows; recall itself still filters to current active claims.
        if memory_matches_scope(
            m,
            normalized_scope,
            include_global=include_global,
            active_only=False,
        )
    ]
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
    scope: dict | None = None,
    include_global: bool = True,
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

    def _hash(content: str) -> str:
        normalized = " ".join((content or "").strip().split()).casefold()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    memories: list[Memory] = []
    normalized_scope = normalize_scope(scope)
    for d in memories_data:
        emb = d.get("embedding")
        if emb is None and recompute_embeddings and engine is not None:
            try:
                emb = engine.embed(d.get("content") or "")
            except Exception:  # noqa: BLE001
                emb = None
        content = str(d.get("content") or "")
        raw_quote = d.get("evidence_quote")
        quote = str(raw_quote).strip() if raw_quote else content
        if quote and quote not in content:
            quote = content
        m = Memory(
            content=content,
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
            user_id=d.get("user_id"),
            session_id=d.get("session_id"),
            workspace_id=d.get("workspace_id"),
            agent_id=d.get("agent_id"),
            observed_at=d.get("observed_at"),
            valid_from=d.get("valid_from"),
            valid_to=d.get("valid_to"),
            status=str(d.get("status") or "active"),
            confidence=float(d.get("confidence") if d.get("confidence") is not None else 1.0),
            evidence_quote=quote,
            source_id=d.get("source_id") or d.get("source"),
            claim_key=d.get("claim_key"),
            supersedes_id=d.get("supersedes_id"),
            content_hash=d.get("content_hash") or _hash(d.get("content") or ""),
            needs_reindex=bool(d.get("needs_reindex", False)),
        )
        if normalized_scope:
            # A scoped import cannot silently create global rows.  Explicit
            # row ownership wins only when it matches the target scope.
            mismatched = False
            for field, value in normalized_scope.items():
                existing = getattr(m, field, None)
                if existing is not None and str(existing) != value:
                    mismatched = True
                    break
                setattr(m, field, value)
            if mismatched:
                continue
        memories.append(m)

    if not memories:
        return {"imported": 0}

    # Dedup guard: skip memories whose content already exists in the store.
    # Prevents bulk imports (e.g. MEMORY.md/USER.md merges) from creating
    # duplicate entries.
    existing_contents: set[str] = set()
    try:
        for existing in backend.all():
            if normalized_scope and not memory_matches_scope(
                existing,
                normalized_scope,
                include_global=include_global,
            ):
                continue
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
    try:
        from luminary_memory.recall.graph import index_memory_entities

        for m, mid in zip(deduped, ids):
            m.id = mid
            backend.record_episode(
                f"memory:{mid}",
                str(m.metadata.get("evidence_quote") or m.content),
                source=m.source,
                metadata=m.metadata,
                user_id=m.user_id,
                session_id=m.session_id,
                workspace_id=m.workspace_id,
                agent_id=m.agent_id,
                observed_at=m.observed_at,
            )
            for claim in list(m.metadata.get("claims") or []):
                if not isinstance(claim, dict):
                    continue
                claim_row = dict(claim)
                claim_quote = str(claim_row.get("evidence_quote") or "").strip()
                if not claim_quote or claim_quote not in m.content:
                    continue
                claim_row["source_episode_id"] = f"memory:{mid}"
                backend.add_claim(
                    mid,
                    claim_row,
                    user_id=m.user_id,
                    session_id=m.session_id,
                    workspace_id=m.workspace_id,
                    agent_id=m.agent_id,
                )
            index_memory_entities(backend, m)
            backend.record_event("import", mid, after=_mem_to_dict(m), actor="import")
            if m.evidence_quote:
                backend.add_evidence(
                    mid,
                    m.evidence_quote,
                    source_id=m.source_id,
                    observed_at=m.observed_at,
                    extractor="import",
                    confidence=m.confidence,
                )
    except Exception:
        logger.warning("import index/evidence rebuild was incomplete", exc_info=True)
    result: dict = {"imported": len(deduped)}
    if skipped_dups:
        result["skipped_duplicates"] = skipped_dups
    return result
