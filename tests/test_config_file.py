"""Optional operator config file for native integrations and the CLI."""

import getpass
import os
from pathlib import Path

from luminary_memory import MemoryClient
from luminary_memory.config import (
    CONFIG_FILE_ENV,
    Settings,
    default_config_path,
    load_config_file,
)
from luminary_memory.integrations import dispatch


class Engine:
    def embed(self, _text):
        return [0.25] * 384

    def embed_batch(self, texts):
        return [self.embed(text) for text in texts]


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_env_style_file_and_constructs_settings(tmp_path, monkeypatch):
    config = _write(
        tmp_path / "luminary.env",
        "\ufeff# operator settings\r\n"
        "export LUMINARY_TOKEN_BUDGET=2048\r\n"
        'LUMINARY_LLM_MODEL="curator-model"\r\n'
        "LUMINARY_LLM_API_KEY='secret-key'\r\n"
        "UNRELATED_SETTING=ignored\r\n",
    )
    monkeypatch.setenv(CONFIG_FILE_ENV, str(config))

    assert load_config_file() == config
    settings = Settings()
    assert settings.token_budget == 2048
    assert settings.llm_model == "curator-model"
    assert settings.llm_api_key == "secret-key"
    assert "UNRELATED_SETTING" not in os.environ


def test_process_environment_wins_unless_override_requested(tmp_path, monkeypatch):
    config = _write(tmp_path / "luminary.env", "LUMINARY_TOKEN_BUDGET=2048\n")
    monkeypatch.setenv(CONFIG_FILE_ENV, str(config))
    monkeypatch.setenv("LUMINARY_TOKEN_BUDGET", "8192")

    load_config_file()
    assert os.environ["LUMINARY_TOKEN_BUDGET"] == "8192"

    load_config_file(override=True)
    assert os.environ["LUMINARY_TOKEN_BUDGET"] == "2048"


def test_default_path_is_loaded(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".luminary").mkdir(parents=True)
    config = _write(home / ".luminary" / "luminary.env", "LUMINARY_CORE_TOP_N=3\n")
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv(CONFIG_FILE_ENV, raising=False)

    assert default_config_path() == Path.home() / ".luminary" / "luminary.env"
    assert load_config_file() == config
    assert os.environ["LUMINARY_CORE_TOP_N"] == "3"


def test_missing_explicit_file_warns_and_is_noop(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv(CONFIG_FILE_ENV, str(tmp_path / "missing.env"))
    with caplog.at_level("WARNING"):
        assert load_config_file() is None
    assert "not found" in caplog.text


def test_missing_default_file_is_silent(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "empty-home"))
    monkeypatch.setenv("HOME", str(tmp_path / "empty-home"))
    monkeypatch.delenv(CONFIG_FILE_ENV, raising=False)
    with caplog.at_level("WARNING"):
        assert load_config_file() is None
    assert "not found" not in caplog.text


def test_disabled_file_loading(monkeypatch):
    monkeypatch.setenv(CONFIG_FILE_ENV, "none")
    assert load_config_file() is None


def test_malformed_line_is_skipped_and_warned(tmp_path, monkeypatch, caplog):
    config = _write(
        tmp_path / "luminary.env",
        "not an assignment\nLUMINARY_CORE_TOP_N=4\n",
    )
    monkeypatch.setenv(CONFIG_FILE_ENV, str(config))
    with caplog.at_level("WARNING"):
        assert load_config_file() == config
    assert os.environ["LUMINARY_CORE_TOP_N"] == "4"
    assert "malformed" in caplog.text


def test_file_cannot_redirect_itself(tmp_path, monkeypatch):
    config = _write(
        tmp_path / "luminary.env",
        f"{CONFIG_FILE_ENV}={tmp_path / 'other.env'}\nLUMINARY_CORE_TOP_N=5\n",
    )
    monkeypatch.setenv(CONFIG_FILE_ENV, str(config))

    assert load_config_file() == config
    assert os.environ[CONFIG_FILE_ENV] == str(config)
    assert os.environ["LUMINARY_CORE_TOP_N"] == "5"


def test_dispatch_loads_file_before_constructing_settings(tmp_path, monkeypatch):
    config = _write(tmp_path / "luminary.env", "LUMINARY_INGEST_LLM=true\n")
    monkeypatch.setenv(CONFIG_FILE_ENV, str(config))
    scope = {
        "workspace_id": os.path.normcase(str(tmp_path.resolve())),
        "user_id": getpass.getuser(),
        "agent_id": "pi",
    }
    client = MemoryClient(
        settings=Settings(
            db_path=str(tmp_path / "native.db"),
            scope_include_global=False,
            strict_recall=True,
            evidence_required=True,
            rule_auto_replace=False,
        ),
        engine=Engine(),
        scope=scope,
    )
    try:
        response = dispatch(
            {
                "agent": "pi",
                "workspace": str(tmp_path),
                "session_id": "config-file",
                "action": "turn",
                "user": "hello",
                "assistant": "hi",
            },
            client=client,
        )
    finally:
        client.close()
    assert response["reason"] == "curation_unconfigured"
