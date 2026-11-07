"""Run the Python suite with an official Hermes source checkout, without SDK stubs."""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("hermes_source", type=Path, help="Official Hermes Agent source checkout")
    args, pytest_args = parser.parse_known_args()
    source = args.hermes_source.resolve(strict=True)
    sys.path.insert(0, str(source))
    with tempfile.TemporaryDirectory(prefix="luminary-hermes-sdk-") as home:
        os.environ["HERMES_HOME"] = home
        os.environ["LUMINARY_CONFIG_FILE"] = "none"
        # Fail before pytest can skip SDK-dependent cases or install its ABC stub.
        import agent.memory_provider
        import plugins.memory.config_schema
        for module in (agent.memory_provider, plugins.memory.config_schema):
            if not Path(module.__file__).resolve().is_relative_to(source):
                raise RuntimeError("Native SDK modules must come from the requested Hermes checkout")
        import pytest

        return int(pytest.main(pytest_args))


if __name__ == "__main__":
    raise SystemExit(main())
