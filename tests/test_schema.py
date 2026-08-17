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
