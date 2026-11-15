"""One read-only release gate: every file that carries the version must agree.

Run from the repository root. Kept as a Python program instead of a heredoc so
Windows runners can execute it without a POSIX shell; ``bash scripts/bump-version.sh
--check`` delegates here.
"""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import re
import tomllib


def text(path):
    return Path(path).read_text(encoding="utf-8")


version = tomllib.loads(text("pyproject.toml"))["project"]["version"]
module = ast.parse(text("src/luminary_memory/__init__.py"))
python_version = next(
    ast.literal_eval(node.value) for node in module.body
    if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__version__" for t in node.targets)
)
if python_version != version:
    raise SystemExit("Python runtime version differs from project metadata")
lock = json.loads(text("package-lock.json"))
for agent in ("pi", "opencode", "omp"):
    path = f"plugins/{agent}/package.json"
    manifest = json.loads(text(path))
    if manifest["name"] != f"luminary-memory-{agent}" or manifest["version"] != version:
        raise SystemExit(f"{path}: package identity/version differs from Python {version}")
    if lock["packages"][f"plugins/{agent}"]["version"] != version:
        raise SystemExit(f"package-lock.json: {agent} version differs from Python {version}")
for path, pattern in (
    ("install.sh", r'VERSION="\$\{LUMINARY_VERSION:-([0-9.]+)\}"'),
    ("install.ps1", r'\$Version = "([0-9.]+)"'),
    ("src/luminary_memory/hermes/plugin.yaml", r'^version: ([0-9.]+)$'),
):
    matches = re.findall(pattern, text(path), re.M)
    if matches != [version]:
        raise SystemExit(f"{path}: version default differs from Python {version}")
tag = os.environ.get("RELEASE_TAG")
if tag and tag != f"v{version}":
    raise SystemExit(f"Tag {tag!r} differs from source version v{version}")
print(f"Source versions synchronized: {version} (no publication claimed)")
