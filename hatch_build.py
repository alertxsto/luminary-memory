"""Include built native resources, failing closed rather than publishing a broken UI."""
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        # Core-engine editable development does not require Node or UI assets.
        # UI installers separately reject absent compiled resources.
        if version == "editable":
            return
        package = "src/luminary_memory"
        compiled = f"{package}/integrations/assets/compiled"
        browser = f"{package}/inspector/assets/browser"
        required = [
            f"{compiled}/pi/index.js", f"{compiled}/omp/index.js",
            *[f"{compiled}/opencode/{name}" for name in (
                "index.js", "rpc.js", "tui.js", "gui-experimental.cjs",
            )],
            *[f"{compiled}/hermes/{name}" for name in (
                "__init__.py", "plugin.yaml", "desktop/plugin.js",
                "dashboard/manifest.json", "dashboard/plugin_api.py", "dashboard/dist/index.js",
            )],
            *[f"{browser}/{name}" for name in ("index.html", "style.css", "app.js")],
        ]
        missing = [name for name in required if not (Path(self.root) / name).is_file()]
        if missing:
            raise RuntimeError("Incomplete native/UI resources; run npm ci && npm run build first. Missing: " + ", ".join(missing))
        # Include required runtime files despite VCS ignores, not generated
        # Python caches or other incidental files beneath these directories.
        build_data["artifacts"].extend(f"/{name}" for name in required)
