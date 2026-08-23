"""Hermes activation through its stable on-disk configuration boundary.

This module deliberately does not import Hermes.  It only edits the documented
top-level ``memory`` settings in ``config.yaml`` and preserves every unrelated
line.  Keeping this adapter independent means the provider can be installed
before, after, or alongside a Hermes update without importing private Hermes
modules or checking a Hermes version number.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_MEMORY_HEADER_RE = re.compile(r"^memory:\s*(?:#.*)?(?:\r?\n)?$")
_INLINE_MEMORY_RE = re.compile(r"^memory:\s+\S")


def _is_top_level_key(line: str) -> bool:
    """Return whether a line starts a non-comment top-level YAML key."""

    return bool(line) and not line[0].isspace() and not line.lstrip().startswith("#")


def activate_config(config_path: str | Path) -> Path:
    """Select Luminary as the memory authority in a Hermes config file.

    Only these three official settings are changed:

    * ``memory.provider = luminary``
    * ``memory.memory_enabled = false``
    * ``memory.user_profile_enabled = false``

    The two native switches are intentionally changed together.  Selecting an
    external provider while leaving either native surface on creates two
    competing persistent memories and is therefore an incomplete setup.
    """

    path = Path(config_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(
            "memory:\n"
            "  provider: luminary\n"
            "  memory_enabled: false\n"
            "  user_profile_enabled: false\n",
            encoding="utf-8",
        )
        return path

    source = path.read_text(encoding="utf-8")
    lines = source.splitlines(keepends=True)
    eol = "\r\n" if "\r\n" in source else "\n"

    memory_indexes = [
        index for index, line in enumerate(lines) if _MEMORY_HEADER_RE.match(line)
    ]
    if not memory_indexes:
        if any(_INLINE_MEMORY_RE.match(line) for line in lines):
            raise ValueError(
                "memory is an inline YAML mapping; convert it to a block before activation"
            )
        if lines and not lines[-1].endswith(("\n", "\r")):
            lines.append(eol)
        lines.extend(
            [
                f"memory:{eol}",
                f"  provider: luminary{eol}",
                f"  memory_enabled: false{eol}",
                f"  user_profile_enabled: false{eol}",
            ]
        )
        path.write_text("".join(lines), encoding="utf-8")
        return path

    start = memory_indexes[0]
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if _is_top_level_key(lines[index]):
            end = index
            break

    def replace_or_add(block_end: int, key: str, value: str) -> int:
        key_re = re.compile(rf"^  {re.escape(key)}:")
        for index in range(start + 1, block_end):
            if key_re.match(lines[index]):
                newline = "\r\n" if lines[index].endswith("\r\n") else eol
                lines[index] = f"  {key}: {value}{newline}"
                return block_end
        lines.insert(block_end, f"  {key}: {value}{eol}")
        return block_end + 1

    for key, value in (
        ("provider", "luminary"),
        ("memory_enabled", "false"),
        ("user_profile_enabled", "false"),
    ):
        end = replace_or_add(end, key, value)

    path.write_text("".join(lines), encoding="utf-8")
    return path


def activation_configs(hermes_home: str | Path) -> list[Path]:
    """Return the root config and existing profile configs in stable order.

    Hermes profiles inherit the root configuration when they do not have a
    local config. We therefore only edit profile files that already exist;
    activation never creates a new profile or invents a second Luminary
    configuration file.
    """
    home = Path(hermes_home).expanduser()
    root = home / "config.yaml"
    paths = [root]
    profiles = home / "profiles"
    if profiles.is_dir():
        paths.extend(sorted(profiles.glob("*/config.yaml")))
    return paths


def activate_home(hermes_home: str | Path) -> list[Path]:
    """Select Luminary in the root and every existing Hermes profile config."""
    activated: list[Path] = []
    for path in activation_configs(hermes_home):
        activate_config(path)
        activated.append(path)
    return activated


def main(argv: list[str] | None = None) -> int:
    """Small installer-facing command; no Hermes package is required."""

    args = list(argv if argv is not None else sys.argv[1:])
    if args in (["--help"], ["-h"]):
        print(
            "usage: python -m luminary_memory.hermes.activation "
            "[--all-profiles] CONFIG.yaml"
        )
        return 0
    all_profiles = False
    if args and args[0] == "--all-profiles":
        all_profiles = True
        args.pop(0)
    if len(args) != 1:
        print(
            "usage: python -m luminary_memory.hermes.activation [--all-profiles] CONFIG.yaml",
            file=sys.stderr,
        )
        return 2
    try:
        if all_profiles:
            activated = activate_home(Path(args[0]).expanduser().parent)
        else:
            activated = [activate_config(args[0])]
    except (OSError, ValueError) as exc:
        print(f"luminary activation failed: {exc}", file=sys.stderr)
        return 1
    print(
        "configured Luminary as the sole persistent memory surface "
        f"in {len(activated)} Hermes config(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
