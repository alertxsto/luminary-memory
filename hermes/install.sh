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
RUNTIME_PY="$REPO_DIR/hermes/probes/runtime_python.py"
PROBE_PY="$REPO_DIR/hermes/probes/capability_probe.py"

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
  # Hermes does not run the bare interpreter: it activates a managed dependency
  # environment at launch, so a package installed into the base interpreter or
  # the user site is invisible to the host. Resolve the interpreter Hermes
  # actually runs with before touching pip.
  HERMES_RUNTIME_PYTHON="$("$LUMINARY_PYTHON" -I "$RUNTIME_PY" 2>/dev/null || true)"

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

  # Check capabilities, never a Hermes release number. This keeps an unsupported
  # host from silently falling back to native memory or leaving two persistent
  # stores active. The probe runs under the same -I isolation Hermes uses, so a
  # package that only landed in the user site cannot make it pass.
  if ! "$HERMES_RUNTIME_PYTHON" -I "$PROBE_PY"; then
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
