from __future__ import annotations

import sqlite3

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    source TEXT,
    tags TEXT NOT NULL DEFAULT '[]',
    importance REAL NOT NULL DEFAULT 0.5,
    ttl_seconds INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_accessed_at TEXT,
    access_count INTEGER NOT NULL DEFAULT 0,
    embedding BLOB,
    user_id TEXT,
    session_id TEXT,
    workspace_id TEXT,
    agent_id TEXT,
    observed_at TEXT,
    valid_from TEXT,
    valid_to TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    confidence REAL NOT NULL DEFAULT 1.0,
    evidence_quote TEXT,
    source_id TEXT,
    claim_key TEXT,
    supersedes_id INTEGER,
    content_hash TEXT,
    needs_reindex INTEGER NOT NULL DEFAULT 0
);
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    content, tags, content='memories', content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, content, tags)
    VALUES (new.id, new.content, new.tags);
END;
CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, tags)
    VALUES ('delete', old.id, old.content, old.tags);
END;
CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, tags)
    VALUES ('delete', old.id, old.content, old.tags);
    INSERT INTO memories_fts(rowid, content, tags)
    VALUES (new.id, new.content, new.tags);
END;
CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL DEFAULT 'generic'
);
CREATE TABLE IF NOT EXISTS relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL REFERENCES entities(id),
    target_id INTEGER NOT NULL REFERENCES entities(id),
    relation_type TEXT NOT NULL DEFAULT 'cooccur',
    weight REAL NOT NULL DEFAULT 1.0,
    memory_id INTEGER REFERENCES memories(id)
);
CREATE INDEX IF NOT EXISTS idx_relations_source ON relations(source_id);
CREATE INDEX IF NOT EXISTS idx_relations_memory ON relations(memory_id);
CREATE INDEX IF NOT EXISTS idx_relations_target ON relations(target_id);
CREATE TABLE IF NOT EXISTS memory_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id INTEGER REFERENCES memories(id) ON DELETE SET NULL,
    quote TEXT NOT NULL,
    source_id TEXT,
    observed_at TEXT,
    extractor TEXT,
    confidence REAL NOT NULL DEFAULT 1.0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_memory_evidence_memory ON memory_evidence(memory_id);

CREATE TABLE IF NOT EXISTS memory_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id INTEGER,
    event_type TEXT NOT NULL,
    before_json TEXT,
    after_json TEXT,
    actor TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_memory_events_memory ON memory_events(memory_id);
CREATE INDEX IF NOT EXISTS idx_memory_events_type ON memory_events(event_type);
CREATE TABLE IF NOT EXISTS episodes (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    source TEXT,
    metadata TEXT NOT NULL DEFAULT '{}',
    user_id TEXT,
    session_id TEXT,
    workspace_id TEXT,
    agent_id TEXT,
    observed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_episodes_scope ON episodes(user_id, workspace_id, agent_id, session_id);
CREATE TABLE IF NOT EXISTS claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id INTEGER REFERENCES memories(id) ON DELETE SET NULL,
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object TEXT NOT NULL,
    polarity TEXT NOT NULL DEFAULT 'positive',
    status TEXT NOT NULL DEFAULT 'active',
    confidence REAL NOT NULL DEFAULT 1.0,
    evidence_quote TEXT,
    source_episode_id TEXT,
    user_id TEXT,
    session_id TEXT,
    workspace_id TEXT,
    agent_id TEXT,
    observed_at TEXT,
    valid_from TEXT,
    valid_to TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_claims_memory ON claims(memory_id);
CREATE INDEX IF NOT EXISTS idx_claims_key ON claims(user_id, workspace_id, subject, predicate, status);
CREATE TABLE IF NOT EXISTS claim_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id INTEGER REFERENCES claims(id) ON DELETE SET NULL,
    quote TEXT NOT NULL,
    source_episode_id TEXT,
    source_offset_start INTEGER,
    source_offset_end INTEGER,
    confidence REAL NOT NULL DEFAULT 1.0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_claim_evidence_claim ON claim_evidence(claim_id);
"""


_MIGRATION_COLUMNS: dict[str, str] = {
    "user_id": "TEXT",
    "session_id": "TEXT",
    "workspace_id": "TEXT",
    "agent_id": "TEXT",
    "observed_at": "TEXT",
    "valid_from": "TEXT",
    "valid_to": "TEXT",
    "status": "TEXT NOT NULL DEFAULT 'active'",
    "confidence": "REAL NOT NULL DEFAULT 1.0",
    "evidence_quote": "TEXT",
    "source_id": "TEXT",
    "claim_key": "TEXT",
    "supersedes_id": "INTEGER",
    "content_hash": "TEXT",
    "needs_reindex": "INTEGER NOT NULL DEFAULT 0",
}


def init_schema(conn: sqlite3.Connection) -> None:
    # A few pre-FTS releases shipped a very small ``memories`` table. Add the
    # columns referenced by the external-content triggers before creating them;
    # ``CREATE TABLE IF NOT EXISTS`` alone cannot evolve an existing table.
    existing_before = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(memories)").fetchall()
    }
    legacy_base_columns: dict[str, str] = {
        "metadata": "TEXT NOT NULL DEFAULT '{}'",
        "source": "TEXT",
        "tags": "TEXT NOT NULL DEFAULT '[]'",
        "importance": "REAL NOT NULL DEFAULT 0.5",
        "ttl_seconds": "INTEGER",
        "created_at": "TEXT NOT NULL DEFAULT ''",
        "updated_at": "TEXT NOT NULL DEFAULT ''",
        "last_accessed_at": "TEXT",
        "access_count": "INTEGER NOT NULL DEFAULT 0",
        "embedding": "BLOB",
    }
    for name, definition in legacy_base_columns.items():
        if existing_before and name not in existing_before:
            conn.execute(f"ALTER TABLE memories ADD COLUMN {name} {definition}")
    # Rebuild the external-content FTS index when upgrading a database created
    # by an older schema that predates the FTS5 table. In that case the virtual
    # table is created empty and the AFTER INSERT/UPDATE/DELETE triggers never
    # fire for rows that already existed, so keyword search would silently
    # return zero hits. Detecting virtual tables in sqlite_master is the cheap,
    # reliable signal (SELECT count(*) on an external-content FTS table counts
    # the content rows, not the index, so it cannot be used). Runs at most once:
    # only the first connection that creates the FTS table performs the rebuild.
    had_fts = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='memories_fts'"
    ).fetchone() is not None
    conn.executescript(SCHEMA_SQL)
    rebuild_fts = not had_fts
    if had_fts:
        # A crash or hand-edited legacy database can leave the derived FTS
        # table/triggers only partially present. Existence of the table name
        # alone is not enough to establish that keyword recall is healthy.
        fts_columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(memories_fts)").fetchall()
        }
        trigger_names = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'memories_%'"
            ).fetchall()
        }
        expected_triggers = {"memories_ai", "memories_au", "memories_ad"}
        if not {"content", "tags"} <= fts_columns or not expected_triggers <= trigger_names:
            conn.execute("DROP TABLE IF EXISTS memories_fts")
            conn.executescript(SCHEMA_SQL)
            rebuild_fts = True
    # ``CREATE TABLE IF NOT EXISTS`` does not evolve a database created by an
    # older release.  Keep migrations deliberately small and idempotent so a
    # provider can open an existing store without a manual migration command.
    existing = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(memories)").fetchall()
    }
    for name, definition in _MIGRATION_COLUMNS.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE memories ADD COLUMN {name} {definition}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_memories_scope "
        "ON memories(user_id, workspace_id, agent_id, session_id)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_memories_claim "
        "ON memories(user_id, workspace_id, claim_key, status)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_memories_hash "
        "ON memories(user_id, workspace_id, content_hash)"
    )
    if rebuild_fts:
        mem_count = conn.execute("SELECT count(*) FROM memories").fetchone()[0]
        if mem_count > 0:
            conn.execute("INSERT INTO memories_fts(memories_fts) VALUES('rebuild')")
    # Backfill a stable content hash for legacy rows without fabricating
    # ownership or evidence.  Do this after an FTS rebuild: the external
    # content triggers fire on UPDATE and older empty FTS indexes otherwise
    # report ``database disk image is malformed`` on some SQLite builds.
    import hashlib

    legacy_rows = conn.execute(
        "SELECT id, content FROM memories WHERE content_hash IS NULL"
    ).fetchall()
    for memory_id, content in legacy_rows:
        normalized = " ".join(str(content or "").strip().split()).casefold()
        content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        conn.execute(
            "UPDATE memories SET content_hash = ? WHERE id = ? AND content_hash IS NULL",
            (content_hash, memory_id),
        )

    # Exact deduplication is a database invariant, not just an API
    # pre-check. Two independent processes can both observe an empty result
    # from ``find_by_hash`` and race into INSERT. Keep the oldest active row,
    # move derived references to it, and retain the event/episode ledgers for
    # auditability before installing the unique constraint.
    duplicate_groups = conn.execute(
        "SELECT COALESCE(user_id, ''), COALESCE(workspace_id, ''), "
        "COALESCE(agent_id, ''), COALESCE(session_id, ''), content_hash, "
        "MIN(id) AS survivor, COUNT(*) AS copies "
        "FROM memories "
        "WHERE COALESCE(status, 'active') = 'active' AND content_hash IS NOT NULL "
        "GROUP BY COALESCE(user_id, ''), COALESCE(workspace_id, ''), "
        "COALESCE(agent_id, ''), COALESCE(session_id, ''), content_hash "
        "HAVING COUNT(*) > 1"
    ).fetchall()
    for user_id, workspace_id, agent_id, session_id, content_hash, survivor, _copies in duplicate_groups:
        duplicate_ids = conn.execute(
            "SELECT id FROM memories WHERE COALESCE(status, 'active') = 'active' "
            "AND content_hash = ? AND COALESCE(user_id, '') = ? "
            "AND COALESCE(workspace_id, '') = ? AND COALESCE(agent_id, '') = ? "
            "AND COALESCE(session_id, '') = ? AND id <> ?",
            (content_hash, user_id, workspace_id, agent_id, session_id, survivor),
        ).fetchall()
        for (duplicate_id,) in duplicate_ids:
            # Keep all durable provenance attached to the surviving memory.
            for table in ("memory_evidence", "claims", "relations"):
                conn.execute(
                    f"UPDATE {table} SET memory_id = ? WHERE memory_id = ?",
                    (survivor, duplicate_id),
                )
            conn.execute(
                "UPDATE memories SET supersedes_id = ? WHERE supersedes_id = ?",
                (survivor, duplicate_id),
            )
            conn.execute("DELETE FROM memories WHERE id = ?", (duplicate_id,))

    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_memories_active_scope_hash "
        "ON memories (COALESCE(user_id, ''), COALESCE(workspace_id, ''), "
        "COALESCE(agent_id, ''), COALESCE(session_id, ''), content_hash) "
        "WHERE COALESCE(status, 'active') = 'active' AND content_hash IS NOT NULL"
    )
    conn.commit()
