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
RAW="${LUMINARY_RAW:-https://raw.githubusercontent.com/alertxsto/luminary-memory}"

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

# 3. Everything that touches host config and the shared bridge record.
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

# A published bridge can predate the setup command. Fetch the compatibility
# setup from the matching release tag, then main, and only trust a copy that
# actually supports --list. A stale or truncated download must fail loudly
# instead of silently doing nothing.
SETUP="$LUMINARY_HOME/setup.py"
fetch_setup() {
  mkdir -p "$LUMINARY_HOME"
  for ref in "v$VERSION" main; do
    rm -f "$SETUP"
    curl -fsSL "$RAW/$ref/src/luminary_memory/integrations/setup.py" -o "$SETUP" 2>/dev/null || continue
    # A silent no-op also exits 0, so require real detection output.
    if [ -n "$("$PY" "$SETUP" --list 2>/dev/null)" ]; then
      return 0
    fi
  done
  rm -f "$SETUP"
  return 1
}
log "bridge predates setup; fetching compatibility setup"
fetch_setup || fail "cannot obtain a compatible setup for bridge $VERSION; install a release that ships the setup command"
run "$PY" "$SETUP" "$@"
