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
  echo "already at $NEW — nothing to do"; exit 0
fi

echo "bumping $OLD → $NEW"

PYBIN="${PYTHON:-python3}"
"$PYBIN" - "$OLD" "$NEW" <<'PY'
import re, sys
old, new = sys.argv[1], sys.argv[2]
# (path, regex, replacement) — regex matches ANY 0.2.X so a file missed by a
# previous bump still gets caught up.
edits = [
    ("pyproject.toml", r'^version = "0\.2\.[0-9]+"', f'version = "{new}"'),
    ("src/luminary_memory/__init__.py", r'__version__ = "0\.2\.[0-9]+"', f'__version__ = "{new}"'),
    ("src/luminary_memory/hermes/plugin.yaml", r'^version: 0\.2\.[0-9]+$', f"version: {new}"),
    ("website/index.html", r'v0\.2\.[0-9]+ - Self-Hosted Memory Layer', f"v{new} - Self-Hosted Memory Layer"),
    ("docs/ROADMAP.md", r'Current release:\*\* v0\.2\.[0-9]+', f"Current release:** v{new}"),
    ("README.md", r'v0\.2\.[0-9]+ → v1\.0\.0', f"v{new} → v1.0.0"),
    ("docs/ROADMAP.md", r'v0\.2\.[0-9]+ → v1\.0\.0', f"v{new} → v1.0.0"),
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

# pip requirement floors — any >=0.2.X
for path in ("hermes/install.sh", "hermes/SKILL.md", "hermes/README.md", "src/luminary_memory/hermes/plugin.yaml"):
    try:
        s = open(path).read()
    except FileNotFoundError:
        continue
    n = len(re.findall(r'luminary-memory\[hermes\]>=0\.2\.[0-9]+', s))
    if n:
        open(path, "w").write(re.sub(r'luminary-memory\[hermes\]>=0\.2\.[0-9]+', f"luminary-memory[hermes]>={new}", s))
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
STALE=$(grep -rnoE "0\.2\.[0-9]+" --include="*.md" --include="*.toml" --include="*.py" --include="*.yml" --include="*.yaml" --include="*.html" --include="*.sh" . 2>/dev/null \
  | grep -vE "\.git/|docs/api/|\.pytest_cache|CHANGELOG|PLAN|REPORT|benchmarks/RESULTS|\.commandcode" \
  | grep -vE "${NEW//./\\.}" || true)
if [[ -n "$STALE" ]]; then
  echo "⚠️  stale versions remain (review manually — may be historical refs):"
  echo "$STALE"
else
  echo "✅ all version references consistent at $NEW"
fi
