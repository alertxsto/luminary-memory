"""Install packaged native adapters and expose the JSON subprocess boundary."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.resources
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Annotated

import typer

from luminary_memory.integrations import AGENTS, MAX_REQUEST_BYTES, dispatch

app = typer.Typer(
    help="Supported native harness adapters and a harness-neutral JSON memory bridge.",
    no_args_is_help=True,
)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=path.parent, delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _install_tree(target: Path, files: dict[str, str], *, force: bool) -> list[Path]:
    """Cut over one complete owned module tree; preserve user-added files."""
    if target.is_symlink():
        raise ValueError(f"Refusing to replace symlinked plugin directory: {target}")
    marker = target / ".luminary-install.json"
    previous = json.loads(marker.read_text(encoding="utf-8")) if marker.exists() else {}
    hashes = previous.get("files", {})
    if not isinstance(hashes, dict):
        raise TypeError("Invalid Luminary installation ownership record")
    for name in {*hashes, *files}:
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Invalid installed resource name")
        path = target / relative
        if any(parent.is_symlink() for parent in (path, *path.parents) if parent != target.parent):
            raise ValueError(f"Refusing symlinked plugin resource: {path}")
        if path.exists() and not force:
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != hashes.get(name):
                raise ValueError(f"{path} was changed outside the installer; inspect it before --force")
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".luminary-stage-", dir=target.parent.parent))
    backup = Path(tempfile.mkdtemp(prefix=".luminary-previous-", dir=target.parent.parent))
    backup.rmdir()
    moved = False
    try:
        if target.exists():
            shutil.copytree(target, stage, dirs_exist_ok=True, symlinks=True)
        for name in hashes.keys() - files.keys():
            (stage / name).unlink(missing_ok=True)
        for name, content in files.items():
            _atomic_write(stage / name, content)
        _atomic_write(stage / ".luminary-install.json", json.dumps({
            "files": {name: hashlib.sha256(content.encode("utf-8")).hexdigest() for name, content in files.items()},
        }, indent=2) + "\n")
        if target.exists():
            target.rename(backup)
            moved = True
        try:
            stage.rename(target)
        except BaseException:
            if moved:
                backup.rename(target)
                moved = False
            raise
        if moved:
            shutil.rmtree(backup)
        return [target / name for name in files]
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def install_adapter(agent: str, directory: Path, *, force: bool = False) -> list[Path]:
    """Install the complete compiled native package, never an orphaned TS file."""
    if agent not in AGENTS:
        raise ValueError("agent must be opencode, pi, or omp")
    resources = importlib.resources.files("luminary_memory.integrations").joinpath("assets")
    source = resources.joinpath("compiled", agent)
    names = ["index.js", "rpc.js", "tui.js"] if agent == "opencode" else ["index.js"]
    if agent == "opencode" and source.joinpath("gui-experimental.cjs").is_file():
        names.append("gui-experimental.cjs")
    files = {}
    for name in names:
        try:
            files[name] = source.joinpath(name).read_text(encoding="utf-8").replace(
                '"__LUMINARY_PYTHON__"', json.dumps(sys.executable),
            )
        except FileNotFoundError as exc:
            raise ValueError("Native resources are absent. Install a complete wheel, or run npm run build before building the wheel.") from exc
    exports = {".": "./index.js"}
    if agent == "opencode":
        exports.update({"./rpc": "./rpc.js", "./tui": "./tui.js"})
        if "gui-experimental.cjs" in files:
            exports["./gui-experimental"] = "./gui-experimental.cjs"
    manifest = {"name": f"luminary-memory-{agent}", "type": "module", "main": "./index.js", "exports": exports}
    if agent != "opencode":
        manifest[agent] = {"extensions": ["./index.js"]}
    files["package.json"] = json.dumps(manifest, indent=2) + "\n"
    directory = directory.expanduser().resolve()
    folder = directory / ("plugins" if agent == "opencode" else "extensions")
    legacy = folder / ("luminary-memory.ts" if agent == "opencode" else "luminary.ts")
    if legacy.exists():
        prefix = {"pi": "// Native pi extension.", "omp": "// Native omp extension.",
                  "opencode": "// OpenCode V2 server plugin."}[agent]
        if not legacy.read_text(encoding="utf-8").startswith(prefix):
            raise ValueError(f"{legacy} is not an identifiable owned hook; leave it untouched and resolve duplicate loading manually")
        if not force:
            raise ValueError(f"Legacy Luminary hook exists at {legacy}; --force performs the explicit package cutover")
    package_path, package_text = directory / "package.json", None
    if agent == "opencode":
        package = json.loads(package_path.read_text(encoding="utf-8")) if package_path.exists() else {}
        if not isinstance(package, dict) or not isinstance(package.setdefault("dependencies", {}), dict):
            raise ValueError("OpenCode package.json and dependencies must be objects")
        needed = json.loads(resources.joinpath(agent, "package.json").read_text(encoding="utf-8"))
        for name, version in needed["dependencies"].items():
            if name in package["dependencies"] and package["dependencies"][name] != version and not force:
                raise ValueError(f"Dependency {name} differs; inspect it before --force")
            package["dependencies"][name] = version
        package_text = json.dumps(package, indent=2) + "\n"
    installed = _install_tree(folder / "luminary-memory", files, force=force)
    if package_text is not None:
        _atomic_write(package_path, package_text)
        installed.append(package_path)
    if legacy.exists():
        legacy.unlink()
    return installed


@app.command("install")
def install(
    agent: str = typer.Argument(..., help="opencode | pi | omp"),
    directory: Annotated[
        Path | None,
        typer.Option("--directory", help="Native config root (.opencode, .pi, or .omp), not workspace root"),
    ] = None,
    global_install: bool = typer.Option(False, "--global", help="Install into the user's native config"),
    force: bool = typer.Option(False, "--force", help="Replace this hook and conflicting SDK dependency"),
) -> None:
    """Install real hooks; restart/reload the target agent afterwards."""
    try:
        if agent not in AGENTS:
            raise ValueError("agent must be opencode, pi, or omp")
        if directory is not None and global_install:
            raise ValueError("choose --directory or --global, not both")
        if directory is None:
            if global_install:
                if agent == "opencode":
                    directory = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / agent
                else:
                    directory = Path.home() / f".{agent}" / "agent"
            else:
                directory = Path.cwd() / f".{agent}"
        for path in install_adapter(agent, directory, force=force):
            typer.echo(f"Installed {path}")
        typer.echo(f"Python bridge: {sys.executable}")
        typer.echo("Restart/reload the agent. Configure LUMINARY_DB_PATH to select a shared store.")
        if agent == "opencode":
            typer.echo(f"From {directory}, run: npm install --ignore-scripts")
            typer.echo("Node dependencies are not installed automatically. Then restart/reload OpenCode.")
    except (OSError, ValueError, TypeError) as exc:
        typer.echo(f"Install failed: {exc}", err=True)
        raise typer.Exit(1) from None


@app.command("bridge")
def bridge() -> None:
    """Read one bounded JSON request on stdin; emit one JSON response on stdout."""
    try:
        raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        if len(raw) > MAX_REQUEST_BYTES:
            raise ValueError("request exceeds 131072 bytes")
        request = json.loads(raw.decode("utf-8"))
        # Embedding runtimes must not corrupt the machine-readable response.
        with contextlib.redirect_stdout(sys.stderr):
            response = dispatch(request)
    except (ValueError, TypeError, UnicodeDecodeError) as exc:
        response = {"ok": False, "status": "error", "reason": "invalid_request", "message": str(exc),
                    "context": "", "memories": [], "stored": 0, "deleted": 0}
    except Exception as exc:  # noqa: BLE001 — process boundary; never expose credentials
        response = {"ok": False, "status": "error", "reason": type(exc).__name__,
                    "message": "Memory operation failed; inspect local configuration and store access.",
                    "context": "", "memories": [], "stored": 0, "deleted": 0}
    sys.stdout.buffer.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()
    if not response["ok"]:
        raise typer.Exit(1)


@app.command("inspector")
def inspector() -> None:
    """Run one inspector operation using verified native launcher context."""
    from luminary_memory.integrations.inspector_cli import inspector_main

    inspector_main()


@app.command("install-hermes-ui")
def install_hermes_ui(
    home: Annotated[Path, typer.Option("--home", help="Explicit native Hermes profile home; does not activate a provider")],
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Install the unified native UI/backend package, independently of retention."""
    source = importlib.resources.files("luminary_memory.integrations").joinpath("assets", "compiled", "hermes")
    files: dict[str, str] = {}

    def collect(root, prefix=""):
        for entry in root.iterdir():
            if entry.name == "__pycache__":
                continue
            name = prefix + entry.name
            if entry.is_dir():
                collect(entry, name + "/")
            else:
                files[name] = entry.read_text(encoding="utf-8")

    collect(source)
    target = home.expanduser().resolve() / "plugins" / "luminary-inspector"
    for path in _install_tree(target, files, force=force):
        typer.echo(f"Installed {path}")
    typer.echo("Enable the ordinary backend and Desktop/dashboard UI explicitly, then restart the backend. Saving and provider activation are unchanged.")


@app.command("companion")
def companion(
    agent: Annotated[str, typer.Option("--agent", help="Exact configured native agent identity")],
    workspace: Annotated[Path, typer.Option("--workspace", help="Explicit native workspace location")],
    session_id: Annotated[str, typer.Option("--session-id", help="Native session ID")],
    profile: str = typer.Option("default", "--profile"),
    port: int = typer.Option(0, "--port", min=0, max=65535),
    open_browser: bool = typer.Option(False, "--open", help="Explicitly open the one-use owner sign-in link"),
) -> None:
    """Explicit optional loopback UI. Never launched by a hook or UI failure."""
    import socket

    from luminary_memory.inspector.web import create_server

    server = create_server({
        "agent_id": agent, "workspace": str(workspace.expanduser().resolve()),
        "session_id": session_id, "host_id": socket.gethostname(), "profile_id": profile,
    }, port=port)
    if open_browser:
        import webbrowser
        webbrowser.open(server.bootstrap_url)
        typer.echo(f"Companion opened at {server.origin}; Ctrl+C stops it.")
    else:
        typer.echo(f"Private one-use owner sign-in link (expires in 60 seconds): {server.bootstrap_url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
