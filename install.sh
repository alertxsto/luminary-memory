#!/usr/bin/env sh
# Luminary Memory one-command installer for OpenCode, pi, and omp.
#
#   curl -fsSL https://raw.githubusercontent.com/alertxsto/luminary-memory/main/install.sh | sh
#
# Provision only the isolated bridge. Python setup owns host configuration,
# runtime verification and the per-agent bridge record.
set -eu

VERSION="${LUMINARY_VERSION:-0.3.4}"
AGENTS="auto"
MODE="sync"
NO_CONFIG=0
PROJECT=0
PRUNE=0
DRY_RUN=0
VERBOSE=0
LIST_ONLY=0
EXPLICIT_VERSION="${LUMINARY_VERSION:+1}"
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
  --list            detect supported agents without provisioning
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
    --version) [ $# -ge 2 ] || fail "--version needs a value"; VERSION="$2"; EXPLICIT_VERSION=1; shift 2 ;;
    --check|--upgrade|--uninstall)
      [ "$MODE" = sync ] || fail "choose only one of --check, --upgrade, --uninstall"
      MODE="${1#--}"; shift ;;
    --prune) PRUNE=1; shift ;;
    --no-config) NO_CONFIG=1; shift ;;
    --project) PROJECT=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --verbose) VERBOSE=1; shift ;;
    --list) LIST_ONLY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) fail "unknown option: $1" ;;
  esac
done

# Validate before downloads, directory creation, or interpreter execution.
printf '%s\n' "$VERSION" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' ||
  fail "version must have the form X.Y.Z"
case "$AGENTS" in
  auto|all) ;;
  ""|,*|*,|*,,*) fail "agent selection must be opencode,pi,omp" ;;
  *)
    for agent in $(printf '%s' "$AGENTS" | tr ',' ' '); do
      case "$agent" in opencode|pi|omp) ;; *) fail "unknown agent: $agent" ;; esac
    done ;;
esac

LUMINARY_HOME="$HOME/.luminary"
BIN_DIR="$LUMINARY_HOME/bin"
VENV="$LUMINARY_HOME/venvs/$VERSION"
PY="$VENV/bin/python"
LOCK_DIR="$LUMINARY_HOME/locks/bootstrap.lock.d"
release_lock() { rm -rf "$LOCK_DIR"; }
acquire_lock() {
  mkdir -p "$LUMINARY_HOME/locks"
  waited=0
  while ! mkdir "$LOCK_DIR" 2>/dev/null; do
    owner=$(cat "$LOCK_DIR/pid" 2>/dev/null || true)
    if [ -n "$owner" ] && ! kill -0 "$owner" 2>/dev/null; then
      rm -rf "$LOCK_DIR"
      continue
    fi
    [ "$waited" -ge 1200 ] && fail "another Luminary bootstrap is running; retry after it finishes"
    sleep 0.1
    waited=$((waited + 1))
  done
  printf '%s\n' "$$" > "$LOCK_DIR/pid"
  trap 'release_lock' EXIT HUP INT TERM
}
SELECTED="$AGENTS"
if [ "$AGENTS" = auto ]; then
  SELECTED=""
  for agent in opencode pi omp; do
    root="$HOME/.$agent/agent"
    [ "$PROJECT" -eq 1 ] && root="$PWD/.$agent"
    if [ "$agent" = opencode ] && [ "$PROJECT" -eq 0 ]; then
      root="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
    fi
    if [ -d "$root" ] || command -v "$agent" >/dev/null 2>&1; then
      SELECTED="$SELECTED $agent"
    fi
  done
fi
if [ "$LIST_ONLY" -eq 1 ]; then
  log "detected agents: ${SELECTED:-none}"
  exit 0
fi
[ -n "$SELECTED" ] || fail "no supported agent detected; use --agents opencode,pi,omp"
if [ "$PROJECT" -eq 1 ] && [ "$NO_CONFIG" -eq 0 ] && [ "$MODE" != check ] && [ "$MODE" != uninstall ] && [ "$DRY_RUN" -eq 0 ]; then
  case ",$(printf '%s' "$SELECTED" | tr ' ' ',')," in
    *,omp,*|*,all,*) fail "omp native packages are user-wide; use explicit project copy installation instead" ;;
  esac
fi
set -- --agents "$AGENTS"
[ -n "$EXPLICIT_VERSION" ] && set -- "$@" --version "$VERSION"
[ "$NO_CONFIG" -eq 1 ] && set -- "$@" --no-config
[ "$PROJECT" -eq 1 ] && set -- "$@" --project
[ "$PRUNE" -eq 1 ] && set -- "$@" --prune
[ "$DRY_RUN" -eq 1 ] && set -- "$@" --dry-run
case "$MODE" in
  check) set -- "$@" --check ;;
  upgrade) set -- "$@" --upgrade ;;
  uninstall) set -- "$@" --uninstall ;;
esac

# No read-only path bootstraps uv, Python, packages, or memory stores.
if [ -n "${LUMINARY_PYTHON:-}" ]; then
  PY="$LUMINARY_PYTHON"
  "$PY" -I -c 'from luminary_memory.integrations.setup import run_setup' ||
    fail "invalid LUMINARY_PYTHON; fix or unset the explicit override"
elif [ "$MODE" = check ] || [ "$MODE" = uninstall ] || [ "$DRY_RUN" -eq 1 ]; then
  if [ ! -x "$PY" ]; then
    for candidate in "$LUMINARY_HOME"/venvs/*/bin/python; do
      [ -x "$candidate" ] && PY="$candidate" && break
    done
  fi
  if [ ! -x "$PY" ]; then
    [ "$DRY_RUN" -eq 1 ] && { log "planned bridge $VERSION for $SELECTED (no provisioning)"; exit 0; }
    fail "no Luminary bridge found; run setup with a setup-capable release first"
  fi
else
  unset PYTHONHOME PYTHONPATH VIRTUAL_ENV CONDA_PREFIX
  acquire_lock
  # Recheck readiness under the lock: a concurrent bootstrap may have finished.
  if ! "$PY" -I -c "import importlib.metadata as m; from luminary_memory.integrations.setup import run_setup; assert m.version('luminary-memory') == '$VERSION'" >/dev/null 2>&1; then
    if command -v uv >/dev/null 2>&1; then
      UV=$(command -v uv)
    else
      UV="$BIN_DIR/uv"
      if [ ! -x "$UV" ]; then
        mkdir -p "$BIN_DIR"
        script=$(mktemp)
        trap 'rm -f "$script"; release_lock' EXIT HUP INT TERM
        curl -LsSf https://astral.sh/uv/install.sh -o "$script"
        env UV_INSTALL_DIR="$BIN_DIR" UV_NO_MODIFY_PATH=1 sh "$script"
        rm -f "$script"
        trap 'release_lock' EXIT HUP INT TERM
      fi
    fi
    [ -x "$PY" ] || run "$UV" venv "$VENV" --python 3.12
    run "$UV" pip install --python "$PY" --reinstall "luminary-memory==$VERSION"
  fi
fi
"$PY" -I -c 'from luminary_memory.integrations.setup import run_setup' ||
  fail "release $VERSION predates managed setup; choose a setup-capable release; host configuration was not changed"
run "$PY" -I -m luminary_memory.integrations setup "$@"
release_lock
trap - EXIT HUP INT TERM
