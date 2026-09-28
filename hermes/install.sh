#!/usr/bin/env bash
# ============================================================
# luminary-memory — Hermes one-shot installer
#
# Installs everything needed to use luminary-memory as a Hermes
# memory provider, plus the optional chat-activity hook and skill.
#
#   - install luminary-memory[hermes] into the Hermes interpreter
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
  # Read the minimum from this checkout, not a hard-coded installer constant.
  # Use the same interpreter as Hermes for pip, metadata, and activation.
  REQUIRED_VERSION="$("$LUMINARY_PYTHON" - "$REPO_DIR/pyproject.toml" <<'PY'
import sys
import tomllib

with open(sys.argv[1], "rb") as project:
    print(tomllib.load(project)["project"]["version"])
PY
)" || fail "could not read checkout version"
  log "installing luminary-memory[hermes]>=0.3.0 (checkout minimum $REQUIRED_VERSION) ..."
  "$LUMINARY_PYTHON" -m pip install -q --upgrade \
    "luminary-memory[hermes]>=$REQUIRED_VERSION" || fail "pip install failed"

  # Verify what THIS Hermes interpreter actually imports before touching its
  # configuration. Metadata alone can describe a stale/broken entry point.
  if ! "$LUMINARY_PYTHON" - "$REQUIRED_VERSION" <<'PY'
import re
import sys
from importlib import metadata

minimum = sys.argv[1]
if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", minimum):
    raise SystemExit(f"invalid checkout version: {minimum!r}")
installed = metadata.distribution("luminary-memory")
version = installed.version
if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
    raise SystemExit(f"invalid installed distribution version: {version!r}")
if tuple(map(int, version.split("."))) < tuple(map(int, minimum.split("."))):
    raise SystemExit(f"stale luminary-memory {version}; checkout requires >= {minimum}")

import luminary_memory

if luminary_memory.__version__ != version:
    raise SystemExit(
        f"interpreter imports luminary-memory {luminary_memory.__version__}, "
        f"but installed distribution metadata says {version}"
    )

from agent.memory_provider import MemoryProvider

required = ("name", "is_available", "initialize", "get_tool_schemas", "replaces_builtin_memory")
missing = [name for name in required if not hasattr(MemoryProvider, name)]
if missing:
    raise SystemExit("Hermes public MemoryProvider contract is missing: " + ", ".join(missing))

entry_points = [
    entry for entry in installed.entry_points
    if entry.group == "hermes_agent.memory_providers" and entry.name == "luminary"
]
if len(entry_points) != 1:
    raise SystemExit(f"expected one luminary entry point in installed distribution, found {len(entry_points)}")
provider_module = entry_points[0].load()
provider_type = provider_module.LuminaryMemoryProvider
if not issubclass(provider_type, MemoryProvider):
    raise SystemExit("installed Luminary provider does not implement the Hermes contract")
if provider_type().name != "luminary":
    raise SystemExit("installed Luminary provider name is not luminary")
PY
  then
    fail "installed Luminary distribution or Hermes provider contract is invalid; config unchanged"
  fi

  CONFIG="$HERMES_HOME/config.yaml"
  log "activating Luminary through Hermes config.yaml ..."
  "$LUMINARY_PYTHON" -m luminary_memory.hermes.activation --all-profiles "$CONFIG" || fail "could not update Hermes memory configs"
fi
fi

# ------------------------------------------------------------------ #
# 2. LLM memory curation (optional — drops chit-chat, stores facts)
# ------------------------------------------------------------------ #
if [ "$DO_LLM" -eq 1 ]; then
  log "enabling LLM memory curation (ingest_llm) ..."
  LUM_CONFIG="$HERMES_HOME/luminary/config.json"
  mkdir -p "$HERMES_HOME/luminary"
  if [ ! -f "$LUM_CONFIG" ]; then
    printf '{\n  "ingest_llm": true,\n  "llm_base_url": "",\n  "llm_model": "",\n  "llm_api_key": ""\n}\n' > "$LUM_CONFIG"
    chmod 600 "$LUM_CONFIG"
    log "config created at $LUM_CONFIG — set llm_base_url / llm_model / llm_api_key"
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
# 3. Skill
# ------------------------------------------------------------------ #
if [ "$DO_SKILL" -eq 1 ]; then
  log "installing luminary-memory skill ..."
  mkdir -p "$HERMES_HOME/skills/luminary-memory"
  cp "$SKILL_SRC" "$HERMES_HOME/skills/luminary-memory/SKILL.md"
  log "skill installed to $HERMES_HOME/skills/luminary-memory/"
fi

log "done. Restart your Hermes gateway (e.g. bash $HERMES_HOME/scripts/restart-bots.sh) to pick up config + hook."
