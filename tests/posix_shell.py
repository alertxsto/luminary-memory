"""Resolve a POSIX shell that can actually run the install script.

Windows resolves a bare ``bash`` to ``System32\\bash.exe``, the WSL stub. On a
runner without a WSL distribution it exits non-zero with "Windows Subsystem for
Linux has no installed distributions", so it is not a POSIX shell. Git for
Windows ships the real one.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def posix_bash() -> str | None:
    candidates: list[Path] = []
    if os.name == "nt":
        for base in (
            os.environ.get("ProgramFiles"),
            os.environ.get("ProgramFiles(x86)"),
            os.environ.get("LOCALAPPDATA"),
        ):
            if base:
                candidates += [
                    Path(base) / "Git" / "bin" / "bash.exe",
                    Path(base) / "Git" / "usr" / "bin" / "bash.exe",
                ]
    found = shutil.which("bash")
    if found:
        candidates.insert(0, Path(found))
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            probe = subprocess.run(
                [str(candidate), "-c", "printf ok"],
                capture_output=True, text=True, timeout=60,
            )
        except OSError:
            continue
        if probe.returncode == 0 and probe.stdout.strip() == "ok":
            return str(candidate)
    return None
