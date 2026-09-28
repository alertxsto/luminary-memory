#!/usr/bin/env python3
"""Fail closed unless a release tag matches project, runtime, and wheel metadata."""

import argparse
import email
import re
import sys
import tomllib
from pathlib import Path
from zipfile import ZipFile

VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\Z")


def verify(tag: str, project: Path, runtime: Path, wheel: Path, manual_ref: str | None) -> None:
    if not tag.startswith("v") or not VERSION.fullmatch(tag[1:]):
        raise ValueError(f"invalid release tag {tag!r}; expected vX.Y.Z")
    if manual_ref is not None and manual_ref != f"refs/tags/{tag}":
        raise ValueError(f"manual dispatch must run on refs/tags/{tag}, not {manual_ref!r}")
    version = tag[1:]
    with project.open("rb") as source:
        project_version = tomllib.load(source)["project"]["version"]
    runtime_text = runtime.read_text(encoding="utf-8")
    runtime_versions = re.findall(r'^__version__\s*=\s*"([^"]+)"\s*$', runtime_text, re.MULTILINE)
    if len(runtime_versions) != 1:
        raise ValueError("runtime must declare exactly one __version__")
    with ZipFile(wheel) as archive:
        metadata_paths = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(metadata_paths) != 1:
            raise ValueError(f"wheel must contain exactly one METADATA, found {len(metadata_paths)}")
        info = email.message_from_bytes(archive.read(metadata_paths[0]))
    if info.get("Name", "").lower().replace("_", "-") != "luminary-memory":
        raise ValueError("wheel metadata is not for luminary-memory")
    versions = {"tag": version, "project": project_version, "runtime": runtime_versions[0], "wheel": info.get("Version")}
    if any(value != version for value in versions.values()):
        raise ValueError("release versions disagree: " + ", ".join(f"{key}={value!r}" for key, value in versions.items()))
    print(f"verified release {tag}: project, runtime, wheel metadata agree")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--project", type=Path, default=Path("pyproject.toml"))
    parser.add_argument("--runtime", type=Path, default=Path("src/luminary_memory/__init__.py"))
    parser.add_argument("--manual-ref", help="GITHUB_REF from workflow_dispatch; must be the selected tag")
    args = parser.parse_args()
    try:
        verify(args.tag, args.project, args.runtime, args.wheel, args.manual_ref)
    except (OSError, KeyError, ValueError, IndexError) as exc:
        print(f"release verification failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
