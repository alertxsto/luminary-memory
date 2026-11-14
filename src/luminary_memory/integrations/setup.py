"""One-command native adapter setup: bridge, config, and handshake.

The installer scripts only provision a Python runtime. Everything that touches
the host configuration, the shared bridge record, and the verification
handshake lives here so the same behaviour is testable without a shell.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from luminary_memory import __version__
from luminary_memory.integrations import AGENTS

PLUGIN_PREFIX = "luminary-memory-"
BRIDGE_SCHEMA = 1
MAX_HANDSHAKE_BYTES = 262144


@dataclass
class AgentReport:
    agent: str
    detected: bool
    config_root: Path
    pin: str | None = None
    bridge: str | None = None
    status: str = "pending"
    detail: str = ""
    handshake: dict = field(default_factory=dict)


def _home(home: Path | None) -> Path:
    return Path(home) if home is not None else Path.home()


def _luminary_home(home: Path) -> Path:
    return home / ".luminary"


def _bridge_file(home: Path) -> Path:
    return _luminary_home(home) / "bridge.json"


def _venv_root(home: Path) -> Path:
    return _luminary_home(home) / "venvs"


def _venv_python(home: Path, version: str) -> Path:
    root = _venv_root(home) / version
    return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def config_root(agent: str, home: Path, *, project: bool = False) -> Path:
    if project:
        return Path.cwd() / f".{agent}"
    if agent == "opencode":
        return Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config") / "opencode"
    return home / f".{agent}" / "agent"


def detect(agent: str, home: Path, *, project: bool = False) -> bool:
    if config_root(agent, home, project=project).exists():
        return True
    if shutil.which(agent):
        return True
    if agent == "opencode":
        local = os.environ.get("LOCALAPPDATA")
        if local and (Path(local) / "Programs" / "ai.opencode.desktop").exists():
            return True
    return False


def _strip_jsonc(text: str) -> str:
    """Remove comments and trailing commas without touching string contents."""
    out: list[str] = []
    index = 0
    in_string = False
    escaped = False
    while index < len(text):
        char = text[index]
        if in_string:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            out.append(char)
            index += 1
            continue
        if char == "/" and index + 1 < len(text):
            following = text[index + 1]
            if following == "/":
                index += 2
                while index < len(text) and text[index] not in "\r\n":
                    index += 1
                continue
            if following == "*":
                index += 2
                while index + 1 < len(text) and not (text[index] == "*" and text[index + 1] == "/"):
                    index += 1
                index += 2
                continue
        out.append(char)
        index += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def _opencode_config(root: Path) -> Path:
    for name in ("opencode.jsonc", "opencode.json"):
        candidate = root / name
        if candidate.exists():
            return candidate
    return root / "opencode.jsonc"


def _read_opencode(root: Path) -> tuple[Path, dict]:
    path = _opencode_config(root)
    if not path.exists():
        return path, {}
    data = json.loads(_strip_jsonc(path.read_text(encoding="utf-8-sig")))
    if not isinstance(data, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return path, data


def _plugin_pin(agent: str, root: Path) -> str | None:
    if agent != "opencode":
        return None
    try:
        _, data = _read_opencode(root)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    plugins = data.get("plugins")
    if not isinstance(plugins, list):
        return None
    for entry in plugins:
        if not isinstance(entry, str) or not entry.startswith(PLUGIN_PREFIX + agent):
            continue
        _, _, version = entry.partition("@")
        return version or None
    return None


def _patch_opencode(root: Path, version: str, *, dry_run: bool) -> Path:
    path, data = _read_opencode(root)
    plugins = data.get("plugins")
    if not isinstance(plugins, list):
        plugins = []
    plugins = [
        entry for entry in plugins
        if not (isinstance(entry, str) and entry.startswith(PLUGIN_PREFIX + "opencode"))
    ]
    plugins.append(f"{PLUGIN_PREFIX}opencode@{version}")
    data["plugins"] = plugins
    if not dry_run:
        if path.exists():
            backup = path.with_name(f"{path.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
            shutil.copy2(path, backup)
        from luminary_memory.integrations.cli import _atomic_write

        _atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return path


def _remove_opencode(root: Path, *, dry_run: bool) -> Path | None:
    path, data = _read_opencode(root)
    plugins = data.get("plugins")
    if not isinstance(plugins, list):
        return None
    kept = [
        entry for entry in plugins
        if not (isinstance(entry, str) and entry.startswith(PLUGIN_PREFIX + "opencode"))
    ]
    if kept == plugins:
        return None
    data["plugins"] = kept
    if not dry_run:
        from luminary_memory.integrations.cli import _atomic_write

        _atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return path


def _read_bridge(home: Path) -> dict:
    path = _bridge_file(home)
    if not path.exists():
        return {"schema": BRIDGE_SCHEMA, "agents": {}}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or not isinstance(data.get("agents"), dict):
        raise TypeError(f"{path} is not a Luminary bridge record")
    return data


def _write_bridge(home: Path, data: dict, *, dry_run: bool) -> Path:
    path = _bridge_file(home)
    if not dry_run:
        from luminary_memory.integrations.cli import _atomic_write

        _atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return path


def _ensure_model_cache(home: Path, *, dry_run: bool) -> Path:
    """Keep the embedding model out of the platform temp directory."""
    path = _luminary_home(home) / "luminary.env"
    line = f"LUMINARY_MODEL_CACHE={_luminary_home(home) / 'models'}"
    if path.exists():
        text = path.read_text(encoding="utf-8-sig")
        if "LUMINARY_MODEL_CACHE" in text:
            return path
        text = text.rstrip() + "\n" + line + "\n"
    else:
        text = line + "\n"
    if not dry_run:
        from luminary_memory.integrations.cli import _atomic_write

        _atomic_write(path, text)
    return path


def _probe_version(python: Path) -> str | None:
    try:
        result = subprocess.run(
            [str(python), "-c",
             "import importlib.metadata as m; print(m.version('luminary-memory'))"],
            check=False, capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _uv(home: Path) -> str | None:
    found = shutil.which("uv")
    if found:
        return found
    candidate = _luminary_home(home) / "bin" / ("uv.exe" if os.name == "nt" else "uv")
    return str(candidate) if candidate.exists() else None


def ensure_venv(version: str, home: Path, *, current: Path | None = None) -> Path:
    """Return an interpreter that imports *version*, creating a venv if needed."""
    if current is not None and _probe_version(current) == version:
        return Path(current)
    target = _venv_python(home, version)
    if target.exists() and _probe_version(target) == version:
        return target
    root = _venv_root(home) / version
    uv = _uv(home)
    if uv:
        subprocess.run([uv, "venv", str(root), "--python", "3.12"], check=True, timeout=300)
        subprocess.run(
            [uv, "pip", "install", "--python", str(target), f"luminary-memory=={version}"],
            check=True, timeout=900,
        )
    else:
        subprocess.run([sys.executable, "-m", "venv", str(root)], check=True, timeout=300)
        subprocess.run(
            [str(target), "-m", "pip", "install", f"luminary-memory=={version}"],
            check=True, timeout=900,
        )
    return target


def _bridge_call(python: Path, agent: str, workspace: Path, action: str) -> dict:
    request = {
        "agent": agent, "workspace": str(workspace),
        "session_id": "setup-check", "action": action,
    }
    try:
        result = subprocess.run(
            [str(python), "-m", "luminary_memory.integrations", "bridge"],
            check=False,
            input=json.dumps(request).encode("utf-8"),
            capture_output=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "status": "error", "reason": type(exc).__name__, "message": str(exc)}
    if result.returncode != 0:
        return {
            "ok": False, "status": "error", "reason": "bridge_exit",
            "message": result.stderr.decode("utf-8", "replace")[:300],
        }
    if len(result.stdout) > MAX_HANDSHAKE_BYTES:
        return {"ok": False, "status": "error", "reason": "output_limit", "message": ""}
    try:
        return json.loads(result.stdout.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {"ok": False, "status": "error", "reason": "invalid_json", "message": ""}


def handshake(python: Path, agent: str, workspace: Path) -> dict:
    version = _bridge_call(python, agent, workspace, "version")
    if version.get("ok"):
        core = _bridge_call(python, agent, workspace, "core")
        return {"version": version, "core": core, "legacy": False}
    # Published bridges before the version action still support core. A
    # working core load is a valid bridge, so probe it before failing an
    # install that would otherwise leave the host without memory.
    core = _bridge_call(python, agent, workspace, "core")
    if core.get("ok"):
        return {
            "version": {
                "ok": True, "status": "ok", "legacy": True,
                "version": _probe_version(python) or "",
            },
            "core": core,
            "legacy": True,
        }
    return {"version": version, "core": core, "legacy": False}


def _selected(agents: str, home: Path, *, project: bool) -> list[str]:
    if agents == "all":
        return list(AGENTS)
    if agents == "auto":
        return [agent for agent in AGENTS if detect(agent, home, project=project)]
    selected = [part.strip() for part in agents.split(",") if part.strip()]
    unknown = [agent for agent in selected if agent not in AGENTS]
    if unknown:
        raise ValueError(f"unknown agent(s): {', '.join(unknown)}")
    return selected


def _install_copy(agent: str, root: Path, python: Path, *, dry_run: bool) -> None:
    if dry_run:
        return
    from luminary_memory.integrations.cli import install_adapter

    try:
        install_adapter(agent, root, python=python)
    except TypeError:
        # Published bridges predate the explicit interpreter argument; they
        # embed the running interpreter, which is this venv.
        install_adapter(agent, root)


def _remove_copy(agent: str, root: Path, *, dry_run: bool) -> bool:
    folder = "plugins" if agent == "opencode" else "extensions"
    target = root / folder / "luminary-memory"
    if not target.exists():
        return False
    if not dry_run:
        shutil.rmtree(target)
    return True


def _prune(home: Path, bridge: dict, *, dry_run: bool) -> list[str]:
    referenced = {
        entry.get("version") for entry in bridge.get("agents", {}).values()
        if isinstance(entry, dict) and entry.get("version")
    }
    removed: list[str] = []
    root = _venv_root(home)
    if not root.exists():
        return removed
    for child in root.iterdir():
        if not child.is_dir() or child.name in referenced:
            continue
        removed.append(child.name)
        if not dry_run:
            shutil.rmtree(child)
    return removed


def run_setup(
    agents: str = "auto",
    *,
    version: str | None = None,
    project: bool = False,
    no_config: bool = False,
    check: bool = False,
    upgrade: bool = False,
    uninstall: bool = False,
    prune: bool = False,
    dry_run: bool = False,
    json_output: bool = False,
    list_only: bool = False,
    home: Path | None = None,
    python: Path | None = None,
) -> int:
    home = _home(home)
    if list_only:
        for agent in AGENTS:
            root = config_root(agent, home, project=project)
            state = "detected" if detect(agent, home, project=project) else "absent"
            print(f"{agent:<9} {state:<9} {root}")
        return 0
    selected = _selected(agents, home, project=project)
    if not selected:
        message = "No supported agent detected. Use --agents opencode,pi,omp or --all."
        if json_output:
            print(json.dumps({"ok": False, "error": message}))
        else:
            print(f"Luminary setup: {message}", file=sys.stderr)
        return 2
    bridge = _read_bridge(home)
    entries = bridge.setdefault("agents", {})
    reports: list[AgentReport] = []
    workspace = Path.cwd()
    exit_code = 0
    for agent in selected:
        root = config_root(agent, home, project=project)
        report = AgentReport(agent=agent, detected=detect(agent, home, project=project), config_root=root)
        report.pin = _plugin_pin(agent, root)
        existing = entries.get(agent) if isinstance(entries.get(agent), dict) else {}
        report.bridge = existing.get("version")
        if upgrade:
            target = version or __version__
        else:
            target = version or report.pin or report.bridge or __version__
        if uninstall:
            removed = False
            if agent == "opencode":
                removed = _remove_opencode(root, dry_run=dry_run) is not None
            else:
                removed = _remove_copy(agent, root, dry_run=dry_run)
            entries.pop(agent, None)
            report.status = "removed" if removed or existing else "absent"
            reports.append(report)
            continue
        if check:
            entry = entries.get(agent) if isinstance(entries.get(agent), dict) else {}
            interpreter = Path(str(entry.get("python", "")))
            if not report.bridge:
                report.status = "missing"
                exit_code = 1
            elif not interpreter.is_file():
                report.status = "missing"
                report.detail = f"interpreter not found: {interpreter}"
                exit_code = 1
            elif report.pin and report.pin != report.bridge:
                report.status = "drift"
                report.detail = f"pin {report.pin} != bridge {report.bridge}"
                exit_code = 1
            else:
                report.status = "ok"
            reports.append(report)
            continue
        if dry_run:
            report.status = "planned"
            report.bridge = target
            reports.append(report)
            continue
        try:
            interpreter = ensure_venv(target, home, current=python)
        except (OSError, subprocess.SubprocessError) as exc:
            report.status = "error"
            report.detail = f"bridge install failed: {exc}"
            exit_code = 1
            reports.append(report)
            continue
        # Verify before committing: a failed handshake must not leave a config
        # pin or bridge record pointing at an unusable interpreter.
        result = handshake(interpreter, agent, workspace)
        report.handshake = result
        if not result["version"].get("ok"):
            report.status = "error"
            report.detail = result["version"].get("message") or result["version"].get("reason", "")
            exit_code = 1
            reports.append(report)
            continue
        if not result["core"].get("ok"):
            report.status = "degraded"
            report.detail = result["core"].get("reason", "")
            exit_code = 1
            reports.append(report)
            continue
        report.bridge = target
        entries[agent] = {
            "python": str(interpreter), "version": target,
            "mode": "npm" if agent == "opencode" and not result.get("legacy") else "copy",
        }
        if not no_config:
            if agent == "opencode" and not result.get("legacy"):
                _patch_opencode(root, target, dry_run=dry_run)
            else:
                # A bridge without the version action predates the npm
                # resolver. Use the copy adapter, which embeds this
                # interpreter, and remove any npm pin that would double-load.
                if agent == "opencode":
                    _remove_opencode(root, dry_run=dry_run)
                _install_copy(agent, root, interpreter, dry_run=dry_run)
        report.status = "ok"
        if result.get("legacy"):
            report.detail = "copy adapter (bridge predates setup)"
        reports.append(report)
    if not check:
        _write_bridge(home, bridge, dry_run=dry_run)
        if not uninstall:
            _ensure_model_cache(home, dry_run=dry_run)
    pruned = _prune(home, bridge, dry_run=dry_run) if prune and not check else []
    if json_output:
        print(json.dumps({
            "ok": exit_code == 0,
            "bridge_file": str(_bridge_file(home)),
            "agents": [
                {
                    "agent": report.agent, "detected": report.detected,
                    "config_root": str(report.config_root), "pin": report.pin,
                    "bridge": report.bridge, "status": report.status,
                    "detail": report.detail,
                }
                for report in reports
            ],
            "pruned": pruned,
        }, indent=2))
    else:
        for report in reports:
            line = f"{report.agent:<9} {report.status:<9} bridge={report.bridge or '-':<8} pin={report.pin or '-'}"
            if report.detail:
                line += f"  {report.detail}"
            print(line)
        if pruned:
            print(f"pruned: {', '.join(pruned)}")
        if exit_code == 0 and not check and not uninstall and not dry_run:
            print("Restart the configured agent(s) to load the bridge.")
    return exit_code


def main(argv: list[str] | None = None) -> int:
    """Standalone entry point used when a published bridge predates `setup`."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="luminary-setup",
        description="Install or update the Luminary bridge and native agents.",
    )
    parser.add_argument("--agents", default="auto", help="auto | all | opencode,pi,omp")
    parser.add_argument("--version", default=None, help="bridge version to install")
    parser.add_argument("--project", action="store_true", help="target project-local config")
    parser.add_argument("--no-config", action="store_true", help="install the bridge only")
    parser.add_argument("--check", action="store_true", help="report status without changes")
    parser.add_argument("--upgrade", action="store_true", help="move plugin pins to the target")
    parser.add_argument("--uninstall", action="store_true", help="remove Luminary entries")
    parser.add_argument("--prune", action="store_true", help="remove unreferenced venvs")
    parser.add_argument("--dry-run", action="store_true", help="show actions without writing")
    parser.add_argument("--json", action="store_true", dest="json_output", help="JSON report")
    parser.add_argument("--list", action="store_true", dest="list_only", help="show detection")
    args = parser.parse_args(argv)
    return run_setup(
        args.agents, version=args.version, project=args.project,
        no_config=args.no_config, check=args.check, upgrade=args.upgrade,
        uninstall=args.uninstall, prune=args.prune, dry_run=args.dry_run,
        json_output=args.json_output, list_only=args.list_only,
        python=Path(sys.executable),
    )


if __name__ == "__main__":
    raise SystemExit(main())
