"""Copy-installer and companion CLI behaviour, without touching an operator profile."""
from __future__ import annotations

import json
import socket

import pytest
import typer


def test_install_refuses_an_unknown_agent(tmp_path):
    from luminary_memory.integrations.cli import install

    with pytest.raises(typer.Exit):
        install("unknown-agent", tmp_path, False, False)
    assert list(tmp_path.iterdir()) == []


def test_install_refuses_ambiguous_targets(tmp_path):
    from luminary_memory.integrations.cli import install

    with pytest.raises(typer.Exit):
        install("pi", tmp_path, True, False)


def test_install_reports_a_refused_legacy_cutover(tmp_path, monkeypatch):
    from luminary_memory.integrations import cli

    def refuse(agent, directory, force=False):
        raise ValueError("Legacy Luminary hook exists; --force performs the explicit package cutover")

    monkeypatch.setattr(cli, "install_adapter", refuse)
    with pytest.raises(typer.Exit):
        cli.install("pi", tmp_path, False, False)


@pytest.mark.parametrize("agent", ["pi", "omp", "opencode"])
def test_install_writes_a_complete_native_package(agent, tmp_path):
    from luminary_memory.integrations.cli import install

    install(agent, tmp_path, False, False)
    folder = tmp_path / ("plugins" if agent == "opencode" else "extensions")
    installed = folder / "luminary-memory"
    assert (installed / "index.js").is_file()
    manifest = json.loads((installed / "package.json").read_text(encoding="utf-8"))
    assert (manifest["name"], manifest["type"]) == (f"luminary-memory-{agent}", "module")
    if agent != "opencode":
        assert manifest[agent] == {"extensions": ["./index.js"]}


def test_companion_registers_no_browser_without_explicit_open(tmp_path, monkeypatch):
    from luminary_memory.integrations import cli

    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
    monkeypatch.setattr("luminary_memory.inspector.web.CompanionServer.serve_forever",
                        lambda self: (_ for _ in ()).throw(KeyboardInterrupt))
    cli.companion(agent="pi", workspace=tmp_path, session_id="session-a", profile="default",
                  port=0, open_browser=False)
    assert opened == []


def test_companion_open_browser_uses_the_single_use_owner_link(tmp_path, monkeypatch):
    from luminary_memory.integrations import cli

    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
    monkeypatch.setattr("luminary_memory.inspector.web.CompanionServer.serve_forever",
                        lambda self: (_ for _ in ()).throw(KeyboardInterrupt))
    cli.companion(agent="pi", workspace=tmp_path, session_id="session-a", profile="default",
                  port=0, open_browser=True)
    assert len(opened) == 1
    assert opened[0].startswith("http://127.0.0.1:")
    assert "#token=" in opened[0]


def test_companion_rejects_a_workspace_that_is_not_a_real_native_location(tmp_path):
    from luminary_memory.integrations import cli

    with pytest.raises(PermissionError, match="native location unavailable"):
        cli.companion(agent="pi", workspace=tmp_path / "missing", session_id="s", profile="default",
                      port=0, open_browser=False)


def test_companion_is_loopback_only(tmp_path):
    from luminary_memory.inspector.web import create_server

    server = create_server({"agent_id": "pi", "workspace": str(tmp_path), "session_id": "s",
                            "host_id": socket.gethostname(), "profile_id": "default"})
    try:
        assert server.server_address[0] == "127.0.0.1"
        assert server.bootstrap_url.startswith(f"http://127.0.0.1:{server.server_address[1]}/#token=")
    finally:
        server.server_close()
