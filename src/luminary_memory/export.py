from __future__ import annotations

import hashlib
import json
import logging
import math
from pathlib import Path
from typing import TYPE_CHECKING

from luminary_memory.scope import memory_matches_scope, normalize_scope

if TYPE_CHECKING:
    from luminary_memory.backends.base import MemoryBackend

logger = logging.getLogger(__name__)

EXPORT_FORMAT = "luminary-memory-export"
EXPORT_VERSION = 1


def _mem_to_dict(m) -> dict:
    try:
        importance = float(m.importance)
    except (TypeError, ValueError):
        importance = 0.5
    if not math.isfinite(importance):
        importance = 0.5
    importance = max(0.0, min(1.0, importance))
    return {
        "content": m.content,
        "tags": list(m.tags or []),
        "metadata": dict(m.metadata or {}),
        "source": m.source,
        "importance": importance,
        "ttl_seconds": m.ttl_seconds,
        "created_at": m.created_at,
        "updated_at": m.updated_at,
        "last_accessed_at": m.last_accessed_at,
        "access_count": max(0, int(m.access_count or 0)),
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
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
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
    payload = json.loads(p.read_text(encoding="utf-8"))

    # Normalize: versioned wrapper (dict) vs bare list.
    if isinstance(payload, dict):
        if payload.get("format") not in (None, EXPORT_FORMAT):
            raise ValueError(f"unsupported export format: {payload.get('format')!r}")
        version = payload.get("version")
        if version is not None:
            try:
                version = int(version)
            except (TypeError, ValueError) as exc:
                raise ValueError("export version must be an integer") from exc
            if version > EXPORT_VERSION:
                raise ValueError(f"unsupported export version: {version}")
        memories_data = payload.get("memories", [])
    elif isinstance(payload, list):
        memories_data = payload
    else:
        raise TypeError("memory export must be a JSON object or list")
    if not isinstance(memories_data, list):
        raise TypeError("export 'memories' must be a list")

    # Build Memory objects; optionally recompute embeddings when absent.
    from luminary_memory.types import Memory

    def _hash(content: str) -> str:
        normalized = " ".join((content or "").strip().split()).casefold()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def _embedding(value) -> list[float] | None:
        if not isinstance(value, (list, tuple)) or not value:
            return None
        try:
            vector = [float(item) for item in value]
        except (TypeError, ValueError):
            return None
        return vector if all(math.isfinite(item) for item in vector) else None

    memories: list[Memory] = []
    normalized_scope = normalize_scope(scope)
    valid_statuses = {"candidate", "active", "conflicted", "superseded", "expired", "deleted"}
    for d in memories_data:
        if not isinstance(d, dict):
            raise TypeError("each exported memory must be an object")
        if not str(d.get("content") or "").strip():
            raise ValueError("exported memory content cannot be empty")
        emb = d.get("embedding")
        if emb is None and recompute_embeddings and engine is not None:
            try:
                emb = engine.embed(d.get("content") or "")
            except Exception:  # noqa: BLE001
                emb = None
        content = str(d.get("content") or "").strip()
        status = str(d.get("status") or "active").lower()
        if status not in valid_statuses:
            raise ValueError(f"invalid exported memory status: {status!r}")
        try:
            importance = float(d.get("importance") if d.get("importance") is not None else 0.5)
            confidence = float(d.get("confidence") if d.get("confidence") is not None else 1.0)
        except (TypeError, ValueError) as exc:
            raise ValueError("exported importance/confidence must be numeric") from exc
        if not math.isfinite(importance) or not math.isfinite(confidence):
            raise ValueError("exported importance/confidence must be finite")
        importance = max(0.0, min(1.0, importance))
        raw_quote = d.get("evidence_quote")
        quote = str(raw_quote).strip() if raw_quote else content
        if quote and quote not in content:
            quote = content
        raw_tags = d.get("tags")
        tags = [str(tag) for tag in raw_tags] if isinstance(raw_tags, (list, tuple, set)) else []
        raw_metadata = d.get("metadata")
        metadata = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}
        try:
            access_count = max(0, int(d.get("access_count") or 0))
        except (TypeError, ValueError):
            access_count = 0
        raw_ttl = d.get("ttl_seconds")
        if raw_ttl is None or raw_ttl == "":
            ttl_seconds = None
        else:
            try:
                ttl_seconds = max(0, int(raw_ttl))
            except (TypeError, ValueError):
                ttl_seconds = None
        computed_hash = _hash(content)
        supplied_hash = str(d.get("content_hash") or "").strip().lower()
        m = Memory(
            content=content,
            tags=tags,
            metadata=metadata,
            source=d.get("source"),
            importance=importance,
            ttl_seconds=ttl_seconds,
            created_at=str(d.get("created_at") or ""),
            updated_at=str(d.get("updated_at") or ""),
            last_accessed_at=(str(d["last_accessed_at"]) if d.get("last_accessed_at") else None),
            access_count=access_count,
            embedding=_embedding(emb),
            user_id=d.get("user_id"),
            session_id=d.get("session_id"),
            workspace_id=d.get("workspace_id"),
            agent_id=d.get("agent_id"),
            observed_at=(str(d["observed_at"]) if d.get("observed_at") else None),
            valid_from=(str(d["valid_from"]) if d.get("valid_from") else None),
            valid_to=(str(d["valid_to"]) if d.get("valid_to") else None),
            status=status,
            confidence=max(0.0, min(1.0, confidence)),
            evidence_quote=quote,
            source_id=d.get("source_id") or d.get("source"),
            claim_key=d.get("claim_key"),
            supersedes_id=d.get("supersedes_id"),
            # A stale/tampered export hash must not break exact-dedup after
            # import; the content is the source of truth.
            content_hash=computed_hash if supplied_hash != computed_hash else supplied_hash,
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
                existing_contents.add(_hash(c))
    except Exception:  # noqa: BLE001 -- dedup is best-effort
        existing_contents = set()

    deduped: list[Memory] = []
    skipped_dups = 0
    for m in memories:
        key = _hash(m.content)
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
    from luminary_memory.recall.graph import index_memory_entities

    secondary_failures = 0
    for m, mid in zip(deduped, ids):
        m.id = mid
        try:
            backend.record_episode(
                f"memory:{mid}",
                str(m.metadata.get("raw_text") or m.content),
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
                if not claim_quote or (
                    claim_quote not in m.content
                    and claim_quote not in str(m.evidence_quote or "")
                ):
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
            secondary_failures += 1
            m.needs_reindex = True
            try:
                backend.update(m)
            except Exception:
                logger.debug("could not mark imported memory %s for reindex", mid, exc_info=True)
            logger.warning("import index/evidence rebuild incomplete for memory %s", mid, exc_info=True)
    result: dict = {"imported": len(deduped)}
    if skipped_dups:
        result["skipped_duplicates"] = skipped_dups
    if secondary_failures:
        result["needs_reindex"] = secondary_failures
    return result
