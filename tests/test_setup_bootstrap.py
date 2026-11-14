"""Execute the platform installer with isolated homes and fixture package tooling."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = os.name == "nt"


@pytest.fixture
def bootstrap(tmp_path):
    home = tmp_path / "home with spaces"
    home.mkdir()
    tools = tmp_path / "tools"
    tools.mkdir()
    log = tmp_path / "tooling.jsonl"
    fixture = tools / "fixture_uv.py"
    fixture.write_text('''import json, os, pathlib, subprocess, sys
args = sys.argv[1:]
with open(os.environ["FIXTURE_LOG"], "a") as out:
    out.write(json.dumps(args) + "\\n")
if args[0] == "venv":
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", args[1]], check=True)
elif args[:2] == ["pip", "install"]:
    python = args[args.index("--python") + 1]
    requested = next(part.split("==", 1)[1] for part in args if part.startswith("luminary-memory=="))
    site = pathlib.Path(subprocess.check_output([python, "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"], text=True).strip())
    package = site / "luminary_memory"
    (package / "integrations").mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text(f'__version__ = "{requested}"\\n')
    (package / "integrations" / "__init__.py").write_text("")
    if requested == "0.3.5":
        (package / "integrations" / "setup.py").write_text("def run_setup(): pass\\n")
        (package / "integrations" / "__main__.py").write_text('import json, os, pathlib, sys\\npathlib.Path(os.environ["HOME"], "delegated.json").write_text(json.dumps(sys.argv[1:]))\\n')
    metadata = site / f"luminary_memory-{requested}.dist-info"
    metadata.mkdir(exist_ok=True)
    (metadata / "METADATA").write_text(f"Name: luminary-memory\\nVersion: {requested}\\n")
else:
    sys.exit(9)
''', encoding="utf-8")
    if WINDOWS:
        (tools / "uv.cmd").write_text(f'@"{sys.executable}" "{fixture}" %*\r\n')
        shell = shutil.which("powershell")
        assert shell, "Windows acceptance requires real PowerShell"
        command = [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "install.ps1")]
        path = str(tools) + os.pathsep + os.environ.get("SystemRoot", r"C:\Windows") + r"\System32"
    else:
        uv = tools / "uv"
        uv.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{fixture}" "$@"\n')
        uv.chmod(0o755)
        command = ["/bin/sh", str(ROOT / "install.sh")]
        path = str(tools) + os.pathsep + "/usr/bin:/bin"
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith(("LUMINARY_", "UV_", "PYTHON"))}
    env.update(HOME=str(home), USERPROFILE=str(home), XDG_CONFIG_HOME=str(home / "config"),
               APPDATA=str(tools), LOCALAPPDATA=str(tools), PATH=path, FIXTURE_LOG=str(log),
               LUMINARY_VERSION="0.3.5")
    if WINDOWS:
        # PowerShell itself initializes AppData/Roaming even with -NoProfile.
        # Establish that shell-owned baseline before measuring installer writes.
        subprocess.run([shell, "-NoProfile", "-Command", "exit 0"], env=env, check=True)

    def invoke(*flags):
        translated = [{"--agents": "-Agents", "--version": "-Version", "--dry-run": "-DryRun", "--check": "-Check", "--upgrade": "-Upgrade", "--uninstall": "-Uninstall", "--list": "-List"}.get(flag, flag) if WINDOWS else flag for flag in flags]
        return subprocess.run(command + translated, check=False, env=env, cwd=tmp_path, capture_output=True, text=True, timeout=60)

    return home, log, invoke


@pytest.mark.parametrize("flags,success", [
    (("--agents", "pi", "--dry-run"), True),
    (("--agents", "pi", "--check"), False),
    (("--agents", "unknown", "--dry-run"), False),
    (("--agents", "pi", "--version", "../escape", "--dry-run"), False),
    (("--agents", "pi", "--check", "--upgrade"), False),
    (("--list",), True),
])
def test_readonly_and_invalid_requests_never_bootstrap(bootstrap, flags, success):
    home, log, invoke = bootstrap
    before = sorted(path.relative_to(home).as_posix() for path in home.rglob("*"))
    result = invoke(*flags)
    assert (result.returncode == 0) is success, result.stdout + result.stderr
    assert not log.exists(), result.stdout + result.stderr
    assert sorted(path.relative_to(home).as_posix() for path in home.rglob("*")) == before
    assert (result.stdout + result.stderr).strip()


def test_release_without_setup_fails_before_host_mutation(bootstrap):
    home, log, invoke = bootstrap
    result = invoke("--agents", "pi", "--version", "0.3.4")
    assert result.returncode != 0, result.stdout + result.stderr
    assert log.exists(), "the requested release is provisioned before its capability is known"
    assert not (home / ".luminary" / "bridge.json").exists()
    assert not (home / "delegated.json").exists()
    assert "predates managed setup" in result.stdout + result.stderr


def test_interrupted_bootstrap_repairs_package_and_delegates(bootstrap):
    home, log, invoke = bootstrap
    venv = home / ".luminary" / "venvs" / "0.3.5"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True)
    result = invoke("--agents", "pi")
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads((home / "delegated.json").read_text())[:3] == ["setup", "--agents", "pi"]
    operations = [json.loads(line) for line in log.read_text().splitlines()]
    assert any(args[:2] == ["pip", "install"] for args in operations)
    before = log.read_bytes()
    result = invoke("--agents", "pi")
    assert result.returncode == 0, result.stdout + result.stderr
    assert log.read_bytes() == before, "healthy repeat must not provision again"
