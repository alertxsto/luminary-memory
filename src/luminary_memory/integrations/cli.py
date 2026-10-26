"""Install packaged native adapters and expose the JSON subprocess boundary."""

from __future__ import annotations

import contextlib
import importlib.resources
import json
import os
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
            mode="w", encoding="utf-8", dir=path.parent, delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def install_adapter(agent: str, directory: Path, *, force: bool = False) -> list[Path]:
    """Install only owned files; merge dependencies without replacing user config."""
    if agent not in AGENTS:
        raise ValueError("agent must be opencode, pi, or omp")
    source = importlib.resources.files("luminary_memory.integrations").joinpath("assets", agent)
    directory = directory.expanduser().resolve()
    name = "luminary-memory.ts" if agent == "opencode" else "luminary.ts"
    target = directory / ("plugins" if agent == "opencode" else "extensions") / name
    content = source.joinpath(name).read_text(encoding="utf-8").replace(
        '"__LUMINARY_PYTHON__"', json.dumps(sys.executable),
    )
    planned = {target: content}
    if target.exists() and target.read_text(encoding="utf-8") != content and not force:
        raise ValueError(f"{target} differs; inspect it, then use --force to replace this hook")
    if agent == "opencode":
        package_path = directory / "package.json"
        package = json.loads(package_path.read_text(encoding="utf-8")) if package_path.exists() else {}
        if not isinstance(package, dict):
            raise ValueError("OpenCode package.json must be an object")
        dependencies = package.setdefault("dependencies", {})
        if not isinstance(dependencies, dict):
            raise ValueError("OpenCode package.json dependencies must be an object")
        needed = json.loads(source.joinpath("package.json").read_text(encoding="utf-8"))
        for name, version in needed["dependencies"].items():
            if name in dependencies and dependencies[name] != version and not force:
                raise ValueError(f"Dependency {name} differs; inspect it before using --force")
            dependencies[name] = version
        planned[package_path] = json.dumps(package, indent=2, ensure_ascii=False) + "\n"
    for path, value in planned.items():
        _atomic_write(path, value)
    return list(planned)


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
            typer.echo("Targets OpenCode V2 (@opencode/plugin 2.1.4); use the plural plugins config and restart/reload.")
    except (OSError, ValueError) as exc:
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
