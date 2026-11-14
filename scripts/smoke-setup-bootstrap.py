#!/usr/bin/env python
"""Exercise the real platform wrapper, uv and a local wheel in a throwaway home.

This is local-artifact proof, not a registry-download or publication claim.
uv and managed Python are actually provisioned; no package-tooling doubles or
editable import paths are used. No host registration is changed (--no-config).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from email.parser import BytesParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def space_free(path: Path) -> Path:
    """uv splits a spaced UV_CONSTRAINT path; use the Windows short name."""
    if " " not in str(path):
        return path
    if os.name == "nt":
        import ctypes

        buffer = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, 32768):
            short = Path(buffer.value)
            if " " not in str(short):
                return short
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args()
    wheel = args.wheel.resolve(strict=True)
    with zipfile.ZipFile(wheel) as archive:
        metadata = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
        version = BytesParser().parsebytes(archive.read(metadata))["Version"]
    with tempfile.TemporaryDirectory(prefix="luminary actual bootstrap ") as temporary, \
            tempfile.TemporaryDirectory(prefix="luminary-bootstrap-staging-") as staging:
        root = Path(temporary)
        home, workspace = root / "home with spaces", root / "workspace"
        home.mkdir()
        workspace.mkdir()
        # uv cannot read a file:// direct reference whose path contains spaces,
        # so stage the wheel and constraint outside the spaced home.
        staged = Path(staging) / wheel.name
        shutil.copyfile(wheel, staged)
        constraint = Path(staging) / "candidate.txt"
        constraint.write_text(f"luminary-memory @ {space_free(staged).as_uri()}\n", encoding="utf-8")
        environment = {
            key: value for key, value in os.environ.items()
            if not key.upper().startswith(("LUMINARY_", "UV_", "PYTHON", "VIRTUAL_ENV", "CONDA_", "PI_", "OMP_"))
        }
        environment.update(
            HOME=str(home), USERPROFILE=str(home), APPDATA=str(root / "appdata"),
            LOCALAPPDATA=str(root / "local"), XDG_CONFIG_HOME=str(home / "config"),
            XDG_DATA_HOME=str(home / "data"), XDG_CACHE_HOME=str(root / "cache"),
            UV_CACHE_DIR=str(root / "uv-cache"),
            UV_PYTHON_INSTALL_DIR=str(home / ".luminary" / "bin" / "python"),
            UV_PYTHON_PREFERENCE="only-managed", UV_CONSTRAINT=str(space_free(constraint)),
            LUMINARY_CONFIG_FILE="none", LUMINARY_BACKEND="sqlite",
            LUMINARY_DB_PATH=str(home / "memory.db"), LUMINARY_USER_ID="bootstrap-artifact-owner",
        )
        windows = os.name == "nt"
        if windows:
            shell = shutil.which("powershell")
            if not shell:
                raise RuntimeError("Actual PowerShell is required for Windows bootstrap acceptance")
            command = [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "install.ps1")]
            environment["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
            subprocess.run([shell, "-NoProfile", "-Command", "exit 0"], env=environment, check=True)
        else:
            command = ["/bin/sh", str(ROOT / "install.sh")]
            environment["PATH"] = "/usr/bin:/bin"
        names = {
            "--agents": "-Agents", "--version": "-Version", "--no-config": "-NoConfig",
            "--dry-run": "-DryRun", "--check": "-Check", "--upgrade": "-Upgrade", "--uninstall": "-Uninstall",
        }

        def invoke(*flags: str, success: bool = True) -> None:
            values = [names.get(flag, flag) if windows else flag for flag in flags]
            result = subprocess.run(command + values, cwd=workspace, env=environment,
                                    check=False, capture_output=True, text=True, timeout=1200)
            if (result.returncode == 0) != success:
                raise AssertionError(f"wrapper {flags} exited {result.returncode}\n{result.stdout}\n{result.stderr}")

        def setup(*flags: str, agents: str = "pi", success: bool = True) -> None:
            invoke("--agents", agents, "--version", version, "--no-config", *flags, success=success)

        bridge = home / ".luminary" / "bridge.json"
        store = home / "memory.db"
        before = sorted(str(path.relative_to(home)) for path in home.rglob("*"))
        setup("--dry-run")
        setup("--check", success=False)
        assert sorted(str(path.relative_to(home)) for path in home.rglob("*")) == before
        setup()
        record = json.loads(bridge.read_text(encoding="utf-8"))
        python = Path(record["agents"]["pi"]["python"])
        assert python.is_relative_to(home / ".luminary" / "venvs")
        result = subprocess.run([str(python), "-I", "-c", "import importlib.metadata as m, json, sys; import luminary_memory; d=m.distribution('luminary-memory'); print(json.dumps({'package':luminary_memory.__file__,'version':d.version,'base':sys.base_prefix,'prefix':sys.prefix,'metadata':str(next(d.locate_file(p) for p in d.files if str(p).endswith('.dist-info/METADATA')))}))"],
                                check=True, env=environment, cwd=workspace, capture_output=True, text=True, timeout=30)
        runtime = json.loads(result.stdout)
        assert runtime["version"] == version
        assert Path(runtime["package"]).is_relative_to(Path(runtime["prefix"]))
        assert Path(runtime["base"]).is_relative_to(home / ".luminary" / "bin" / "python")
        metadata_path = Path(runtime["metadata"])
        installed_at = metadata_path.stat().st_mtime_ns
        setup()
        assert metadata_path.stat().st_mtime_ns == installed_at, "healthy repeat reinstalled the runtime"
        # Seed a genuine store row without downloading an embedding model during setup.
        subprocess.run([str(python), "-I", "-c", "import os; from luminary_memory.backends.sqlite import SQLiteBackend; from luminary_memory.types import Memory; b=SQLiteBackend(os.environ['LUMINARY_DB_PATH']); b.add(Memory(content='Bootstrap fixture fact', user_id='bootstrap-artifact-owner', workspace_id='fixture', agent_id='pi')); b.close()"],
                       check=True, env=environment, cwd=workspace, timeout=30)
        readonly = digest(bridge), digest(store)
        setup("--check")
        assert (digest(bridge), digest(store)) == readonly
        package = Path(runtime["package"]).parent
        shutil.rmtree(package)  # Own temporary runtime only; emulate an interrupted install.
        setup("--check", success=False)
        assert (digest(bridge), digest(store)) == readonly
        setup()
        setup("--upgrade", agents="pi,omp")
        assert set(json.loads(bridge.read_text())["agents"]) == {"pi", "omp"}
        before_remove = digest(store)
        setup("--uninstall")
        remaining = json.loads(bridge.read_text())["agents"]
        assert set(remaining) == {"omp"}
        assert remaining["omp"]["python"] == str(python)
        assert digest(store) == before_remove
        subprocess.run([str(python), "-I", "-c", "import os, sqlite3; c=sqlite3.connect(os.environ['LUMINARY_DB_PATH']); assert c.execute(\"select content from memories where content='Bootstrap fixture fact'\").fetchone()==('Bootstrap fixture fact',); c.close()"],
                       check=True, env=environment, cwd=workspace, timeout=30)
        assert not any((home / name).exists() for name in (
            ".pi/settings.json", ".omp/plugins/package.json", "config/opencode/opencode.jsonc",
        )), "no-config setup must not register a host"
        print(json.dumps({"platform": sys.platform, "version": version, "wheel_sha256": digest(wheel),
                          "actual_uv_managed_python": True, "cold_repeat_repair_check_upgrade_selected_remove": "passed",
                          "memory_preserved": True, "proof": "local wheel; no registry or publication claim"}))


if __name__ == "__main__":
    main()
