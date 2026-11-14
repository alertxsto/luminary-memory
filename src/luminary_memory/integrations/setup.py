"""One-command native adapter setup: bridge, config, and handshake.

The installer scripts only provision a Python runtime. Everything that touches
the host configuration, the shared bridge record, and the verification
handshake lives here so the same behaviour is testable without a shell.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
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
    return re.sub(
        r'"(?:\\.|[^"\\])*"|,(\s*[}\]])',
        lambda match: match.group(1) if match.group(1) is not None else match.group(0),
        "".join(out),
    )


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


def _is_native(value: object, agent: str) -> bool:
    if isinstance(value, dict):
        value = value.get("source")
    if not isinstance(value, str):
        return False
    value = value.removeprefix("npm:")
    name = PLUGIN_PREFIX + agent
    return value == name or value.startswith(name + "@")


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def _plugin_pin(agent: str, root: Path) -> str | None:
    if agent == "opencode":
        _, data = _read_opencode(root)
        values = data.get("plugins", [])
    elif agent == "pi":
        values = _read_json(root / "settings.json").get("packages", [])
    else:
        value = _read_json(root.parent / "plugins" / "package.json").get("dependencies", {}).get(PLUGIN_PREFIX + agent)
        return value if isinstance(value, str) else None
    if not isinstance(values, list):
        raise TypeError(f"{agent} package registrations must be a list")
    pins = []
    for value in values:
        if _is_native(value, agent):
            source = value.get("source") if isinstance(value, dict) else value
            pins.append(source.partition("@")[2] or "")
    if len(pins) > 1:
        raise ValueError(f"Multiple native {agent} registrations; resolve the conflict before setup")
    return pins[0] if pins else None


def _native_registered(agent: str, root: Path, version: str) -> bool:
    if _plugin_pin(agent, root) != version:
        return False
    if agent == "opencode":
        return True  # The supported host config is the registration surface.
    package = (root / "npm" if agent == "pi" else root.parent / "plugins") / "node_modules" / (PLUGIN_PREFIX + agent)
    manifest = _read_json(package / "package.json")
    if manifest.get("name") != PLUGIN_PREFIX + agent or manifest.get("version") != version:
        return False
    if agent == "omp":
        state = _read_json(root.parent / "plugins" / "omp-plugins.lock.json")
        if state.get("plugins", {}).get(PLUGIN_PREFIX + agent, {}).get("enabled") is not True:
            return False
    return True


def _host_command(agent: str, args: list[str], home: Path) -> None:
    executable = shutil.which(agent)
    if not executable:
        raise RuntimeError(f"{agent} CLI not found; install the host first")
    environment = dict(os.environ, HOME=str(home), USERPROFILE=str(home),
                       PI_CODING_AGENT_DIR=str(config_root(agent, home)))
    # A named omp profile is a different installation target, not a user-default.
    environment.pop("OMP_PROFILE", None)
    subprocess.run([executable, *args], check=True, timeout=900, env=environment)


def _native_install(agent: str, root: Path, home: Path, version: str, *, project: bool) -> None:
    if agent == "opencode":
        _patch_opencode(root, version, dry_run=False)
    elif not _native_registered(agent, root, version):
        if agent == "pi":
            _host_command(agent, ["install", f"npm:{PLUGIN_PREFIX}{agent}@{version}", *(["--local"] if project else [])], home)
        else:
            _host_command(agent, ["plugin", "install", f"{PLUGIN_PREFIX}{agent}@{version}"], home)
    if not _native_registered(agent, root, version):
        raise RuntimeError(f"{agent} did not register the requested native package {version}")


def _native_remove(agent: str, root: Path, home: Path, *, project: bool, dry_run: bool) -> bool:
    pin = _plugin_pin(agent, root)
    if pin is None:
        return False
    if not dry_run:
        if agent == "opencode":
            _remove_opencode(root, dry_run=False)
        elif agent == "pi":
            _host_command(agent, ["remove", f"npm:{PLUGIN_PREFIX}{agent}", *(["--local"] if project else [])], home)
        else:
            _host_command(agent, ["plugin", "uninstall", PLUGIN_PREFIX + agent], home)
        if _plugin_pin(agent, root) is not None:
            raise RuntimeError(f"{agent} still registers Luminary after removal")
    return True


def _patch_opencode(root: Path, version: str, *, dry_run: bool) -> Path:
    path, data = _read_opencode(root)
    plugins = data.get("plugins")
    if not isinstance(plugins, list):
        plugins = []
    plugins = [
        entry for entry in plugins
        if not _is_native(entry, "opencode")
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
        if not _is_native(entry, "opencode")
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
    """Import and probe capabilities without constructing a client or opening a DB."""
    script = (
        "import importlib.metadata as m; "
        "from luminary_memory.integrations import dispatch; "
        "from luminary_memory.integrations.setup import run_setup; "
        "v=m.version('luminary-memory'); "
        "r=dispatch({'agent':'pi','action':'version'}); "
        "assert r.get('ok') is True and r.get('version')==v and 'core' in r.get('actions',[]); "
        "print(v)"
    )
    try:
        result = subprocess.run(
            [str(python), "-I", "-c", script],
            check=False, capture_output=True, text=True, timeout=30,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


@contextlib.contextmanager
def _lock(home: Path, name: str):
    """An OS-owned lock survives process interruption without a stale PID lease."""
    path = _luminary_home(home) / "locks" / f"{name}.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.write(b"\0")
        handle.flush()
        deadline = time.monotonic() + 120
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Another setup owns {path}; try again after it finishes") from None
                time.sleep(0.1)
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def _uv(home: Path) -> str | None:
    found = shutil.which("uv")
    if found:
        return found
    candidate = _luminary_home(home) / "bin" / ("uv.exe" if os.name == "nt" else "uv")
    return str(candidate) if candidate.exists() else None


def ensure_venv(version: str, home: Path, *, current: Path | None = None) -> Path:
    """Reuse a verified interpreter, repairing only a private managed environment."""
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("version must have the form X.Y.Z")
    if current is not None and _probe_version(current) == version:
        return Path(current)
    target = _venv_python(home, version)
    with _lock(home, f"runtime-{version}"):
        if target.is_file() and _probe_version(target) == version:
            return target
        uv = _uv(home)
        if not uv:
            raise RuntimeError("uv not found; run the platform installer to provision the managed runtime")
        if not target.is_file():
            subprocess.run(
                [uv, "venv", str(target.parent.parent), "--python", "3.12"],
                check=True, timeout=300,
            )
        subprocess.run(
            [uv, "pip", "install", "--python", str(target), "--reinstall", f"luminary-memory=={version}"],
            check=True, timeout=900,
        )
        if _probe_version(target) != version:
            raise RuntimeError(f"Managed bridge {version} failed its version/capability probe; rerun setup to repair")
        return target


def _bridge_call(python: Path, agent: str, workspace: Path, action: str) -> dict:
    request = {
        "agent": agent, "workspace": str(workspace),
        "session_id": "setup-check", "action": action,
    }
    try:
        result = subprocess.run(
            [str(python), "-I", "-m", "luminary_memory.integrations", "bridge"],
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
    if not version.get("ok"):
        return {"version": version, "core": {"ok": False, "reason": "version_unavailable"}, "legacy": False}
    core = _bridge_call(python, agent, workspace, "core")
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


def _is_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    return os.name == "nt" and path.exists() and bool(
        path.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def _owned_copies(agent: str, root: Path) -> list[Path]:
    """Only hashed, unchanged copy-installer resources may be cut over."""
    folder = root / ("plugins" if agent == "opencode" else "extensions")
    legacy = folder / ("luminary-memory.ts" if agent == "opencode" else "luminary.ts")
    if legacy.exists():
        raise ValueError(f"Unverified legacy hook at {legacy}; inspect/remove it explicitly before native setup")
    target = folder / "luminary-memory"
    if not target.exists():
        return []
    marker = target / ".luminary-install.json"
    if _is_link(target) or not marker.is_file():
        raise ValueError(f"Unrecognized copy at {target}; resolve duplicate loading manually")
    hashes = _read_json(marker).get("files")
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError(f"Invalid ownership record at {marker}")
    expected = set(hashes) | {marker.name}
    for path in target.rglob("*"):
        if _is_link(path):
            raise ValueError(f"Symlinked copy resource at {path}; refusing cutover")
        if not path.is_file():
            continue
        name = path.relative_to(target).as_posix()
        if name not in expected:
            raise ValueError(f"User-added copy resource at {path}; refusing cutover")
        if name in hashes and hashlib.sha256(path.read_bytes()).hexdigest() != hashes[name]:
            raise ValueError(f"User-modified copy resource at {path}; refusing cutover")
    for name in hashes:
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or not (target / relative).is_file():
            raise ValueError(f"Invalid or incomplete owned copy at {target}")
    return [target]




def _prune(home: Path, bridge: dict, *, dry_run: bool) -> list[str]:
    entries = [entry for entry in bridge.get("agents", {}).values() if isinstance(entry, dict)]
    versions = {entry.get("version") for entry in entries}
    interpreters = [Path(entry["python"]) for entry in entries if entry.get("python")]
    removed: list[str] = []
    root = _venv_root(home)
    if not root.exists():
        return removed
    for child in sorted(root.iterdir()):
        if (not child.is_dir() or _is_link(child)
                or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", child.name)
                or not (child / "pyvenv.cfg").is_file()
                or child.name in versions
                # POSIX venv interpreters are symlinks, so keep both the
                # lexical and the resolved containment check.
                or any(python.is_relative_to(child) or python.resolve().is_relative_to(child.resolve())
                       for python in interpreters)):
            continue
        removed.append(child.name)
        if not dry_run:
            shutil.rmtree(child)
    return removed


@contextlib.contextmanager
def _park_copies(copies: list[Path]):
    moved: list[tuple[Path, Path]] = []
    try:
        for copy in copies:
            parked = copy.parent.parent / f".luminary-disabled-{time.time_ns()}"
            copy.rename(parked)
            moved.append((copy, parked))
        yield
    except BaseException:
        for original, parked in reversed(moved):
            parked.rename(original)
        raise
    else:
        # The record is already committed; a cleanup failure must not report a
        # failed setup that actually succeeded. Leftovers are pruned next run.
        for _, parked in moved:
            try:
                shutil.rmtree(parked)
            except OSError:
                pass


def _sweep_parked(root: Path) -> None:
    for parked in root.glob(".luminary-disabled-*"):
        try:
            shutil.rmtree(parked)
        except OSError:
            pass


@contextlib.contextmanager
def _host_transaction(agent: str, root: Path):
    """Rollback Luminary registration/resources without reverting unrelated settings."""
    from luminary_memory.integrations.cli import _atomic_write

    if agent == "opencode":
        paths, package = [_opencode_config(root)], None
    elif agent == "pi":
        paths = [root / "settings.json"]
        package = root / "npm" / "node_modules" / (PLUGIN_PREFIX + agent)
    else:
        paths = [root.parent / "plugins" / name for name in ("package.json", "omp-plugins.lock.json")]
        package = root.parent / "plugins" / "node_modules" / (PLUGIN_PREFIX + agent)
    originals = {path: path.read_text(encoding="utf-8-sig") if path.exists() else None for path in paths}
    if package is not None and _is_link(package):
        raise ValueError(f"Linked package at {package}; remove the local registration explicitly before native setup")
    with tempfile.TemporaryDirectory(prefix="luminary-host-") as temporary:
        backup = Path(temporary) / "package"
        if package is not None and package.exists():
            shutil.copytree(package, backup, symlinks=True)
        try:
            yield
        except Exception:
            for path, original in originals.items():
                current_text = path.read_text(encoding="utf-8-sig") if path.exists() else None
                if current_text == original:
                    continue
                previous = json.loads(_strip_jsonc(original)) if original else {}
                current = json.loads(_strip_jsonc(current_text)) if current_text else {}
                if agent in {"opencode", "pi"}:
                    key = "plugins" if agent == "opencode" else "packages"
                    kept = [item for item in current.get(key, []) if not _is_native(item, agent)]
                    old = [item for item in previous.get(key, []) if _is_native(item, agent)]
                    if key in previous or kept or old:
                        current[key] = kept + old
                    else:
                        current.pop(key, None)
                else:
                    keys = ["dependencies"] if path.name == "package.json" else ["plugins", "settings"]
                    for key in keys:
                        values = current.get(key, {})
                        old = previous.get(key, {})
                        name = PLUGIN_PREFIX + agent
                        if name in old:
                            values[name] = old[name]
                        else:
                            values.pop(name, None)
                        if key in current or key in previous:
                            current[key] = values
                if current == previous:
                    if original is None:
                        path.unlink(missing_ok=True)
                    else:
                        _atomic_write(path, original)
                else:
                    _atomic_write(path, json.dumps(current, indent=2) + "\n")
            if package is not None:
                if _is_link(package):
                    package.unlink()
                elif package.exists():
                    shutil.rmtree(package)
                if backup.exists():
                    shutil.copytree(backup, package, symlinks=True)
            raise


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
    if sum((check, upgrade, uninstall)) > 1:
        raise ValueError("choose only one of check, upgrade, or uninstall")
    if version is not None and not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("version must have the form X.Y.Z")
    selected = _selected(agents, home, project=project)
    if list_only:
        for agent in AGENTS:
            state = "detected" if detect(agent, home, project=project) else "absent"
            print(f"{agent:<9} {state:<9} {config_root(agent, home, project=project)}")
        return 0
    if not selected:
        print("No supported agent detected; use --agents opencode,pi,omp.", file=sys.stderr)
        return 2
    if project and "omp" in selected and not no_config and not (check or uninstall):
        print("omp native project install is unsupported; use explicit project copy installation.", file=sys.stderr)
        return 2
    # Serialize record read/merge and host cutover, not read-only operations.
    with contextlib.ExitStack() as stack:
        if not check and not dry_run:
            stack.enter_context(_lock(home, "setup"))
        return _run_setup(
            selected, home=home, version=version, project=project,
            no_config=no_config, check=check, upgrade=upgrade, uninstall=uninstall,
            prune=prune, dry_run=dry_run, json_output=json_output, python=python,
        )


def _run_setup(
    selected: list[str], *, home: Path, version: str | None, project: bool,
    no_config: bool, check: bool, upgrade: bool, uninstall: bool, prune: bool,
    dry_run: bool, json_output: bool, python: Path | None,
) -> int:
    bridge = _read_bridge(home)
    entries = bridge["agents"]
    reports: list[AgentReport] = []
    exit_code = 0
    for agent in selected:
        root = config_root(agent, home, project=project)
        report = AgentReport(agent, detect(agent, home, project=project), root)
        reports.append(report)
        existing = entries.get(agent) if isinstance(entries.get(agent), dict) else {}
        report.bridge = existing.get("version")
        try:
            report.pin = _plugin_pin(agent, root)
            target = version or (__version__ if upgrade else report.pin or report.bridge or __version__)
            if not (check or uninstall) and not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", target):
                raise ValueError(f"unsupported release pin {target!r}; select --version X.Y.Z")
            if check:
                override = os.environ.get("LUMINARY_PYTHON")
                interpreter = Path(override or existing.get("python") or "")
                actual = _probe_version(interpreter) if interpreter.is_file() else None
                if not report.bridge:
                    report.status = "missing"
                elif not interpreter.is_file():
                    report.status, report.detail = "missing", f"interpreter not found: {interpreter}"
                elif actual is None:
                    report.status, report.detail = "broken", "package import or bridge capability probe failed"
                elif actual != report.bridge or (report.pin and report.pin != report.bridge):
                    report.status, report.detail = "drift", f"package={actual}, record={report.bridge}, pin={report.pin or '-'}"
                elif not no_config and existing.get("mode") == "npm" and not _native_registered(agent, root, report.bridge):
                    report.status, report.detail = "missing", "native package registration is missing or disabled"
                elif not no_config and existing.get("mode") == "copy":
                    try:
                        if not _owned_copies(agent, root):
                            raise ValueError("copied adapter is missing")
                    except ValueError as exc:
                        report.status, report.detail = "broken", str(exc)
                    else:
                        report.status = "ok"
                else:
                    report.status = "ok"
                if report.status != "ok":
                    exit_code = 1
                continue
            if dry_run:
                if not no_config:
                    _owned_copies(agent, root)
                report.status = "planned"
                report.detail = "remove selected registration" if uninstall else f"native setup {target}"
                continue
            if uninstall:
                copies = _owned_copies(agent, root) if not no_config else []
                # A project registration shares the user-wide per-agent runtime
                # record; removing the global entry must not revoke it.
                project_pin = _plugin_pin(agent, config_root(agent, home, project=True)) if not project else None
                try:
                    transaction = contextlib.nullcontext() if no_config else _host_transaction(agent, root)
                    with transaction, _park_copies(copies):
                        if not no_config:
                            _native_remove(agent, root, home, project=project, dry_run=False)
                        if not project and project_pin is None:
                            entries.pop(agent, None)
                            if existing:
                                _write_bridge(home, bridge, dry_run=False)
                        elif not project:
                            report.detail = "runtime record retained for the current project registration"
                except Exception:
                    if existing:
                        entries[agent] = existing
                    raise
                report.status = "removed" if existing or report.pin is not None or copies else "absent"
                continue
            if existing.get("mode") == "copy" and not upgrade and not no_config:
                raise ValueError("copied/pre-managed installation requires explicit --upgrade for native migration")
            copies = _owned_copies(agent, root) if not no_config else []
            if not no_config:
                other = config_root(agent, home, project=not project)
                if other != root and _owned_copies(agent, other):
                    raise ValueError(
                        f"Luminary copy adapter is also installed at {other}; "
                        "remove that scope explicitly before native migration"
                    )
                _sweep_parked(root)
            override = os.environ.get("LUMINARY_PYTHON")
            if override:
                interpreter = Path(override)
                if _probe_version(interpreter) != target:
                    raise ValueError(f"invalid LUMINARY_PYTHON or package version mismatch: {override}; no fallback used")
            else:
                current = python or (Path(existing["python"]) if existing.get("python") else None)
                interpreter = ensure_venv(target, home, current=current)
            result = handshake(interpreter, agent, Path.cwd())
            report.handshake = result
            if not result["version"].get("ok") or result["version"].get("version") != target:
                raise RuntimeError("bridge version handshake failed or mismatched the selected release")
            if not result["core"].get("ok"):
                raise RuntimeError(f"bridge core handshake failed: {result['core'].get('reason', 'unavailable')}")
            _ensure_model_cache(home, dry_run=False)
            try:
                transaction = contextlib.nullcontext() if no_config else _host_transaction(agent, root)
                with transaction, _park_copies(copies):
                    if not no_config:
                        _native_install(agent, root, home, target, project=project)
                    entries[agent] = {
                        "python": str(interpreter), "version": target,
                        "mode": existing.get("mode", "bridge") if no_config else "npm",
                    }
                    _write_bridge(home, bridge, dry_run=False)
            except Exception:
                if existing:
                    entries[agent] = existing
                else:
                    entries.pop(agent, None)
                raise
            report.bridge, report.pin, report.status = target, _plugin_pin(agent, root), "ok"
        except (OSError, ValueError, TypeError, RuntimeError, subprocess.SubprocessError) as exc:
            report.status, report.detail = "error", str(exc)
            exit_code = 1
    pruned = _prune(home, bridge, dry_run=dry_run) if prune and not check else []
    if json_output:
        print(json.dumps({
            "ok": exit_code == 0, "bridge_file": str(_bridge_file(home)),
            "agents": [
                {"agent": report.agent, "detected": report.detected,
                 "config_root": str(report.config_root), "pin": report.pin,
                 "bridge": report.bridge, "status": report.status, "detail": report.detail}
                for report in reports
            ], "pruned": pruned,
        }, indent=2))
    else:
        for report in reports:
            print(f"{report.agent:<9} {report.status:<9} bridge={report.bridge or '-'} pin={report.pin or '-'}  {report.detail}")
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
