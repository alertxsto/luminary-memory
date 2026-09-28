"""Behavioral checks of release preparation and publication preconditions."""

import os
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CURRENT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
major, minor, patch = map(int, CURRENT.split("."))
NEXT = f"{major}.{minor}.{patch + 1}"
RELEASE_FILES = (
    "pyproject.toml",
    "src/luminary_memory/__init__.py",
    "src/luminary_memory/hermes/plugin.yaml",
    "hermes/install.sh",
    "website/index.html",
    "website/docs.html",
    "website/js/docs-guides.js",
)


def _fixture(tmp_path):
    for filename in RELEASE_FILES:
        target = tmp_path / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / filename, target)
    script = tmp_path / "scripts" / "bump-version.sh"
    script.parent.mkdir()
    shutil.copyfile(ROOT / "scripts" / "bump-version.sh", script)
    return script


def _run_bump(script, version):
    return subprocess.run(
        ["bash", str(script), version], cwd=script.parent.parent,
        text=True, capture_output=True, check=False,
    )


def test_bump_updates_required_release_anchors_and_is_idempotent(tmp_path):
    script = _fixture(tmp_path)
    before = {name: (tmp_path / name).read_bytes() for name in RELEASE_FILES}
    first = _run_bump(script, NEXT)
    assert first.returncode == 0, first.stderr
    after = {name: (tmp_path / name).read_bytes() for name in RELEASE_FILES}
    assert all(after[name] != before[name] for name in RELEASE_FILES), "every current release surface must bump"
    for name in RELEASE_FILES:
        assert NEXT.encode() in after[name], name
    guide = after["website/js/docs-guides.js"].decode()
    assert f"The repository declares v{NEXT}." in guide
    assert f'["Declared version", "{NEXT} / Python 3.11+"]' in guide
    assert b"0.3.0\", \"2026-08-24" in after["website/js/docs-guides.js"], "historical release row must not be rewritten"
    second = _run_bump(script, NEXT)
    assert second.returncode == 0, second.stderr
    assert f"already at {NEXT}" in second.stdout
    assert after == {name: (tmp_path / name).read_bytes() for name in RELEASE_FILES}


def test_bump_missing_current_anchor_fails_without_partial_writes(tmp_path):
    script = _fixture(tmp_path)
    plugin = tmp_path / "src/luminary_memory/hermes/plugin.yaml"
    plugin.write_text(plugin.read_text().replace(
        f"luminary-memory>={CURRENT}", "luminary-memory>=0.0.0",
    ))
    before = {name: (tmp_path / name).read_bytes() for name in RELEASE_FILES}
    result = _run_bump(script, NEXT)
    assert result.returncode != 0
    assert "no files changed" in result.stderr
    assert before == {name: (tmp_path / name).read_bytes() for name in RELEASE_FILES}


def _wheel(path, version):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"luminary_memory-{version}.dist-info/METADATA", f"Name: luminary-memory\nVersion: {version}\n")
    return path


def _verify(tmp_path, tag, wheel_version, *, manual_ref=None, project_version=None):
    wheel = _wheel(tmp_path / "release.whl", wheel_version)
    project = tmp_path / "pyproject.toml"
    project.write_text(f'[project]\nname = "luminary-memory"\nversion = "{project_version or CURRENT}"\n')
    runtime = tmp_path / "__init__.py"
    runtime.write_text(f'__version__ = "{CURRENT}"\n')
    args = [sys.executable, str(ROOT / "scripts/verify-release.py"), "--tag", tag,
            "--wheel", str(wheel), "--project", str(project), "--runtime", str(runtime)]
    if manual_ref is not None:
        args.extend(["--manual-ref", manual_ref])
    return subprocess.run(args, text=True, capture_output=True, check=False)


def test_release_verifier_accepts_matching_tag_project_runtime_and_wheel(tmp_path):
    result = _verify(tmp_path, f"v{CURRENT}", CURRENT, manual_ref=f"refs/tags/v{CURRENT}")
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("tag,wheel,manual_ref,project", [
    (f"v{NEXT}", CURRENT, None, CURRENT),
    (f"v{CURRENT}", NEXT, None, CURRENT),
    (f"v{CURRENT}", CURRENT, "refs/heads/main", CURRENT),
    (f"v{CURRENT}", CURRENT, f"refs/tags/v{NEXT}", CURRENT),
    (f"v{CURRENT}", CURRENT, None, NEXT),
])
def test_release_verifier_rejects_mismatch(tmp_path, tag, wheel, manual_ref, project):
    result = _verify(tmp_path, tag, wheel, manual_ref=manual_ref, project_version=project)
    assert result.returncode != 0
    assert "release verification failed" in result.stderr


def test_installer_rejects_stale_distribution_before_activating(tmp_path):
    # An isolated interpreter has this checkout's distribution.
    # A pip wrapper simulates the no-op install that once left it stale.
    import venv

    env_dir = tmp_path / "venv"
    venv.EnvBuilder(with_pip=True, system_site_packages=True).create(env_dir)
    python = env_dir / "bin" / "python"
    subprocess.run([str(python), "-m", "pip", "install", "--no-deps", "--force-reinstall", str(ROOT)],
                   check=True, capture_output=True)
    repo = tmp_path / "checkout"
    (repo / "hermes").mkdir(parents=True)
    shutil.copyfile(ROOT / "hermes/install.sh", repo / "hermes/install.sh")
    (repo / "pyproject.toml").write_text(f'[project]\nversion = "{NEXT}"\n')
    wrapper = tmp_path / "stale-python"
    wrapper.write_text(f'''#!/usr/bin/env bash
if [ "$1" = "-m" ] && [ "$2" = "pip" ]; then exit 0; fi
exec "{python}" "$@"
''')
    wrapper.chmod(0o755)
    host = tmp_path / "agent"
    host.mkdir()
    (host / "__init__.py").write_text("")
    (host / "memory_provider.py").write_text('''class MemoryProvider:
    name = "host"
    def is_available(self): pass
    def initialize(self, session_id, **kwargs): pass
    def get_tool_schemas(self): pass
    def replaces_builtin_memory(self): pass
''')
    config = tmp_path / "hermes-home" / "config.yaml"
    config.parent.mkdir()
    config.write_text("memory:\n  provider: default\n")
    process = subprocess.run(
        ["bash", str(repo / "hermes/install.sh"), "--no-hook", "--no-skill"],
        env={**os.environ, "HERMES_PYTHON": str(wrapper),
             "HERMES_HOME": str(config.parent), "PYTHONPATH": str(tmp_path)},
        text=True, capture_output=True, check=False,
    )
    assert process.returncode != 0, process.stdout
    assert f"stale luminary-memory {CURRENT}" in process.stderr
    assert config.read_text() == "memory:\n  provider: default\n"
