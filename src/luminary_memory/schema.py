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
    embedding BLOB
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
"""

def init_schema(conn: sqlite3.Connection) -> None:
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
    if not had_fts:
        mem_count = conn.execute("SELECT count(*) FROM memories").fetchone()[0]
        if mem_count > 0:
            conn.execute("INSERT INTO memories_fts(memories_fts) VALUES('rebuild')")
    conn.commit()
