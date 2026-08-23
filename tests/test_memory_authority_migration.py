"""Regression tests for provenance/lifecycle authority repair."""

import json
import sqlite3

from luminary_memory.backends.sqlite import SQLiteBackend
from luminary_memory.types import Memory
from scripts.repair_memory_authority import apply_repairs, find_repairs


def test_authority_repair_uses_provenance_not_memory_language(tmp_path):
    db_path = tmp_path / "memory.db"
    backend = SQLiteBackend(str(db_path))
    backend.add(
        Memory(
            content="Historical provider decision",
            source="import",
            tags=["core", "mem0-import", "mem0:memory"],
        )
    )
    backend.add(
        Memory(
            content="A sentence in any language\nwith a second line",
            source="hermes",
            tags=["session:s1", "platform:test", "agent:default"],
            metadata={"session_id": "s1", "platform": "test", "agent_identity": "default"},
            session_id="s1",
        )
    )
    backend.add(
        Memory(
            content="Curated durable summary",
            source="hermes",
            tags=["session:s1", "platform:test", "agent:default"],
            metadata={"session_id": "s1", "summary": "Curated durable summary"},
            session_id="s1",
        )
    )
    backend.close()

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    repairs = find_repairs(conn)
    assert [item["action"] for item in repairs] == [
        "archive_historical_authority_snapshot",
        "archive_uncurated_episode",
    ]
    apply_repairs(conn, repairs, "2026-08-23T00:00:00+00:00")

    rows = conn.execute(
        "SELECT id, status, tags, metadata FROM memories ORDER BY id"
    ).fetchall()
    assert [row["status"] for row in rows] == ["archived", "archived", "active"]
    assert "core" not in json.loads(rows[0]["tags"])
    assert json.loads(rows[0]["metadata"])["authority_repair"] == "archive_historical_authority_snapshot"
    assert json.loads(rows[1]["metadata"])["authority_repair"] == "archive_uncurated_episode"
    assert conn.execute("SELECT COUNT(*) FROM memory_events").fetchone()[0] == 2
    conn.close()
