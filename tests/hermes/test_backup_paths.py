"""T11: backup_paths — declare state outside HERMES_HOME."""

from luminary_memory.hermes.provider import LuminaryMemoryProvider


def test_backup_paths_default_empty(tmp_path):
    p = LuminaryMemoryProvider()
    p.initialize("s1", hermes_home=str(tmp_path))
    paths = p.backup_paths()
    assert paths == [], f"expected no backup paths for default config, got {paths}"
    p.shutdown()


def test_backup_paths_override_outside_home(tmp_path):
    outside = tmp_path.parent / "outside.db"
    p = LuminaryMemoryProvider()
    p.initialize("s1", hermes_home=str(tmp_path))
    p._config["db_path"] = str(outside)
    paths = p.backup_paths()
    assert paths == [str(outside)], f"expected [outside.db], got {paths}"
    p.shutdown()


def test_backup_paths_callable_without_initialize(tmp_path):
    p = LuminaryMemoryProvider()
    p._hermes_home = str(tmp_path)
    p._config["db_path"] = str(tmp_path.parent / "x.db")
    paths = p.backup_paths()
    assert paths == [str(tmp_path.parent / "x.db")]
