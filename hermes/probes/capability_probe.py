"""Check that the Hermes runtime exposes the Luminary memory-provider contract.

The installer runs this before it touches any Hermes configuration. It must pass
in both host layouts:

* a pip-installed Hermes, where ``agent`` is already importable;
* a git-checkout Hermes, where ``agent`` lives in the checkout and is only on
  ``sys.path`` because the ``hermes`` launcher inserts it.

Run it with ``-I`` so a package that only landed in the user site cannot make the
check pass: Hermes itself runs isolated, so user-site visibility proves nothing.

Exit status is 0 on success. Every failure mode prints one actionable line and
exits non-zero.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from importlib import metadata
from pathlib import Path

REQUIRED = ("name", "is_available", "initialize", "get_tool_schemas")


def _candidate_roots():
    """Yield directories that may hold the Hermes ``agent`` package."""
    seen: set[str] = set()

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
            check=False,
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


def load_contract():
    """Return Hermes' ``MemoryProvider``, importing it wherever it lives."""
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


def main() -> int:
    MemoryProvider = load_contract()
    if MemoryProvider is None:
        print(
            "the Hermes agent package is not importable. Install Hermes with pip, or "
            "set HERMES_HOME to the directory that contains the Hermes checkout.",
            file=sys.stderr,
        )
        return 1

    missing = [name for name in REQUIRED if not hasattr(MemoryProvider, name)]
    if missing:
        print(
            "Hermes public MemoryProvider contract is missing: " + ", ".join(missing),
            file=sys.stderr,
        )
        return 1

    entry_points = metadata.entry_points()
    if hasattr(entry_points, "select"):
        installed = {
            entry.name
            for entry in entry_points.select(group="hermes_agent.memory_providers")
        }
    else:
        installed = {
            entry.name
            for entry in entry_points
            if getattr(entry, "group", "") == "hermes_agent.memory_providers"
        }
    if "luminary" not in installed:
        print(
            "Luminary entry point is not visible to the Hermes runtime interpreter. "
            "Hermes runs with -I, so a --user install is not enough; install into the "
            "environment that runs Hermes.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
