import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_opencode_python_exports_import_without_hermes():
    code = """
import sys

class BlockHermes:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "hermes_agent" or fullname.startswith("luminary_memory.hermes"):
            raise ModuleNotFoundError("Hermes intentionally unavailable")
        return None

sys.meta_path.insert(0, BlockHermes())
from luminary_memory.opencode import ProtocolValidationError, Request, Response, Scope, main, run_jsonl
assert all((ProtocolValidationError, Request, Response, Scope, main, run_jsonl))
"""
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True)


def test_python_entry_point_targets_public_sidecar_main():
    pyproject = (ROOT / "pyproject.toml").read_text()

    assert 'luminary-memory-opencode = "luminary_memory.opencode.sidecar:main"' in pyproject


def test_npm_package_declares_compiled_plugin_and_skill_contents():
    package = json.loads((ROOT / "opencode/package.json").read_text())

    assert package["main"] == "./dist/plugin.js"
    assert package["exports"]["."] == "./dist/plugin.js"
    assert "dist" in package["files"]
    assert "skills/luminary-memory/SKILL.md" in package["files"]
    assert "build" in package["scripts"]
    assert "pack:check" in package["scripts"]
    assert (ROOT / "opencode/skills/luminary-memory/SKILL.md").is_file()


def test_open_code_docs_cover_install_runtime_scope_failure_and_write_policy():
    docs = "\n".join(
        (
            (ROOT / "opencode/README.md").read_text(),
            (ROOT / "docs/opencode-integration.md").read_text(),
        )
    )

    for expected in (
        "Python 3.11",
        "opencode plug",
        "python -m luminary_memory.opencode.sidecar",
        "SQLite",
        "health",
        "graceful",
        "workspace_id",
        "Only the explicit `luminary_ingest` tool writes durable memory",
        "@opencode-ai/plugin",
        "## Architecture",
    ):
        assert expected in docs
