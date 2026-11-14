#!/usr/bin/env sh
# Luminary Memory one-command installer for OpenCode, pi, and omp.
#
#   curl -fsSL https://raw.githubusercontent.com/alertxsto/luminary-memory/main/install.sh | sh
#
# Provisions a private Python runtime with uv, installs the version-matched
# bridge, writes ~/.luminary/bridge.json, configures every detected agent, and
# verifies the bridge. No Python, Node, or venv setup is required.
set -eu

VERSION="${LUMINARY_VERSION:-0.3.4}"
AGENTS="auto"
MODE="sync"
NO_CONFIG=0
PROJECT=0
PRUNE=0
DRY_RUN=0
VERBOSE=0

usage() {
  cat <<'EOF'
Usage: install.sh [options]

  --agents LIST     auto (default) | all | opencode,pi,omp
  --all             configure every supported agent
  --version X       bridge version to install
  --check           report status without changing anything
  --upgrade         move plugin pins to the target version
  --uninstall       remove Luminary entries
  --prune           remove unreferenced bridge venvs
  --no-config       install the bridge only
  --project         target project-local config
  --dry-run         show actions without writing
  --verbose         print every command
  -h, --help        show this help
EOF
}

log() { printf '\033[1;36m[luminary]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[luminary]\033[0m ERROR: %s\n' "$*" >&2; exit 1; }
run() { [ "$VERBOSE" -eq 1 ] && printf '+ %s\n' "$*"; "$@"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --agents) [ $# -ge 2 ] || fail "--agents needs a value"; AGENTS="$2"; shift 2 ;;
    --all) AGENTS="all"; shift ;;
    --version) [ $# -ge 2 ] || fail "--version needs a value"; VERSION="$2"; shift 2 ;;
    --check) MODE="check"; shift ;;
    --upgrade) MODE="upgrade"; shift ;;
    --uninstall) MODE="uninstall"; shift ;;
    --prune) PRUNE=1; shift ;;
    --no-config) NO_CONFIG=1; shift ;;
    --project) PROJECT=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --verbose) VERBOSE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) fail "unknown option: $1" ;;
  esac
done

LUMINARY_HOME="$HOME/.luminary"
BIN_DIR="$LUMINARY_HOME/bin"
VENV="$LUMINARY_HOME/venvs/$VERSION"
PY="$VENV/bin/python"

select_agents() {
  case "$AGENTS" in
    all) echo "opencode pi omp" ;;
    auto)
      found=""
      if [ -d "$HOME/.config/opencode" ]; then found="$found opencode"; fi
      if [ -n "${LOCALAPPDATA:-}" ] && [ -d "$LOCALAPPDATA/Programs/ai.opencode.desktop" ]; then
        found="$found opencode"
      fi
      if [ -d "$HOME/.pi" ]; then found="$found pi"; fi
      if [ -d "$HOME/.omp" ]; then found="$found omp"; fi
      echo "$found" | tr ' ' '\n' | awk 'NF && !seen[$0]++' | tr '\n' ' '
      ;;
    *) echo "$AGENTS" | tr ',' ' ' ;;
  esac
}

# 1. A bridge interpreter. Status-only modes reuse an existing venv.
if [ "$MODE" = "check" ] || [ "$MODE" = "uninstall" ]; then
  if [ ! -x "$PY" ]; then
    for candidate in "$LUMINARY_HOME"/venvs/*/bin/python; do
      [ -x "$candidate" ] && PY="$candidate" && break
    done
  fi
  [ -x "$PY" ] || fail "no Luminary bridge found; run the installer without --check/--uninstall first"
fi

# 2. uv: a single static binary that can provision Python itself. Only needed
#    when the target interpreter does not exist yet.
if [ ! -x "$PY" ]; then
  if ! command -v uv >/dev/null 2>&1; then
    if [ ! -x "$BIN_DIR/uv" ]; then
      log "installing uv"
      mkdir -p "$BIN_DIR"
      curl -LsSf https://astral.sh/uv/install.sh |
        env UV_INSTALL_DIR="$BIN_DIR" UV_NO_MODIFY_PATH=1 sh >/dev/null
    fi
    PATH="$BIN_DIR:$PATH"
    export PATH
  fi
  log "python 3.12 -> $VENV"
  run uv venv "$VENV" --python 3.12
  log "bridge $VERSION"
  run uv pip install --python "$PY" "luminary-memory==$VERSION"
fi

# 3. Preferred path: the bridge ships the setup command.
set -- --agents "$AGENTS" --version "$VERSION"
[ "$NO_CONFIG" -eq 1 ] && set -- "$@" --no-config
[ "$PROJECT" -eq 1 ] && set -- "$@" --project
[ "$PRUNE" -eq 1 ] && set -- "$@" --prune
[ "$DRY_RUN" -eq 1 ] && set -- "$@" --dry-run
case "$MODE" in
  check) set -- "$@" --check ;;
  upgrade) set -- "$@" --upgrade ;;
  uninstall) set -- "$@" --uninstall ;;
esac

if "$PY" -m luminary_memory.integrations setup --list >/dev/null 2>&1; then
  run "$PY" -m luminary_memory.integrations setup "$@"
  exit $?
fi

# ------------------------------------------------------------------------
# Compatibility path for a published bridge that predates `setup`.
#
# It uses only commands and actions the older bridge already has:
#   - `luminary-memory.integrations install <agent> --global` writes a copy
#     adapter that embeds this interpreter, so no env var is required;
#   - the `core` action proves the bridge can read its store.
# Nothing is downloaded, so a stale remote copy cannot masquerade as success.
# ------------------------------------------------------------------------
SELECTED=$(select_agents)
[ -n "$SELECTED" ] || fail "no supported agent detected; use --agents opencode,pi,omp or --all"

if [ "$MODE" = "uninstall" ]; then
  rm -rf "$HOME/.config/opencode/plugins/luminary-memory"
  rm -rf "$HOME/.pi/agent/extensions/luminary-memory"
  rm -rf "$HOME/.omp/agent/extensions/luminary-memory"
  rm -f "$LUMINARY_HOME/bridge.json"
  log "removed Luminary adapters and bridge record"
  exit 0
fi

if [ "$MODE" = "check" ]; then
  "$PY" - <<'EOF'
import json, sys
from pathlib import Path
path = Path.home() / ".luminary" / "bridge.json"
if not path.exists():
    print("no bridge record; run the installer first")
    raise SystemExit(1)
data = json.loads(path.read_text(encoding="utf-8"))
agents = data.get("agents") or {}
if not agents:
    print("no agent recorded; run the installer first")
    raise SystemExit(1)
ok = True
for agent, entry in agents.items():
    python = Path(entry.get("python", ""))
    alive = python.is_file()
    ok = ok and alive
    print(f"{agent:<9} {'ok' if alive else 'missing':<9} bridge={entry.get('version', '-')}  python={python}")
raise SystemExit(0 if ok else 1)
EOF
  exit $?
fi

[ "$DRY_RUN" -eq 1 ] && { log "would install: $SELECTED"; exit 0; }

for agent in $SELECTED; do
  run "$PY" -m luminary_memory.integrations install "$agent" --global
done

"$PY" - "$PY" "$VERSION" "$SELECTED" <<'EOF'
import json, os, subprocess, sys
from pathlib import Path

python, version, selected = sys.argv[1], sys.argv[2], sys.argv[3].split()
home = Path.home() / ".luminary"
home.mkdir(parents=True, exist_ok=True)
data = {"schema": 1, "agents": {
    agent: {"python": python, "version": version, "mode": "copy"}
    for agent in selected
}}
(home / "bridge.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

failed = False
for agent in selected:
    request = {"agent": agent, "workspace": os.getcwd(), "session_id": "setup-check", "action": "core"}
    result = subprocess.run(
        [python, "-m", "luminary_memory.integrations", "bridge"],
        input=json.dumps(request).encode(), capture_output=True,
    )
    try:
        reply = json.loads(result.stdout.decode())
    except Exception:
        reply = {"ok": False, "message": result.stderr.decode()[:200]}
    ok = reply.get("ok") is True
    failed = failed or not ok
    detail = "" if ok else f"  {(reply.get('message') or reply.get('reason') or '')}"
    print(f"{agent:<9} {'ok' if ok else 'error':<9} bridge={version}{detail}")
raise SystemExit(1 if failed else 0)
EOF
