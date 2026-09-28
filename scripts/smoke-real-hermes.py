#!/usr/bin/env python3
"""Isolated release smoke: installed upstream Hermes MemoryManager drives Luminary."""

import importlib.metadata
import sqlite3
import tempfile
import time
from pathlib import Path

from agent.memory_manager import MemoryManager
from agent.memory_provider import MemoryProvider


def main() -> None:
    host = importlib.metadata.distribution("hermes-agent")
    assert host.version, "upstream Hermes distribution is not installed"
    distribution = importlib.metadata.distribution("luminary-memory")
    entries = [
        entry for entry in distribution.entry_points
        if entry.group == "hermes_agent.memory_providers" and entry.name == "luminary"
    ]
    assert len(entries) == 1, "Luminary's installed Hermes entry point is missing"
    module = entries[0].load()
    provider = module.LuminaryMemoryProvider()
    assert isinstance(provider, MemoryProvider), "entry point does not implement the real Hermes contract"
    assert provider.replaces_builtin_memory() and provider.is_available()

    with tempfile.TemporaryDirectory(prefix="luminary-real-hermes-") as home:
        manager = MemoryManager()
        manager.add_provider(provider)
        manager.initialize_all("release-session", hermes_home=home, platform="cli", user_id="release-user")
        assert provider._client is not None, "Hermes manager did not initialize the provider"
        manager.sync_all(
            "The sample launch code is sapphire.", "I will remember the sapphire launch code.",
            session_id="release-session",
        )
        episode_db = Path(home) / "luminary" / "memory.db"
        deadline = time.monotonic() + 15
        recorded = []
        while time.monotonic() < deadline:
            if episode_db.exists():
                with sqlite3.connect(episode_db) as connection:
                    recorded = connection.execute(
                        "SELECT session_id, content FROM episodes "
                        "WHERE session_id = ? AND content LIKE ?",
                        ("release-session", "%sapphire%"),
                    ).fetchall()
            if recorded:
                break
            time.sleep(0.05)
        assert recorded, "Hermes did not dispatch the completed turn to its scoped episode ledger"
        manager.on_session_end([{"role": "user", "content": "The sample launch code is sapphire."}])
        manager.shutdown_all()
        assert manager.shutdown_drain_state["status"] == "drained", "Hermes did not drain session writes"
        with sqlite3.connect(episode_db) as connection:
            episodes = connection.execute(
                "SELECT content FROM episodes WHERE session_id = ?", ("release-session",)
            ).fetchall()
        assert any("sapphire" in row[0] for row in episodes)
    print(f"real Hermes {host.version} manager + Luminary entry point: exact-session turn persisted")


if __name__ == "__main__":
    main()
