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


def _norm(content: str) -> str:
    return " ".join((content or "").strip().split()).casefold()


def _hash(content: str) -> str:
    return hashlib.sha256(_norm(content).encode("utf-8")).hexdigest()


def _ownership_key(memory) -> tuple:
    """Full ownership tuple plus content hash.

    Deduplication must key on ownership, not content alone: two tenants can
    legitimately hold the same text, and collapsing them would silently lose
    one tenant's memory. This mirrors the active-row unique index.
    """
    return (
        str(getattr(memory, "user_id", None) or ""),
        str(getattr(memory, "workspace_id", None) or ""),
        str(getattr(memory, "agent_id", None) or ""),
        str(getattr(memory, "session_id", None) or ""),
        _hash(getattr(memory, "content", "") or ""),
    )


def _mem_to_dict(m) -> dict:
    try:
        importance = float(m.importance)
    except (TypeError, ValueError):
        importance = 0.5
    if not math.isfinite(importance):
        importance = 0.5
    importance = max(0.0, min(1.0, importance))
    return {
        # The source id is exported so supersession lineage can be remapped to
        # destination ids instead of being copied verbatim.
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


def _claims_for(backend: MemoryBackend, memory_id: int) -> list[dict]:
    """Read structured claims for one memory so their lifecycle round-trips."""
    conn = getattr(backend, "conn", None)
    if conn is None or memory_id is None:
        return []
    try:
        rows = conn.execute(
            "SELECT subject, predicate, object, polarity, status, confidence, "
            "evidence_quote, observed_at, valid_from, valid_to "
            "FROM claims WHERE memory_id = ? ORDER BY id",
            (memory_id,),
        ).fetchall()
    except Exception:  # noqa: BLE001 -- claim export is best-effort
        return []
    return [dict(row) for row in rows]


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
            {
                **{**_mem_to_dict(m), **({} if include_embeddings else {"embedding": None})},
                # Carry the claim ledger so an inactive parent cannot be
                # restored with active claims.
                "claims": _claims_for(backend, m.id),
            }
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

    from luminary_memory.types import Memory

    def _embedding(value) -> list[float] | None:
        if not isinstance(value, (list, tuple)) or not value:
            return None
        try:
            vector = [float(item) for item in value]
        except (TypeError, ValueError):
            return None
        return vector if all(math.isfinite(item) for item in vector) else None

    normalized_scope = normalize_scope(scope)
    valid_statuses = {"candidate", "active", "conflicted", "superseded", "expired", "deleted"}
    import_timestamp = datetime.now(UTC).isoformat()

    # ---- pass 1: build records, capturing the source id and lineage edges ----
    records: list[dict] = []
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
        created_at = str(d.get("created_at") or import_timestamp)
        updated_at = str(d.get("updated_at") or created_at)
        raw_claims = d.get("claims")
        claims = [dict(c) for c in raw_claims if isinstance(c, dict)] if isinstance(raw_claims, list) else []
        if not claims:
            # Older exports kept claims inside metadata.
            claims = [dict(c) for c in metadata.get("claims", []) if isinstance(c, dict)]
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
            supersedes_id=None,  # resolved in pass 2
            # A stale/tampered export hash must not break exact-dedup after
            # import; the content is the source of truth.
            content_hash=computed_hash if supplied_hash != computed_hash else supplied_hash,
            needs_reindex=bool(d.get("needs_reindex", False)),
        )
        if normalized_scope:
            # A scoped import cannot silently create global rows. Explicit row
            # ownership wins only when it matches the target scope.
            mismatched = False
            for field, value in normalized_scope.items():
                existing = getattr(m, field, None)
                if existing is not None and str(existing) != value:
                    mismatched = True
                    break
                setattr(m, field, value)
            if mismatched:
                continue
        records.append(
            {
                "memory": m,
                "source_id": d.get("id") if isinstance(d.get("id"), int) else None,
                "parent_source_id": (
                    d.get("supersedes_id") if isinstance(d.get("supersedes_id"), int) else None
                ),
                "claims": claims,
            }
        )

    if not records:
        return {"imported": 0}

    # ---- pass 2: resolve lineage and ownership-aware deduplication ----
    # Existing rows are keyed by ownership tuple + content hash, so a restore
    # never mistakes another tenant's row for a copy of this one.
    existing_by_key: dict[tuple, int] = {}
    try:
        for existing in backend.all():
            if str(getattr(existing, "status", "active") or "active") != "active":
                continue
            existing_by_key.setdefault(_ownership_key(existing), int(existing.id))
    except Exception:  # noqa: BLE001 -- dedup is best-effort
        existing_by_key = {}

    id_map: dict[int, int] = {}          # source id -> destination id
    planned: list[dict] = []             # records that will actually be written
    skipped_dups = 0

    for rec in records:
        m = rec["memory"]
        key = _ownership_key(m)
        if key in existing_by_key:
            dest_id = existing_by_key[key]
            if rec["source_id"] is not None:
                id_map[rec["source_id"]] = dest_id
            skipped_dups += 1
            continue
        planned.append(rec)

    planned_source_ids = {
        rec["source_id"] for rec in planned if rec["source_id"] is not None
    }
    for rec in planned:
        m = rec["memory"]
        parent_source_id = rec["parent_source_id"]
        if parent_source_id is None:
            m.supersedes_id = None
            continue
        # The parent must resolve to a row we are importing or one that
        # already exists in the destination *with the same ownership*. A
        # dangling or cross-scope ancestor is refused rather than silently
        # repointed at an unrelated record.
        if parent_source_id in id_map:
            m.supersedes_id = id_map[parent_source_id]
            continue
        source_parent = next(
            (r for r in records if r["source_id"] == parent_source_id), None
        )
        if source_parent is None:
            raise ValueError(
                f"unresolved supersedes_id {parent_source_id}: parent is not in the export"
            )
        parent_memory = source_parent["memory"]
        parent_key = _ownership_key(parent_memory)
        if parent_key in existing_by_key:
            m.supersedes_id = existing_by_key[parent_key]
            continue
        if _ownership_key(m) == parent_key:
            raise ValueError(
                "supersedes_id would collapse parent and child into one row"
            )
        # A lineage edge only exists inside one ownership scope; an ancestor
        # owned by another tenant is a cross-scope reference, not a parent.
        if parent_key[:4] != _ownership_key(m)[:4]:
            raise ValueError(
                f"unresolved supersedes_id {parent_source_id}: parent belongs to another scope"
            )
        if parent_source_id in planned_source_ids:
            # The parent is imported in this same pass and does not have a
            # destination id yet; the post-write remap below fills it in.
            m.supersedes_id = None
            continue
        raise ValueError(
            f"unresolved supersedes_id {parent_source_id}: parent is not importable in this scope"
        )

    # A parent that was skipped as a duplicate still needs its destination id
    # recorded so children resolve to it (handled above), and no child may
    # point at itself.
    for rec in planned:
        m = rec["memory"]
        if m.supersedes_id is not None and m.supersedes_id in {id(x["memory"]) for x in []}:
            raise ValueError("supersedes_id must reference a different row")

    # ---- pass 3: write, then remap ids for children of freshly written rows --
    add_many_with_status = getattr(backend, "add_many_with_status", None)
    to_write = [rec["memory"] for rec in planned]
    if callable(add_many_with_status):
        added = add_many_with_status(to_write)
    else:
        add_many = getattr(backend, "add_many", None)
        if callable(add_many):
            added = [(mid, True) for mid in add_many(to_write)]
        else:
            added = [(backend.add(m), True) for m in to_write]

    from luminary_memory.recall.graph import index_memory_entities

    secondary_failures = 0
    imported_count = 0
    for rec, (mid, inserted) in zip(planned, added):
        m = rec["memory"]
        m.id = mid
        if rec["source_id"] is not None:
            id_map[rec["source_id"]] = mid
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
            for claim in rec["claims"]:
                claim_row = dict(claim)
                claim_quote = str(claim_row.get("evidence_quote") or "").strip()
                if not claim_quote or (
                    claim_quote not in m.content
                    and claim_quote not in str(m.evidence_quote or "")
                ):
                    continue
                claim_row["source_episode_id"] = f"memory:{mid}"
                # Preserve the claim lifecycle: an inactive parent must not
                # come back with active claims.
                claim_row.setdefault("status", m.status)
                if claim_row.get("valid_to") is None:
                    claim_row["valid_to"] = m.valid_to
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

    # Children whose parent was written in this same pass were planned with a
    # placeholder; rewrite them now that destination ids exist.
    for rec, (mid, inserted) in zip(planned, added):
        m = rec["memory"]
        parent_source_id = rec["parent_source_id"]
        if not inserted or parent_source_id is None:
            continue
        resolved = id_map.get(parent_source_id)
        if resolved is None or resolved == mid:
            continue
        if m.supersedes_id != resolved:
            m.supersedes_id = resolved
            try:
                backend.update(m)
            except Exception:  # noqa: BLE001
                logger.warning("could not record lineage for imported memory %s", mid, exc_info=True)

    result: dict = {"imported": imported_count}
    if skipped_dups:
        result["skipped_duplicates"] = skipped_dups
    if secondary_failures:
        result["needs_reindex"] = secondary_failures
    return result
