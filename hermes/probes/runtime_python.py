"""Print the interpreter Hermes actually runs with, or nothing.

Hermes does not run the bare interpreter. At launch it activates a managed
dependency environment and imports the ``agent`` package from its own checkout,
so a package installed into the base interpreter or the user site is invisible
to the host. The installer has to target the activated environment instead of
guessing, and this module is how it finds out.

Run it with ``-I`` so the answer reflects the isolation Hermes itself uses::

    python3 -I hermes/probes/runtime_python.py
    python3 -I hermes/probes/runtime_python.py --site-packages

Prints the absolute path of the runtime interpreter (or its ``site-packages``
directory) on success and nothing when no Hermes installation can be located. It
never fails the caller, because the installer falls back to the interpreter it
was given.
"""

from __future__ import annotations

import contextlib
import os
import site
import sys
from pathlib import Path


def _roots():
    """Yield directories that may hold the Hermes bootstrap module."""
    home = os.environ.get("HERMES_HOME")
    if home:
        yield Path(home) / "hermes-agent"
        yield Path(home)
    names = ("hermes.exe",) if os.name == "nt" else ("hermes",)
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not os.path.isabs(entry):
            continue
        for name in names:
            exe = Path(entry) / name
            if not exe.is_file():
                continue
            for parent in exe.resolve().parents:
                if (parent / "hermes_bootstrap.py").is_file():
                    yield parent
                    break


def runtime_environment() -> tuple[Path, Path] | None:
    """Return ``(interpreter, site-packages)`` for the environment Hermes activates."""
    # The base interpreter, the interpreter running this probe, and the user site
    # are exactly the places Hermes cannot see, so none of them can be the answer.
    skip = {Path(sys.base_prefix).resolve(), Path(sys.prefix).resolve()}
    # A host without a user site is still valid, so this is not an error path.
    with contextlib.suppress(Exception):
        skip.add(Path(site.getusersitepackages()).resolve())
    for root in _roots():
        if not (root / "hermes_bootstrap.py").is_file():
            continue
        sys.path.insert(0, str(root))
        try:
            import hermes_bootstrap  # noqa: F401
        except Exception:  # noqa: BLE001 - a broken checkout is not our failure
            sys.path.remove(str(root))
            continue
        for entry in sys.path:
            if not entry or not entry.endswith("site-packages"):
                continue
            path = Path(entry).resolve()
            if any(path.is_relative_to(root) for root in skip):
                continue
            for parent in path.parents:
                if not (parent / "pyvenv.cfg").is_file():
                    continue
                candidate = parent / (
                    "Scripts/python.exe" if os.name == "nt" else "bin/python"
                )
                if candidate.exists():
                    return candidate, path
                break
    return None


def runtime_python() -> Path | None:
    """Return the interpreter of the environment Hermes activates, if any."""
    found = runtime_environment()
    return found[0] if found else None


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    found = runtime_environment()
    if found is None:
        return 0
    interpreter, site_packages = found
    print(site_packages if "--site-packages" in args else interpreter)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
