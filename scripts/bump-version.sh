#!/usr/bin/env bash
# bump-version.sh — bump version consistently across EVERY file that carries it.
# Usage: ./bump-version.sh 0.2.7
# Run from repo root. Verifies no stale version remains afterwards.
# Uses python3 for in-place edits (sed -i / perl -i are unreliable on some
# filesystems — python's write is atomic and portable).
set -euo pipefail

# One read-only release gate, shared by CI and publication.
if [[ "${1:-}" == "--check" ]]; then
  "${PYTHON:-python3}" - <<'PY'
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
PY
  exit $?
fi

OLD="$(sed -n 's/^version = "\([0-9]\+\.[0-9]\+\.[0-9]\+\)"/\1/p' pyproject.toml | head -1)"
NEW="${1:?usage: ./bump-version.sh X.Y.Z}"

if [[ "$NEW" == "$OLD" ]]; then
  echo "already at $NEW — synchronizing versioned files"
fi

echo "bumping $OLD → $NEW"

PYBIN="${PYTHON:-python3}"
"$PYBIN" - "$OLD" "$NEW" <<'PY'
import json
from pathlib import Path
import re
import sys

old, new = sys.argv[1], sys.argv[2]
if not re.fullmatch(r"\d+\.\d+\.\d+", new):
    raise SystemExit("version must have the form X.Y.Z")

# Documentation carries non-ASCII text, so never rely on the locale codec
# (cp1252 on Windows) for these rewrites.
def read_doc(path):
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


def write_doc(path, text):
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)

# Parse JSON structurally to validate identity, but rewrite only the version
# token so hand-formatted manifests and the lockfile keep their layout.
def sync_json_version(path, key, expected_name):
    raw = read_doc(path)
    document = json.loads(raw)
    manifest = document if key is None else document["packages"][key]
    if manifest.get("name") != expected_name:
        raise SystemExit(f"{path}: unexpected package name for {key or 'root'}")
    if key is None:
        start, end = 0, len(raw)
    else:
        marker = f'"{key}": {{'
        start = raw.index(marker)
        closer = re.compile(r"\r?\n    \},?")
        match = closer.search(raw, start)
        if match is None:
            raise SystemExit(f"{path}: unterminated workspace block {key}")
        end = match.start()
    block = raw[start:end]
    updated, count = re.subn(
        r'("version"\s*:\s*")[^"]+(")', rf"\g<1>{new}\g<2>", block, count=1
    )
    if count != 1:
        raise SystemExit(f"{path}: no version field inside {key or 'root'}")
    write_doc(path, raw[:start] + updated + raw[end:])
    print(f"  {path}: plugin version synchronized")


for agent in ("pi", "opencode", "omp"):
    sync_json_version(Path("plugins") / agent / "package.json", None, f"luminary-memory-{agent}")

# npm ci checks workspace versions against this lockfile. The private root
# package deliberately has no version and must remain unversioned.
for agent in ("pi", "opencode", "omp"):
    sync_json_version(Path("package-lock.json"), f"plugins/{agent}", f"luminary-memory-{agent}")

# (path, regex, replacement) — regex matches ANY 0.2.X so a file missed by a
# previous bump still gets caught up.
edits = [
    ("pyproject.toml", r'^version = "(\d+\.\d+\.\d+)"', f'version = "{new}"'),
    ("src/luminary_memory/__init__.py", r'__version__ = "(\d+\.\d+\.\d+)"', f'__version__ = "{new}"'),
    ("src/luminary_memory/hermes/plugin.yaml", r'^version: (\d+\.\d+\.\d+)$', f"version: {new}"),
    ("website/index.html", r'v\d+\.\d+\.\d+ - Self-Hosted Memory Layer', f"v{new} - Self-Hosted Memory Layer"),
    ("README.md", r'v\d+\.\d+\.\d+ → v1\.0\.0', f"v{new} → v1.0.0"),
    ("docs/ROADMAP.md", r'v\d+\.\d+\.\d+ → v1\.0\.0', f"v{new} → v1.0.0"),
    ("install.sh", r'VERSION="\$\{LUMINARY_VERSION:-(\d+\.\d+\.\d+)\}"', f'VERSION="${{LUMINARY_VERSION:-{new}}}"'),
    ("install.ps1", r'\$Version = "(\d+\.\d+\.\d+)"', f'$Version = "{new}"'),
]
for path, pat, repl in edits:
    try:
        s = read_doc(path)
    except FileNotFoundError:
        continue
    n = len(re.findall(pat, s, re.M))
    if n:
        write_doc(path, re.sub(pat, repl, s, flags=re.M))
        print(f"  {path}: {n} replacement(s)")

# remaining version displays (v-prefixed) and pip floors
for path, pat, repl in [
    ("website/docs.html", r'<span>v\d+\.\d+\.\d+</span>', f"<span>v{new}</span>"),
    ("website/index.html", r'<span>v\d+\.\d+\.\d+</span>', f"<span>v{new}</span>"),
]:
    try:
        s = read_doc(path)
    except FileNotFoundError:
        continue
    n = len(re.findall(pat, s))
    if n:
        write_doc(path, re.sub(pat, repl, s))
        print(f"  {path}: {n} version-display replacement(s)")

# pip requirement floors — any >=0.2.X
for path in ("hermes/install.sh", "hermes/SKILL.md", "hermes/README.md", "src/luminary_memory/hermes/plugin.yaml"):
    try:
        s = read_doc(path)
    except FileNotFoundError:
        continue
    n = len(re.findall(r"luminary-memory(\[hermes\])?>=\d+\.\d+\.\d+", s))
    if n:
        write_doc(path, re.sub(r"luminary-memory(\[hermes\])?>=\d+\.\d+\.\d+", lambda m: f"luminary-memory{m.group(1) or ''}>={new}", s))
        print(f"  {path}: {n} pip-floor replacement(s)")

PY

# CHANGELOG — prepend new entry if not present
if ! grep -q "## \[$NEW\]" CHANGELOG.md; then
  TMP="$(mktemp)"
  awk -v n="$NEW" -v d="$(date +%Y-%m-%d)" '
    NR==1 { print; print ""; print "## [" n "] - " d; print ""; print "### Added"; print ""; print "- _(fill in)_"; print ""; next }
    { print }
  ' CHANGELOG.md > "$TMP"
  mv "$TMP" CHANGELOG.md
fi

echo ""
echo "=== verify: any stale $OLD left? ==="
STALE=$(grep -rnoE "$OLD" --include="*.md" --include="*.toml" --include="*.py" --include="*.yml" --include="*.yaml" --include="*.html" --include="*.sh" . 2>/dev/null \
  | grep -vE "\.git/|docs/api/|\.pytest_cache|CHANGELOG|PLAN|REPORT|benchmarks/RESULTS|\.commandcode" \
  | grep -vE "${NEW//./\\.}" || true)
if [[ -n "$STALE" ]]; then
  echo "⚠️  stale versions remain (review manually — may be historical refs):"
  echo "$STALE"
else
  echo "✅ all version references consistent at $NEW"
fi
