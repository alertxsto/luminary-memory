"""Runtime health and per-host setup transaction regressions."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from luminary_memory import __version__
from luminary_memory.integrations import setup


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("LUMINARY_CONFIG_FILE", "none")
    monkeypatch.setenv("LUMINARY_DB_PATH", str(tmp_path / "must-not-open.db"))
    monkeypatch.delenv("LUMINARY_PYTHON", raising=False)
    return tmp_path


def record(home, **agents):
    path = home / ".luminary" / "bridge.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": 1, "agents": agents}), encoding="utf-8")
    return path


def entry(python=sys.executable, version=__version__, mode="npm"):
    return {"python": str(python), "version": version, "mode": mode}


def bare_python(root):
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(root)], check=True)
    return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def test_check_rejects_missing_package_without_opening_store(isolated, capsys):
    interpreter = bare_python(isolated / "incomplete")
    bridge = record(isolated, pi=entry(interpreter))
    before = bridge.read_bytes()
    assert setup.run_setup("pi", check=True, home=isolated, json_output=True) == 1
    assert json.loads(capsys.readouterr().out)["agents"][0]["status"] == "broken"
    assert bridge.read_bytes() == before
    assert not (isolated / "must-not-open.db").exists()


def test_check_reports_actual_distribution_drift(isolated, capsys):
    record(isolated, pi=entry(version="0.0.1"))
    assert setup.run_setup("pi", check=True, home=isolated, json_output=True) == 1
    assert json.loads(capsys.readouterr().out)["agents"][0]["status"] == "drift"
    assert not (isolated / "must-not-open.db").exists()


def test_check_rejects_broken_import_even_when_metadata_matches(isolated, capsys):
    interpreter = bare_python(isolated / "broken")
    site = Path(subprocess.check_output([str(interpreter), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"], text=True).strip())
    metadata = site / f"luminary_memory-{__version__}.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(f"Name: luminary-memory\nVersion: {__version__}\n")
    package = site / "luminary_memory"
    package.mkdir()
    (package / "__init__.py").write_text("raise RuntimeError('broken package')\n")
    record(isolated, pi=entry(interpreter))
    assert setup.run_setup("pi", check=True, home=isolated, json_output=True) == 1
    assert json.loads(capsys.readouterr().out)["agents"][0]["status"] == "broken"


def test_invalid_override_does_not_silently_reuse_managed_python(isolated, monkeypatch):
    bridge = record(isolated, pi=entry())
    before = bridge.read_bytes()
    monkeypatch.setenv("LUMINARY_PYTHON", str(isolated / "missing interpreter"))
    assert setup.run_setup("pi", no_config=True, home=isolated) == 1
    assert bridge.read_bytes() == before
    assert not (isolated / "must-not-open.db").exists()


def test_failed_core_handshake_preserves_existing_registration(isolated, monkeypatch):
    root = setup.config_root("opencode", isolated)
    root.mkdir(parents=True)
    config = root / "opencode.jsonc"
    config.write_text('{"plugins":["other", "luminary-memory-opencode@0.0.1"]}')
    bridge = record(isolated, opencode=entry(version="0.0.1"), omp=entry())
    before = (config.read_bytes(), bridge.read_bytes())
    monkeypatch.setattr(setup, "ensure_venv", lambda *a, **kw: Path(sys.executable))
    monkeypatch.setattr(setup, "handshake", lambda *a: {"version": {"ok": True, "version": __version__}, "core": {"ok": False, "reason": "unavailable"}, "legacy": False})
    assert setup.run_setup("opencode", upgrade=True, home=isolated) == 1
    assert (config.read_bytes(), bridge.read_bytes()) == before


def test_readonly_fresh_home_never_creates_managed_state(isolated):
    assert setup.run_setup("pi", dry_run=True, home=isolated) == 0
    assert setup.run_setup("pi", check=True, home=isolated) == 1
    assert not (isolated / ".luminary").exists()
    assert not (isolated / "must-not-open.db").exists()


def test_no_config_preserves_host_but_registers_verified_runtime(isolated):
    root = setup.config_root("pi", isolated)
    root.mkdir(parents=True)
    config = root / "settings.json"
    config.write_text('{"packages":["npm:unrelated"]}')
    assert setup.run_setup("pi", no_config=True, home=isolated, python=Path(sys.executable)) == 0
    assert json.loads(config.read_text()) == {"packages": ["npm:unrelated"]}
    assert json.loads((isolated / ".luminary" / "bridge.json").read_text())["agents"]["pi"]["python"] == sys.executable


def test_jsonc_values_containing_trailing_comma_sequence_are_preserved():
    source = '{"message":"keep ,} and ,]", "url":"https://host//x", /* comment */ "plugins":[],}'
    assert json.loads(setup._strip_jsonc(source))["message"] == "keep ,} and ,]"


@pytest.fixture
def host_cli(isolated, monkeypatch):
    tools = isolated / "host-tools"
    tools.mkdir()
    script = tools / "host.py"
    script.write_text('''import json, os, pathlib, sys
agent, *args = sys.argv[1:]
home = pathlib.Path(os.environ["USERPROFILE"] if os.name == "nt" else os.environ["HOME"])
name = "luminary-memory-" + agent
if os.environ.get("FIXTURE_HOST_FAIL") == "1":
    sys.exit(7)
if agent == "pi":
    root = pathlib.Path.cwd() / ".pi" if "--local" in args else home / ".pi" / "agent"
    path = root / "settings.json"
    data = json.loads(path.read_text()) if path.exists() else {}
    items = data.setdefault("packages", [])
    if args[0] == "install":
        source = args[1]
        assert source.startswith("npm:" + name + "@")
        data["packages"] = [x for x in items if not str(x).startswith("npm:" + name)] + [source]
        version = source.rsplit("@", 1)[1]
        package = root / "npm" / "node_modules" / name
        package.mkdir(parents=True, exist_ok=True)
        (package / "package.json").write_text(json.dumps({"name": name, "version": version}))
    elif args[0] == "remove":
        data["packages"] = [x for x in items if not str(x).startswith("npm:" + name)]
    else:
        sys.exit(8)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
else:
    assert args[0] == "plugin"
    root = home / ".omp" / "plugins"
    root.mkdir(parents=True, exist_ok=True)
    path = root / "package.json"
    data = json.loads(path.read_text()) if path.exists() else {"dependencies": {}}
    package = root / "node_modules" / name
    if args[1] == "install":
        assert args[2].startswith(name + "@")
        version = args[2].rsplit("@", 1)[1]
        data["dependencies"][name] = version
        package.mkdir(parents=True, exist_ok=True)
        (package / "package.json").write_text(json.dumps({"name": name, "version": version, "omp": {"extensions": ["./dist/index.js"]}}))
        lock = root / "omp-plugins.lock.json"
        current = json.loads(lock.read_text()) if lock.exists() else {"plugins": {}}
        current["plugins"][name] = {"enabled": True, "version": version}
        lock.write_text(json.dumps(current))
    elif args[1] == "uninstall":
        data["dependencies"].pop(name, None)
        if package.exists():
            import shutil
            shutil.rmtree(package)
        lock = root / "omp-plugins.lock.json"
        current = json.loads(lock.read_text()) if lock.exists() else {"plugins": {}}
        current["plugins"].pop(name, None)
        lock.write_text(json.dumps(current))
    else:
        sys.exit(8)
    path.write_text(json.dumps(data))
''', encoding="utf-8")
    for agent in ("pi", "omp"):
        command = tools / (agent + (".cmd" if os.name == "nt" else ""))
        command.write_text(
            f'@"{sys.executable}" "{script}" {agent} %*\r\n' if os.name == "nt"
            else f'#!/bin/sh\nexec "{sys.executable}" "{script}" {agent} "$@"\n',
        )
        command.chmod(0o755)
    monkeypatch.setenv("PATH", str(tools) + os.pathsep + os.environ["PATH"])
    return isolated


@pytest.mark.parametrize("agent", ["pi", "omp", "opencode"])
def test_native_setup_migrates_owned_copy_and_repeats_without_duplicates(host_cli, agent):
    home = host_cli
    root = setup.config_root(agent, home)
    from luminary_memory.integrations.cli import install_adapter
    install_adapter(agent, root)
    old_copy = root / ("plugins" if agent == "opencode" else "extensions") / "luminary-memory"
    record(home, **{agent: entry(version="0.3.4", mode="copy")})
    for _ in range(2):
        assert setup.run_setup(agent, upgrade=True, home=home, python=Path(sys.executable)) == 0
        assert not old_copy.exists()
        bridge = json.loads((home / ".luminary" / "bridge.json").read_text())
        assert bridge["agents"][agent]["mode"] == "npm"
        assert setup._plugin_pin(agent, root) == __version__
    if agent == "pi":
        assert json.loads((root / "settings.json").read_text())["packages"] == [f"npm:luminary-memory-pi@{__version__}"]


def test_native_host_failure_preserves_copy_record_and_unrelated_settings(host_cli, monkeypatch):
    from luminary_memory.integrations.cli import install_adapter
    root = setup.config_root("pi", host_cli)
    install_adapter("pi", root)
    settings = root / "settings.json"
    settings.write_text('{"theme":"custom","packages":["npm:unrelated"]}')
    bridge = record(host_cli, pi=entry(mode="copy"), omp=entry())
    before = bridge.read_bytes(), settings.read_bytes()
    monkeypatch.setenv("FIXTURE_HOST_FAIL", "1")
    assert setup.run_setup("pi", upgrade=True, home=host_cli, python=Path(sys.executable)) == 1
    assert (bridge.read_bytes(), settings.read_bytes()) == before
    assert (root / "extensions" / "luminary-memory" / "index.js").exists()


def test_modified_copy_conflict_does_not_install_native_package(host_cli):
    from luminary_memory.integrations.cli import install_adapter
    root = setup.config_root("pi", host_cli)
    install_adapter("pi", root)
    copy = root / "extensions" / "luminary-memory" / "index.js"
    copy.write_text("// operator customized\\n")
    bridge = record(host_cli, pi=entry(mode="copy"))
    before = bridge.read_bytes()
    assert setup.run_setup("pi", upgrade=True, home=host_cli, python=Path(sys.executable)) == 1
    assert bridge.read_bytes() == before
    assert copy.read_text() == "// operator customized\\n"
    assert not (root / "settings.json").exists()


def test_selected_native_uninstall_preserves_other_host_and_memories(host_cli):
    home = host_cli
    assert setup.run_setup("pi,omp", home=home, python=Path(sys.executable)) == 0
    store = home / "must-not-open.db"
    before = store.read_bytes()
    assert setup.run_setup("pi", uninstall=True, home=home) == 0
    bridge = json.loads((home / ".luminary" / "bridge.json").read_text())
    assert set(bridge["agents"]) == {"omp"}
    assert setup._plugin_pin("omp", setup.config_root("omp", home)) == __version__
    assert store.read_bytes() == before


def test_omp_project_native_is_refused_before_writes(isolated):
    assert setup.run_setup("omp", project=True, home=isolated) != 0
    assert not (isolated / ".luminary").exists()


def test_pre_managed_copy_requires_explicit_upgrade(host_cli):
    bridge = record(host_cli, pi=entry(version="0.3.4", mode="copy"))
    before = bridge.read_bytes()
    assert setup.run_setup("pi", home=host_cli, python=Path(sys.executable)) == 1
    assert bridge.read_bytes() == before


@pytest.fixture
def runtime_tooling(isolated, monkeypatch):
    import sysconfig
    tools = isolated / "runtime tools"
    tools.mkdir()
    installer = tools / "uv_fixture.py"
    installer.write_text(f'''import pathlib, subprocess, sys
args = sys.argv[1:]
if args[0] == "venv":
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", args[1]], check=True)
else:
    assert args[:2] == ["pip", "install"]
    target = args[args.index("--python") + 1]
    site = pathlib.Path(subprocess.check_output([target, "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"], text=True).strip())
    (site / "fixture-installed-bridge.pth").write_text("import site; site.addsitedir(" + repr({sysconfig.get_path('purelib')!r}) + ")\\n")
''', encoding="utf-8")
    uv = tools / ("uv.cmd" if os.name == "nt" else "uv")
    uv.write_text(
        f'@"{sys.executable}" "{installer}" %*\r\n' if os.name == "nt"
        else f'#!/bin/sh\nexec "{sys.executable}" "{installer}" "$@"\n',
    )
    uv.chmod(0o755)
    monkeypatch.setenv("PATH", str(tools) + os.pathsep + os.environ["PATH"])
    return isolated


def test_interrupted_runtime_is_repaired_and_healthy_repeat_is_reused(runtime_tooling):
    home = runtime_tooling
    target = setup._venv_python(home, __version__)
    bare_python(target.parent.parent)
    assert setup._probe_version(target) is None
    assert setup.ensure_venv(__version__, home) == target
    assert setup._probe_version(target) == __version__
    site = Path(subprocess.check_output([str(target), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"], text=True).strip())
    marker = site / "fixture-installed-bridge.pth"
    before = marker.stat().st_mtime_ns
    assert setup.ensure_venv(__version__, home) == target
    assert marker.stat().st_mtime_ns == before


def test_two_setup_processes_converge_on_verified_runtime(runtime_tooling):
    home = runtime_tooling
    code = "import sys; from pathlib import Path; from luminary_memory.integrations.setup import run_setup; sys.exit(run_setup('pi', no_config=True, home=Path(sys.argv[1])))"
    children = [subprocess.Popen([sys.executable, "-c", code, str(home)], cwd=home, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
    results = [child.communicate(timeout=120) for child in children]
    assert [child.returncode for child in children] == [0, 0], results
    bridge = json.loads((home / ".luminary" / "bridge.json").read_text())
    assert set(bridge["agents"]) == {"pi"}
    assert bridge["agents"]["pi"]["python"] == str(setup._venv_python(home, __version__))
    assert setup._probe_version(Path(bridge["agents"]["pi"]["python"])) == __version__


@pytest.mark.parametrize("operation", ["upgrade", "uninstall"])
def test_record_write_failure_restores_native_registration_and_owned_copy(host_cli, monkeypatch, operation):
    from luminary_memory.integrations.cli import install_adapter
    root = setup.config_root("pi", host_cli)
    install_adapter("pi", root)
    settings = root / "settings.json"
    settings.write_text('{"theme":"custom","packages":["npm:unrelated"]}')
    bridge = record(host_cli, pi=entry(mode="copy"))
    before = bridge.read_bytes(), settings.read_bytes()
    def unavailable(*args, **kwargs):
        raise OSError("record storage unavailable")
    monkeypatch.setattr(setup, "_write_bridge", unavailable)
    assert setup.run_setup("pi", **{operation: True}, home=host_cli, python=Path(sys.executable)) == 1
    assert (bridge.read_bytes(), settings.read_bytes()) == before
    assert (root / "extensions" / "luminary-memory" / "index.js").exists()


def test_prune_preserves_referenced_paths_and_unowned_directories(isolated):
    root = isolated / ".luminary" / "venvs"
    referenced = root / "0.0.1"
    orphan = root / "0.0.2"
    unrelated = root / "operator-project"
    for directory in (referenced, orphan, unrelated):
        directory.mkdir(parents=True)
        (directory / "pyvenv.cfg").write_text("home = fixture\\n")
    bridge = {"schema": 1, "agents": {"pi": entry(referenced / "bin" / "python", version="0.9.9")}}
    assert setup._prune(isolated, bridge, dry_run=False) == ["0.0.2"]
    assert referenced.exists()
    assert unrelated.exists()


def test_pi_project_uninstall_keeps_user_registration_and_shared_bridge(host_cli, monkeypatch):
    home = host_cli
    assert setup.run_setup("pi", home=home, python=Path(sys.executable)) == 0
    project = home / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    assert setup.run_setup("pi", project=True, home=home, python=Path(sys.executable)) == 0
    assert setup._plugin_pin("pi", project / ".pi") == __version__
    before = (home / ".luminary" / "bridge.json").read_bytes()
    assert setup.run_setup("pi", project=True, uninstall=True, home=home) == 0
    assert setup._plugin_pin("pi", project / ".pi") is None
    assert setup._plugin_pin("pi", setup.config_root("pi", home)) == __version__
    assert (home / ".luminary" / "bridge.json").read_bytes() == before


def test_uninstall_removes_native_range_pin_without_installing_runtime(isolated):
    root = setup.config_root("opencode", isolated)
    root.mkdir(parents=True)
    config = root / "opencode.jsonc"
    config.write_text('{"plugins":["unrelated","luminary-memory-opencode@latest"]}')
    assert setup.run_setup("opencode", uninstall=True, home=isolated) == 0
    assert json.loads(config.read_text())["plugins"] == ["unrelated"]
    assert not (isolated / "must-not-open.db").exists()


def test_handshake_does_not_execute_workspace_shadow_package(isolated, monkeypatch):
    workspace = isolated / "workspace"
    shadow = workspace / "luminary_memory"
    shadow.mkdir(parents=True)
    marker = isolated / "shadow-executed"
    (shadow / "__init__.py").write_text(f"open({str(marker)!r}, 'w').close()\n")
    monkeypatch.chdir(workspace)
    result = setup.handshake(Path(sys.executable), "pi", workspace)
    assert result["version"]["ok"] is True
    assert not marker.exists(), "setup handshake must not import workspace code"


def test_global_uninstall_retains_record_for_project_registration(host_cli, monkeypatch):
    home = host_cli
    assert setup.run_setup("pi", home=home, python=Path(sys.executable)) == 0
    project = home / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    assert setup.run_setup("pi", project=True, home=home, python=Path(sys.executable)) == 0
    before = (home / ".luminary" / "bridge.json").read_bytes()
    assert setup.run_setup("pi", uninstall=True, home=home) == 0
    assert setup._plugin_pin("pi", setup.config_root("pi", home)) is None
    assert setup._plugin_pin("pi", project / ".pi") == __version__
    assert (home / ".luminary" / "bridge.json").read_bytes() == before


def test_prune_keeps_symlinked_posix_interpreter(isolated):
    root = isolated / ".luminary" / "venvs"
    venv = root / "0.0.1"
    (venv / "bin").mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text("home = /usr/bin\n")
    (venv / "bin" / "python").symlink_to(sys.executable)
    bridge = {"schema": 1, "agents": {"pi": entry(venv / "bin" / "python", version="0.9.9")}}
    assert setup._prune(isolated, bridge, dry_run=False) == []
    assert venv.exists()


def test_cross_scope_copy_blocks_native_migration(host_cli, monkeypatch):
    from luminary_memory.integrations.cli import install_adapter
    home = host_cli
    install_adapter("pi", setup.config_root("pi", home))
    project = home / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    assert setup.run_setup("pi", project=True, upgrade=True, home=home, python=Path(sys.executable)) == 1
    assert (setup.config_root("pi", home) / "extensions" / "luminary-memory" / "index.js").exists()
    assert not (project / ".pi" / "settings.json").exists()


def test_check_reports_missing_copied_adapter(isolated, capsys):
    record(isolated, pi=entry(mode="copy"))
    assert setup.run_setup("pi", check=True, home=isolated, json_output=True) == 1
    assert json.loads(capsys.readouterr().out)["agents"][0]["status"] == "broken"


def test_parked_cleanup_failure_does_not_report_failed_setup(host_cli, monkeypatch):
    from luminary_memory.integrations.cli import install_adapter
    home = host_cli
    install_adapter("pi", setup.config_root("pi", home))
    record(home, pi=entry(mode="copy"))
    original = setup.shutil.rmtree
    def fail_parked(path, *args, **kwargs):
        if ".luminary-disabled-" in str(path):
            raise OSError("read-only parked copy")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(setup.shutil, "rmtree", fail_parked)
    assert setup.run_setup("pi", upgrade=True, home=home, python=Path(sys.executable)) == 0
    assert json.loads((home / ".luminary" / "bridge.json").read_text())["agents"]["pi"]["mode"] == "npm"
