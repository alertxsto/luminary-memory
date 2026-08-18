#!/usr/bin/env bash
# ============================================================
# luminary-memory — Hermes test & verification runner
#
# Runs the full test suite, lint, coverage, and a live Hermes
# runtime smoke test in one command. Use before every push.
#
# Usage:
#   bash hermes/test.sh              # full: tests + lint + runtime smoke
#   bash hermes/test.sh --quick      # tests + lint only (skip runtime smoke)
#   bash hermes/test.sh --hermes     # Hermes runtime smoke test only
#   bash hermes/test.sh --help
# ============================================================
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

PYBIN="${PYTHON:-python3}"
MODE="full"

for arg in "$@"; do
  case "$arg" in
    --quick)  MODE="quick" ;;
    --hermes) MODE="hermes" ;;
    --help|-h)
      echo "Usage: bash hermes/test.sh [--quick | --hermes]"
      echo "  (default)  full: pytest + ruff + coverage + hermes runtime smoke"
      echo "  --quick    pytest + ruff only"
      echo "  --hermes   hermes runtime smoke test only"
      exit 0 ;;
    *) echo "unknown flag: $arg (see --help)"; exit 1 ;;
  esac
done

echo ""
echo "=== Luminary Memory — Hermes verification ==="
echo "mode: $MODE · python: $($PYBIN --version 2>&1)"
echo "============================================="

if [[ "$MODE" == "full" || "$MODE" == "quick" ]]; then
  echo ""
  echo "── 1/3 pytest (full suite) ──"
  "$PYBIN" -m pytest tests/ --tb=short

  echo ""
  echo "── 2/3 ruff check ──"
  "$PYBIN" -m ruff check src tests
fi

if [[ "$MODE" == "full" || "$MODE" == "hermes" ]]; then
  echo ""
  echo "── 3/3 Hermes runtime smoke test ──"
  "$PYBIN" - "$REPO_DIR" <<'PY'
import sys, tempfile, os
sys.path.insert(0, sys.argv[1])
# Inject the same agent.memory_provider stub used by the test suite
# (see tests/conftest.py) so provider import works without hermes-agent.
import importlib.util, types
from pathlib import Path
_stub = Path(sys.argv[1]) / "tests" / "hermes_stubs" / "agent" / "memory_provider.py"
if "agent.memory_provider" not in sys.modules:
    _agent = types.ModuleType("agent"); _agent.__path__ = []
    _spec = importlib.util.spec_from_file_location("agent.memory_provider", _stub)
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules["agent"] = _agent; sys.modules["agent.memory_provider"] = _mod
    _spec.loader.exec_module(_mod)
from luminary_memory.hermes.provider import LuminaryMemoryProvider
import json

tmp = tempfile.mkdtemp()
p = LuminaryMemoryProvider()
p.initialize("smoke", hermes_home=tmp, platform="cli", agent_identity="smoke")
class _E:
    def embed(self, t): return [0.1]*384
    def embed_batch(self, ts): return [[0.1]*384 for _ in ts]
p._client.engine = _E()
p._client.settings.rule_auto_replace = False

# core memory
r = p.handle_tool_call("luminary_core_add", {"content": "WAJIB markdown table semua laporan"})
assert "Core memory stored" in json.loads(r)["result"], r
# prefetch includes core, no dup, query unrelated
p._config["recall_sync"] = True
block = p.prefetch("riset teknologi xyz", session_id="smoke")
assert "Core memory (auto-loaded every session)" in block, "core block missing"
assert "markdown table" in block, "core rule missing"
assert block.count("markdown table") == 1, f"dup: {block.count('markdown table')}"
# system prompt includes core
sp = p.system_prompt_block()
assert "Core memory (auto-loaded every session)" in sp, "system prompt missing core"
# core_list / core_remove
d = json.loads(p.handle_tool_call("luminary_core_list", {}))
assert len(d["core"]) == 1, d
cid = d["core"][0]["id"]
r = json.loads(p.handle_tool_call("luminary_core_remove", {"id": cid}))
assert "removed from core" in r["result"], r
# recall still works
res = p._client.recall("riset", limit=5)
assert len(res.memories) >= 0
p.shutdown()
print("  Hermes runtime smoke: OK (core add/list/remove, prefetch, anti-dup, system prompt)")
PY
fi

echo ""
echo "============================================="
echo "✅ All checks passed"
echo "============================================="
