#!/usr/bin/env bash
# bump-version.sh — bump version consistently across EVERY file that carries it.
# Usage: ./bump-version.sh 0.2.7
# Run from repo root. Verifies no stale version remains afterwards.
# Uses python3 for in-place edits (sed -i / perl -i are unreliable on some
# filesystems — python's write is atomic and portable).
set -euo pipefail

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

# Parse JSON structurally: dependency versions and other package metadata must
# not be touched by the display-version replacements below.
plugin_updates = []
agents = ("pi", "opencode", "omp")
for agent in agents:
    path = Path("plugins") / agent / "package.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("name") != f"luminary-memory-{agent}":
        raise SystemExit(f"{path}: unexpected plugin package name")
    manifest["version"] = new
    plugin_updates.append((path, manifest))

# npm ci checks workspace versions against this lockfile. The private root
# package deliberately has no version and must remain unversioned.
lock_path = Path("package-lock.json")
lock = json.loads(lock_path.read_text(encoding="utf-8"))
for agent in agents:
    key = f"plugins/{agent}"
    if key not in lock.get("packages", {}):
        raise SystemExit(f"{lock_path}: missing workspace {key}")
    lock["packages"][key]["version"] = new
plugin_updates.append((lock_path, lock))

# (path, regex, replacement) — regex matches ANY 0.2.X so a file missed by a
# previous bump still gets caught up.
edits = [
    ("pyproject.toml", r'^version = "(\d+\.\d+\.\d+)"', f'version = "{new}"'),
    ("src/luminary_memory/__init__.py", r'__version__ = "(\d+\.\d+\.\d+)"', f'__version__ = "{new}"'),
    ("src/luminary_memory/hermes/plugin.yaml", r'^version: (\d+\.\d+\.\d+)$', f"version: {new}"),
    ("website/index.html", r'v\d+\.\d+\.\d+ - Self-Hosted Memory Layer', f"v{new} - Self-Hosted Memory Layer"),
    ("docs/ROADMAP.md", r'Current release:\*\* v\d+\.\d+\.\d+', f"Current release:** v{new}"),
    ("README.md", r'v\d+\.\d+\.\d+ → v1\.0\.0', f"v{new} → v1.0.0"),
    ("docs/ROADMAP.md", r'v\d+\.\d+\.\d+ → v1\.0\.0', f"v{new} → v1.0.0"),
]
for path, pat, repl in edits:
    try:
        s = open(path).read()
    except FileNotFoundError:
        continue
    n = len(re.findall(pat, s, re.M))
    if n:
        open(path, "w").write(re.sub(pat, repl, s, flags=re.M))
        print(f"  {path}: {n} replacement(s)")

# remaining version displays (v-prefixed) and pip floors
for path, pat, repl in [
    ("docs/index.md", r'Released baseline: `\d+\.\d+\.\d+`', f"Released baseline: `{new}`"),
    ("website/docs.html", r'<span>v\d+\.\d+\.\d+</span>', f"<span>v{new}</span>"),
    ("website/index.html", r'<span>v\d+\.\d+\.\d+</span>', f"<span>v{new}</span>"),
]:
    try:
        s = open(path).read()
    except FileNotFoundError:
        continue
    n = len(re.findall(pat, s))
    if n:
        open(path, "w").write(re.sub(pat, repl, s))
        print(f"  {path}: {n} version-display replacement(s)")

# pip requirement floors — any >=0.2.X
for path in ("hermes/install.sh", "hermes/SKILL.md", "hermes/README.md", "src/luminary_memory/hermes/plugin.yaml"):
    try:
        s = open(path).read()
    except FileNotFoundError:
        continue
    n = len(re.findall(r'luminary-memory(\[hermes\])?>=\d+\.\d+\.\d+', s))
    if n:
        open(path, "w").write(re.sub(r'luminary-memory(\[hermes\])?>=\d+\.\d+\.\d+', lambda m: f"luminary-memory{m.group(1) or ''}>={new}", s))
        print(f"  {path}: {n} pip-floor replacement(s)")

for path, document in plugin_updates:
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  {path}: plugin versions synchronized")
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
