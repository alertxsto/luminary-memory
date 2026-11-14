#!/usr/bin/env bash
# ============================================================
# luminary-memory — Hermes one-shot installer
#
# Installs everything needed to use luminary-memory as a Hermes
# memory provider, plus the optional chat-activity hook and skill.
#
#   - install luminary-memory[hermes] into the environment Hermes runs
#   - enables memory.provider = luminary and disables the two native memory
#     surfaces in Hermes config, so there is one persistent authority
#   - installs the luminary-activity hook
#   - installs the luminary-memory skill
#
# Usage:
#   bash hermes/install.sh          # full install
#   bash hermes/install.sh --hook   # hook only
#   bash hermes/install.sh --skill  # skill only
#   bash hermes/install.sh --no-hook --no-skill  # provider only
# ============================================================
set -euo pipefail

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
LUMINARY_PYTHON="${HERMES_PYTHON:-python3}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL_SRC="$REPO_DIR/hermes/SKILL.md"
HOOK_SRC="$REPO_DIR/hermes/hooks/luminary-activity"
HOOK_DST="$HERMES_HOME/hooks/luminary-activity"

DO_PROVIDER=1
DO_HOOK=1
DO_SKILL=1
DO_LLM=0

for arg in "$@"; do
  case "$arg" in
    --hook) DO_PROVIDER=0; DO_SKILL=0 ;;
    --skill) DO_PROVIDER=0; DO_HOOK=0 ;;
    --llm) DO_LLM=1 ;;
    --no-hook) DO_HOOK=0 ;;
    --no-skill) DO_SKILL=0 ;;
    *) echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done

log()  { printf '\033[1;36m[luminary]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[luminary]\033[0m ERROR: %s\n' "$*" >&2; exit 1; }

# ------------------------------------------------------------------ #
# 1. Python package (provider + entry point)
# ------------------------------------------------------------------ #
if [ "$DO_PROVIDER" -eq 1 ]; then
  # Hermes does not run the bare interpreter. At launch it activates a managed
  # dependency environment and imports the ``agent`` package from its own
  # checkout, so a package installed into the base interpreter or the user site
  # is invisible to the host. Resolve the interpreter Hermes actually runs with
  # before touching pip.
  HERMES_RUNTIME_PYTHON="$("$LUMINARY_PYTHON" -I - <<'PY' 2>/dev/null || true
import os
import site
import sys
from pathlib import Path


def _roots():
    """Yield directories that may hold the Hermes bootstrap module."""
    home = os.environ.get("HERMES_HOME")
    if home:
        yield Path(home) / "hermes-agent"
        yield Path(home)
    names = ("hermes.exe",) if os.name == "nt" else ("hermes",)
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not os.path.isabs(entry):
            continue
        for name in names:
            exe = Path(entry) / name
            if not exe.is_file():
                continue
            for parent in exe.resolve().parents:
                if (parent / "hermes_bootstrap.py").is_file():
                    yield parent
                    break


def _runtime_python():
    base = Path(sys.base_prefix).resolve()
    try:
        user = Path(site.getusersitepackages()).resolve()
    except Exception:
        user = None
    for root in _roots():
        if not (root / "hermes_bootstrap.py").is_file():
            continue
        sys.path.insert(0, str(root))
        try:
            import hermes_bootstrap  # noqa: F401
        except Exception:
            sys.path.remove(str(root))
            continue
        for entry in sys.path:
            if not entry or not entry.endswith("site-packages"):
                continue
            path = Path(entry).resolve()
            if path.is_relative_to(base):
                continue
            if user is not None and path == user:
                continue
            for parent in path.parents:
                if not (parent / "pyvenv.cfg").is_file():
                    continue
                candidate = parent / (
                    "Scripts/python.exe" if os.name == "nt" else "bin/python"
                )
                if candidate.exists():
                    return candidate
                break
    return None


found = _runtime_python()
if found is not None:
    print(found)
PY
)"

  if [ -z "$HERMES_RUNTIME_PYTHON" ]; then
    HERMES_RUNTIME_PYTHON="$LUMINARY_PYTHON"
    log "could not resolve the Hermes runtime environment; using $LUMINARY_PYTHON"
  else
    log "Hermes runtime interpreter: $HERMES_RUNTIME_PYTHON"
  fi

  log "installing luminary-memory[hermes] ..."
  # ``pip --python`` targets the resolved environment even when it has no pip of
  # its own, which is the normal shape of a Hermes managed environment.
  if ! "$LUMINARY_PYTHON" -m pip --python "$HERMES_RUNTIME_PYTHON" install -q \
      "luminary-memory[hermes]"; then
    "$HERMES_RUNTIME_PYTHON" -m pip install -q "luminary-memory[hermes]" \
      || fail "pip install failed"
  fi

  # Check capabilities, never a Hermes release number.  This keeps an
  # unsupported host from silently falling back to native memory or leaving
  # two persistent stores active.
  #
  # Two host layouts have to work here:
  #
  #   * pip-installed Hermes: ``agent`` is already importable.
  #   * git-checkout Hermes: ``agent`` lives in the checkout and is only on
  #     ``sys.path`` because the ``hermes`` launcher inserts it.  A bare
  #     interpreter cannot import it, so the checkout is discovered and
  #     inserted here instead of assuming a pip install.
  #
  # The probe runs with -I to match the isolation Hermes itself uses, so a
  # package that only landed in the user site cannot pass this check.
  if ! "$HERMES_RUNTIME_PYTHON" -I - <<'PY'
import json
import os
import subprocess
import sys
from importlib import metadata
from pathlib import Path

REQUIRED = ("name", "is_available", "initialize", "get_tool_schemas")


def _candidate_roots():
    """Yield directories that may hold the Hermes ``agent`` package."""
    seen = set()

    def fresh(value):
        if not value:
            return None
        try:
            resolved = Path(value).expanduser().resolve()
        except OSError:
            return None
        if resolved.is_dir() and str(resolved) not in seen:
            seen.add(str(resolved))
            return resolved
        return None

    home = os.environ.get("HERMES_HOME")
    if home:
        for candidate in (Path(home) / "hermes-agent", Path(home)):
            root = fresh(candidate)
            if root:
                yield root

    # The launcher knows which checkout it runs from; ask it instead of guessing.
    launcher = os.environ.get("HERMES_BIN") or "hermes"
    try:
        done = subprocess.run(
            [launcher, "--print-runtime-command"],
            capture_output=True,
            text=True,
            timeout=60,
            stdin=subprocess.DEVNULL,
        )
        if done.returncode == 0:
            for part in json.loads(done.stdout):
                if isinstance(part, str) and "sys.path.insert" in part:
                    for token in part.split("'"):
                        root = fresh(token)
                        if root:
                            yield root
    except (OSError, ValueError, subprocess.SubprocessError):
        pass

    # Last resort: walk up from the launcher on PATH looking for the package.
    names = ("hermes.exe",) if os.name == "nt" else ("hermes",)
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not os.path.isabs(entry):
            continue
        for name in names:
            exe = Path(entry) / name
            if not exe.is_file():
                continue
            for parent in exe.resolve().parents:
                if (parent / "agent" / "memory_provider.py").is_file():
                    root = fresh(parent)
                    if root:
                        yield root
                    break


def _load_contract():
    try:
        from agent.memory_provider import MemoryProvider

        return MemoryProvider
    except ImportError:
        pass
    for root in _candidate_roots():
        if not (root / "agent" / "memory_provider.py").is_file():
            continue
        sys.path.insert(0, str(root))
        try:
            from agent.memory_provider import MemoryProvider

            return MemoryProvider
        except ImportError:
            sys.path.remove(str(root))
    return None


MemoryProvider = _load_contract()
if MemoryProvider is None:
    raise SystemExit(
        "the Hermes agent package is not importable. Install Hermes with pip, or "
        "set HERMES_HOME to the directory that contains the Hermes checkout."
    )

missing = [name for name in REQUIRED if not hasattr(MemoryProvider, name)]
if missing:
    raise SystemExit(
        "Hermes public MemoryProvider contract is missing: " + ", ".join(missing)
    )

entry_points = metadata.entry_points()
if hasattr(entry_points, "select"):
    installed = {entry.name for entry in entry_points.select(group="hermes_agent.memory_providers")}
else:
    installed = {
        entry.name
        for entry in entry_points
        if getattr(entry, "group", "") == "hermes_agent.memory_providers"
    }
if "luminary" not in installed:
    raise SystemExit(
        "Luminary entry point is not visible to the Hermes runtime interpreter. "
        "Hermes runs with -I, so a --user install is not enough; install into the "
        "environment that runs Hermes."
    )
PY
  then
    fail "Hermes does not expose the public memory-provider capabilities required by Luminary"
  fi

  CONFIG="$HERMES_HOME/config.yaml"
  log "activating Luminary through Hermes config.yaml ..."
  "$HERMES_RUNTIME_PYTHON" -m luminary_memory.hermes.activation "$CONFIG" \
    || fail "could not update selected Hermes memory config"
fi

# ------------------------------------------------------------------ #
# 2. LLM memory curation (optional — drops chit-chat, stores facts)
# ------------------------------------------------------------------ #
if [ "$DO_LLM" -eq 1 ]; then
  log "enabling LLM memory curation (ingest_llm) ..."
  LUM_CONFIG="$HERMES_HOME/luminary/config.json"
  mkdir -p "$HERMES_HOME/luminary"
  if [ ! -f "$LUM_CONFIG" ]; then
    printf '{\n  "ingest_llm": true,\n  "llm_base_url": "",\n  "llm_model": ""\n}\n' > "$LUM_CONFIG"
    chmod 600 "$LUM_CONFIG"
    log "config created at $LUM_CONFIG — set llm_base_url / llm_model; configure LUMINARY_LLM_API_KEY in Hermes secrets"
  else
    log "config exists — edit $LUM_CONFIG to set ingest_llm + llm_*"
  fi
fi

# ------------------------------------------------------------------ #
# 3. Activity hook
# ------------------------------------------------------------------ #
if [ "$DO_HOOK" -eq 1 ]; then
  log "installing luminary-activity hook ..."
  mkdir -p "$HOOK_DST"
  cp "$HOOK_SRC/handler.py" "$HOOK_DST/"
  cp "$HOOK_SRC/HOOK.yaml" "$HOOK_DST/"
  chmod +x "$HOOK_DST/handler.py"
  log "hook installed to $HOOK_DST"
  if [ -f "$HERMES_HOME/.env" ] && grep -q "LUMINARY_HOOK_CHAT_ID" "$HERMES_HOME/.env"; then
    log "LUMINARY_HOOK_CHAT_ID already set — skipping"
  else
    echo "# Optional: chat where luminary activity is posted (defaults to TELEGRAM_HOME_CHANNEL)" >> "$HERMES_HOME/.env"
    log "NOTE: set LUMINARY_HOOK_CHAT_ID in $HERMES_HOME/.env to choose the activity chat"
  fi
fi

# ------------------------------------------------------------------ #
# 4. Skill
# ------------------------------------------------------------------ #
if [ "$DO_SKILL" -eq 1 ]; then
  log "installing luminary-memory skill ..."
  mkdir -p "$HERMES_HOME/skills/luminary-memory"
  cp "$SKILL_SRC" "$HERMES_HOME/skills/luminary-memory/SKILL.md"
  log "skill installed to $HERMES_HOME/skills/luminary-memory/"
fi

log "done. Restart your Hermes gateway (e.g. bash $HERMES_HOME/scripts/restart-bots.sh) to pick up config + hook."
