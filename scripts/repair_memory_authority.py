"""Repair source-authority collisions in a Luminary SQLite store.

This migration deliberately reasons from provenance and lifecycle metadata,
not from the language or wording of a memory. It performs two safe repairs:

* historical imported memory-system decisions are archived, because they are
  snapshots of an old authority decision rather than current user facts;
* uncurated Hermes turn episodes are archived, because an episode must not be
  treated as a durable semantic memory.

No rows are deleted. ``--apply`` creates a SQLite-consistent backup before the
transaction. Without ``--apply`` the command is a read-only dry run.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _json(value: str | None, default: Any) -> Any:
    try:
        return json.loads(value or "")
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _tags(value: str | None) -> list[str]:
    parsed = _json(value, [])
    if not isinstance(parsed, list):
        return []
    return [str(tag) for tag in parsed]


def _metadata(value: str | None) -> dict[str, Any]:
    parsed = _json(value, {})
    return parsed if isinstance(parsed, dict) else {}


def _is_uncurated_episode(row: sqlite3.Row) -> bool:
    """Detect a retained episode without depending on its natural language."""

    tags = set(_tags(row["tags"]))
    metadata = _metadata(row["metadata"])
    return (
        row["status"] == "active"
        and row["source"] == "hermes"
        and bool(row["session_id"])
        and any(tag.startswith("session:") for tag in tags)
        and "summary" not in metadata
        and len(str(row["content"] or "").splitlines()) >= 2
    )


def find_repairs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return a deterministic, explainable repair plan without mutating data."""

    rows = conn.execute(
        "SELECT id, content, metadata, source, tags, status, session_id, valid_to "
        "FROM memories WHERE status = 'active' ORDER BY id"
    ).fetchall()
    repairs: list[dict[str, Any]] = []
    for row in rows:
        tags = _tags(row["tags"])

        # This tag is a provenance category from the imported snapshot. It is
        # intentionally treated as historical architecture state, not as an
        # active fact about the current provider.
        if "mem0:memory" in tags:
            repairs.append(
                {
                    "id": int(row["id"]),
                    "action": "archive_historical_authority_snapshot",
                    "remove_core": "core" in tags,
                }
            )
            continue

        if _is_uncurated_episode(row):
            repairs.append(
                {
                    "id": int(row["id"]),
                    "action": "archive_uncurated_episode",
                    "remove_core": "core" in tags,
                }
            )

    return repairs


def backup_database(db_path: Path, backup_path: Path) -> None:
    """Create a consistent SQLite backup, including WAL state."""

    backup_path.parent.mkdir(parents=True, exist_ok=True)
    if backup_path.exists():
        raise FileExistsError(f"backup already exists: {backup_path}")
    source = sqlite3.connect(str(db_path))
    target = sqlite3.connect(str(backup_path))
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def apply_repairs(conn: sqlite3.Connection, repairs: list[dict[str, Any]], now: str) -> None:
    """Apply the planned lifecycle transitions and append an audit event."""

    conn.execute("BEGIN IMMEDIATE")
    try:
        for repair in repairs:
            memory_id = int(repair["id"])
            row = conn.execute(
                "SELECT metadata, tags, status, valid_to FROM memories WHERE id = ?",
                (memory_id,),
            ).fetchone()
            if row is None or row["status"] != "active":
                continue

            tags = _tags(row["tags"])
            metadata = _metadata(row["metadata"])
            if repair["remove_core"]:
                tags = [tag for tag in tags if tag != "core"]
            metadata["authority_repair"] = repair["action"]
            metadata["authority_repair_at"] = now

            before = {
                "status": row["status"],
                "valid_to": row["valid_to"],
                "tags": _tags(row["tags"]),
            }
            after = {
                "status": "archived",
                "valid_to": row["valid_to"] or now,
                "tags": tags,
            }
            conn.execute(
                "UPDATE memories SET tags = ?, metadata = ?, status = 'archived', "
                "valid_to = COALESCE(valid_to, ?), updated_at = ? WHERE id = ?",
                (json.dumps(tags, ensure_ascii=False), json.dumps(metadata, ensure_ascii=False), now, now, memory_id),
            )
            conn.execute(
                "INSERT INTO memory_events(memory_id, event_type, before_json, after_json, actor) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    memory_id,
                    repair["action"],
                    json.dumps(before, ensure_ascii=False),
                    json.dumps(after, ensure_ascii=False),
                    "repair_memory_authority",
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _default_backup_path(db_path: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return db_path.with_name(f"{db_path.name}.before-authority-repair-{stamp}.bak")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", required=True, type=Path)
    parser.add_argument("--apply", action="store_true", help="apply the repair after making a backup")
    parser.add_argument("--backup-path", type=Path)
    args = parser.parse_args(argv)

    db_path = args.db_path.expanduser().resolve()
    if not db_path.is_file():
        parser.error(f"database does not exist: {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        repairs = find_repairs(conn)
        result: dict[str, Any] = {
            "database": str(db_path),
            "mode": "apply" if args.apply else "dry-run",
            "repair_count": len(repairs),
            "repairs": repairs,
        }
        if args.apply and repairs:
            backup_path = (args.backup_path or _default_backup_path(db_path)).expanduser().resolve()
            backup_database(db_path, backup_path)
            apply_repairs(conn, repairs, _now())
            result["backup"] = str(backup_path)
            result["applied"] = True
        else:
            result["applied"] = False
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
