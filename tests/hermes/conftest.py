"""Native schema cases require Hermes; the release SDK gate runs them fail-closed."""
import importlib

import pytest


@pytest.fixture(scope="session")
def hermes_config_sdk():
    try:
        return importlib.import_module("plugins.memory.config_schema")
    except ModuleNotFoundError as error:
        if error.name in {"plugins", "plugins.memory", "plugins.memory.config_schema"}:
            pytest.skip("Requires the official Hermes config SDK; exercised by the native SDK release gate")
        raise
