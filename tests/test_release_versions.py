"""The existing version procedure must reject inconsistent release inputs."""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("drift", [None, "lock", "installer", "tag"])
def test_version_check_is_readonly_and_rejects_drift(tmp_path, drift):
    paths = ["pyproject.toml", "src/luminary_memory/__init__.py", "src/luminary_memory/hermes/plugin.yaml",
             "package-lock.json", "install.sh", "install.ps1", *[f"plugins/{a}/package.json" for a in ("pi", "omp", "opencode")]]
    for name in paths:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    if drift == "lock":
        path = tmp_path / "package-lock.json"
        data = json.loads(path.read_text())
        data["packages"]["plugins/pi"]["version"] = "99.0.0"
        path.write_text(json.dumps(data))
    elif drift == "installer":
        path = tmp_path / "install.ps1"
        path.write_text(re.sub(r'\$Version = "[0-9.]+"', '$Version = "99.0.0"', path.read_text()))
    before = {name: (tmp_path / name).read_bytes() for name in paths}
    environment = dict(os.environ, PYTHON=sys.executable)
    environment["RELEASE_TAG"] = "v99.0.0" if drift == "tag" else ""
    result = subprocess.run(["bash", str(ROOT / "scripts/bump-version.sh"), "--check"], check=False, cwd=tmp_path, env=environment,
                            capture_output=True, text=True, timeout=30)
    assert (result.returncode == 0) is (drift is None), result.stdout + result.stderr
    assert {name: (tmp_path / name).read_bytes() for name in paths} == before
