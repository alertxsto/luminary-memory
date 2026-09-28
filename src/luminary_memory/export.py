from __future__ import annotations

import hashlib
import json
import logging
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from luminary_memory.scope import SCOPE_FIELDS, memory_matches_scope, normalize_scope

if TYPE_CHECKING:
    from luminary_memory.backends.base import MemoryBackend

logger = logging.getLogger(__name__)

EXPORT_FORMAT = "luminary-memory-export"
EXPORT_VERSION = 2


def _mem_to_dict(m) -> dict:
    try:
        importance = float(m.importance)
    except (TypeError, ValueError):
        importance = 0.5
    if not math.isfinite(importance):
        importance = 0.5
    importance = max(0.0, min(1.0, importance))
    return {
        "id": m.id,
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


    def _owner(m: Memory) -> tuple[str, ...]:
        return tuple(
            str(value) if value is not None else ""
            for field in SCOPE_FIELDS
            for value in (getattr(m, field, None),)
        )
        return tuple(str(getattr(m, field) or "") for field in SCOPE_FIELDS)


    def _hash(content: str) -> str:
        normalized = " ".join((content or "").strip().split()).casefold()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def _embedding(value) -> list[float] | None:
        if not isinstance(value, (list, tuple)) or not value:
            return None
        try:
            vector = [float(item) for item in value]
        except (TypeError, ValueError):
    memories: list[Memory] = []
    source_ids: list[int | None] = []
    memories: list[Memory] = []
    source_ids: list[int | None] = []

    memories: list[Memory] = []
    normalized_scope = normalize_scope(scope)
    valid_statuses = {"candidate", "active", "conflicted", "superseded", "expired", "deleted"}
    import_timestamp = datetime.now(UTC).isoformat()
    for d in memories_data:
        if not isinstance(d, dict):
            raise TypeError("each exported memory must be an object")
        source_id = d.get("id")
        if source_id is not None and (
            isinstance(source_id, bool) or not isinstance(source_id, int) or source_id <= 0
        ):
            raise ValueError("exported memory id must be a positive integer")
        parent_id = d.get("supersedes_id")
        if parent_id is not None and (
            isinstance(parent_id, bool) or not isinstance(parent_id, int) or parent_id <= 0
        ):
            raise ValueError("exported supersedes_id must be a positive integer")
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
        created_at = str(d.get("created_at") or import_timestamp)
        updated_at = str(d.get("updated_at") or created_at)
        m = Memory(
            content=content,
            tags=tags,
            metadata=metadata,
            source=d.get("source"),
            importance=importance,
            ttl_seconds=ttl_seconds,
            created_at=created_at,
            updated_at=updated_at,
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
        source_ids.append(source_id)
                continue
        memories.append(m)

    if not memories:
    # Resolve source lineage only against rows in this export. An old ID is
    # never a destination ID, even when a same-numbered destination row exists.
    source_rows: dict[int, Memory] = {}
    for m, old_id in zip(memories, source_ids):
        if old_id is not None:
            if old_id in source_rows:
                raise ValueError(f"duplicate exported memory id: {old_id}")
            source_rows[old_id] = m
    for m in memories:
        if m.supersedes_id is None:
            continue
        parent = source_rows.get(m.supersedes_id)
        if parent is None:
            raise ValueError(f"unresolved supersedes_id: {m.supersedes_id}")
        if parent is m or _owner(parent) != _owner(m):
            raise ValueError(f"invalid supersedes_id ownership: {m.supersedes_id}")

    # COALESCE(owner, '') and the normalized content hash are exactly the
    # columns in the active-row unique index. Inactive history remains distinct.
    existing_contents: dict[tuple[tuple[str, ...], str], Memory] = {}
    for existing in backend.all():
        if str(getattr(existing, "status", "active") or "active") == "active":
            existing_contents[(_owner(existing), _hash(existing.content))] = existing

    deduped: list[Memory] = []
    targets: dict[int, Memory] = {}
    canonical: dict[int, Memory] = {}
    canonical: dict[int, Memory] = {}
    skipped_dups = 0
    parents: list[tuple[Memory, int]] = []
    for m, old_id in zip(memories, source_ids):
        if m.supersedes_id is not None:
            parents.append((m, m.supersedes_id))
            # Insert without the source ID; restore mapped references only
            # after all destination IDs (including forward refs) are known.
            m.supersedes_id = None
        key = (_owner(m), m.content_hash)
        canonical[id(m)] = match if match is not None else m
        match = existing_contents.get(key) if m.status == "active" else None
        canonical[id(m)] = match if match is not None else m
        if match is not None:
            skipped_dups += 1
            if old_id is not None:
                targets[old_id] = match
            continue
        if m.status == "active":
            existing_contents[key] = m
        deduped.append(m)
    for m, old_parent_id in parents:
        if canonical[id(m)] is canonical[id(source_rows[old_parent_id])]:
            raise ValueError(f"supersedes_id {old_parent_id} resolves to the child itself")
        if old_id is not None:
            targets[old_id] = m

    # Prefer the status-aware batch path when available. A DB-level race
    # winner also becomes a valid source-ID target, without duplicated ledgers.
    add_many_with_status = getattr(backend, "add_many_with_status", None)
    if callable(add_many_with_status):
        added = add_many_with_status(deduped)
    else:
        add_many = getattr(backend, "add_many", None)
        if callable(add_many):
            added = [(mid, True) for mid in add_many(deduped)]
        else:
            added = [(backend.add(m), True) for m in deduped]
    if len(added) != len(deduped):
        raise RuntimeError("backend returned incomplete import IDs; lineage was not restored")
    for m, (mid, inserted) in zip(deduped, added):
        m.id = mid
        if not inserted:
    for m, (mid, inserted) in zip(deduped, added):
            winner = backend.get(mid)
            if winner is None or _owner(winner) != _owner(m) or _hash(winner.content) != m.content_hash:
                raise RuntimeError(f"backend returned an invalid duplicate import ID: {mid}")
            canonical[id(m)] = winner
            for old_id, target in targets.items():
                if target is m:
                    targets[old_id] = winner
            # The batch result represents an existing row, not this new
            # object; never rewrite it while restoring source lineage.
            canonical[id(m)] = backend.get(mid)
            for old_id, target in targets.items():
                if target is m:
                    targets[old_id] = canonical[id(m)]
    for m, old_parent_id in parents:
        if canonical[id(m)] is parent or (canonical[id(m)] is m and m.id == parent.id):
            raise ValueError(f"supersedes_id {old_parent_id} resolves to the child itself")
        target = canonical[id(m)]
        if parent is None or parent.id is None:
            raise ValueError(f"unresolved destination supersedes_id: {old_parent_id}")
        if _owner(parent) != _owner(m):
            raise ValueError(f"destination supersedes_id ownership mismatch: {old_parent_id}")
        target = canonical[id(m)]
        if target.id is None:
            raise ValueError("unresolved destination ID for imported lineage")
        if target is not m:
            if target.supersedes_id != parent.id:
                raise ValueError("existing duplicate has conflicting supersedes lineage")
            continue
        m.supersedes_id = parent.id
        backend.update(m)

    if not deduped:
        return {"imported": 0, "skipped_duplicates": skipped_dups}
    from luminary_memory.recall.graph import index_memory_entities
            added = [(backend.add(m), True) for m in deduped]

    secondary_failures = 0
    imported_count = 0
    for m, (mid, inserted) in zip(deduped, added):
        m.id = mid
        if not inserted:
            skipped_dups += 1
            continue
        imported_count += 1
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
                claim_row["status"] = (
                    m.status if m.status != "active" else str(claim_row.get("status") or "active")
                )
                claim_row["valid_from"] = claim_row.get("valid_from") or m.valid_from
                claim_row["valid_to"] = claim_row.get("valid_to") or m.valid_to
                claim_row["observed_at"] = claim_row.get("observed_at") or m.observed_at
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
    result: dict = {"imported": imported_count}
    if skipped_dups:
        result["skipped_duplicates"] = skipped_dups
    if secondary_failures:
        result["needs_reindex"] = secondary_failures
    return result
