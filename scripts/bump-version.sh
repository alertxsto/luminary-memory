#!/usr/bin/env bash
# Bump only current release metadata; historical changelog entries stay historical.
# Usage (from repository root): bash scripts/bump-version.sh X.Y.Z
set -euo pipefail

NEW="${1:?usage: scripts/bump-version.sh X.Y.Z}"
"${PYTHON:-python3}" - "$NEW" <<'PY'
import os
import re
import sys
import tempfile
import tomllib
from pathlib import Path

new = sys.argv[1]
if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", new):
    raise SystemExit("expected a release version X.Y.Z")
project = Path("pyproject.toml")
old = tomllib.loads(project.read_text(encoding="utf-8"))["project"]["version"]
if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", old):
    raise SystemExit(f"invalid current project version: {old!r}")

# Each anchored expression matches an actual current-release field, never a
# historical changelog entry or an unrelated occurrence of the version.
# Expected counts must be checked on EVERY file before the first write.
fields = {
    "pyproject.toml": [(rf'(?m)^version = "{re.escape(old)}"$', 1)],
    "src/luminary_memory/__init__.py": [(rf'(?m)^__version__ = "{re.escape(old)}"$', 1)],
    "src/luminary_memory/hermes/plugin.yaml": [
        (rf'(?m)^version: {re.escape(old)}$', 1),
        (rf'(?m)^  - "luminary-memory>={re.escape(old)}"$', 1),
    ],
    "hermes/install.sh": [(rf'luminary-memory\[hermes\]>={re.escape(old)}', 1)],
    "website/index.html": [(rf'>v{re.escape(old)}</span>', 2)],
    "website/docs.html": [(rf'>v{re.escape(old)}</span>', 2)],
    "website/js/docs-guides.js": [
        (rf'The repository declares v{re.escape(old)}\.', 1),
        (rf'\["Declared version", "{re.escape(old)} / Python 3\.11\+"\]', 1),
    ],
}

pending = {}
errors = []
for filename, patterns in fields.items():
    path = Path(filename)
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"{filename}: {exc}")
        continue
    updated = content
    for literal_pattern, expected in patterns:
        matches = list(re.finditer(literal_pattern, content))
        if len(matches) != expected:
            errors.append(f"{filename}: expected {expected} current {old} anchor(s) for {literal_pattern!r}, found {len(matches)}")
        updated = re.sub(literal_pattern, lambda match: match.group().replace(old, new), updated)
    pending[path] = updated
if errors:
    raise SystemExit("release version preflight failed (no files changed):\n" + "\n".join(errors))
if new == old:
    print(f"already at {new}; all release anchors verified")
    raise SystemExit(0)
for path, content in pending.items():
    if content == path.read_text(encoding="utf-8"):
        continue
    mode = path.stat().st_mode
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as output:
        temp_name = output.name
        output.write(content)
    try:
        os.chmod(temp_name, mode)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    print(f"  {path}: updated")
print(f"release metadata: {old} -> {new}")
PY
