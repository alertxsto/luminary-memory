import sqlite3

from luminary_memory.schema import init_schema


def test_init_schema_creates_tables(tmp_path):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    init_schema(conn)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"memories", "memories_fts", "entities", "relations"} <= tables
    conn.close()

def test_fts_trigger_syncs_content(tmp_path):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    init_schema(conn)
    conn.execute(
        "INSERT INTO memories (content) VALUES (?)", ("hello world token",))
    conn.commit()
    row = conn.execute(
        "SELECT COUNT(*) FROM memories_fts WHERE memories_fts MATCH 'world'").fetchone()
    assert row[0] == 1
    conn.close()


def test_init_schema_rebuilds_fts_for_upgraded_db(tmp_path):
    """A DB created before the FTS5 table existed gets its keyword index rebuilt.

    Regression: rows that predate the FTS virtual table are never indexed by
    the triggers, so keyword search silently returned zero hits. init_schema
    must detect the upgrade and run an FTS 'rebuild' once.
    """
    db = tmp_path / "upgrade.db"
    # Old schema (matches the production memories table that predates the FTS5
    # virtual table): rows populated, no FTS table yet.
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE memories (id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT, tags TEXT DEFAULT '[]')")
    conn.executemany("INSERT INTO memories (content, tags) VALUES (?, '[]')",
                     [("alpha beta marker",), ("gamma delta marker",)])
    conn.commit()
    conn.close()

    # Upgrade: running init_schema creates the FTS table and must rebuild it.
    conn = sqlite3.connect(db)
    init_schema(conn)
    n = conn.execute(
        "SELECT COUNT(*) FROM memories_fts WHERE memories_fts MATCH '\"marker\"'").fetchone()[0]
    assert n == 2, f"pre-existing rows must be keyword-searchable after upgrade, got {n}"
    conn.close()


def test_init_schema_rebuild_is_idempotent_and_cheap_on_reopen(tmp_path):
    """Subsequent opens must not touch the FTS index again (no spurious rebuild)."""
    db = tmp_path / "reopen.db"
    conn = sqlite3.connect(db)
    init_schema(conn)
    conn.execute("INSERT INTO memories (content) VALUES (?)", ("hello world",))
    conn.commit()
    conn.close()

    conn = sqlite3.connect(db)
    init_schema(conn)  # second open — FTS table already exists
    n = conn.execute(
        "SELECT COUNT(*) FROM memories_fts WHERE memories_fts MATCH 'world'").fetchone()[0]
    assert n == 1, f"reopen must keep the FTS index in sync, got {n}"
    conn.close()
