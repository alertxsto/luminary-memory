"""v0.2.18: importance repurposed to retrieval-only.

Covers: persistent-context decoupled (default off), noise filtering, and
destructive-imperative suppression so a live instruction always wins.
"""

from types import SimpleNamespace

from luminary_memory.hermes.provider import (
    LuminaryMemoryProvider,
    _is_destructive_imperative,
    _is_noise_memory,
)


def _init_provider(tmp_path, mode="hybrid"):
    p = LuminaryMemoryProvider()
    p.initialize("s1", hermes_home=str(tmp_path), platform="cli")
    p._config["mode"] = mode
    return p


def _fake_memory(mid, content):
    return SimpleNamespace(id=mid, content=content, importance=0.95, tags=[])


# --------------------------------------------------------------------------- #
# Core block carries an explicit subordinate label
# --------------------------------------------------------------------------- #


def test_core_block_subordinate_label(tmp_path):
    p = _init_provider(tmp_path)
    p._client.ingest("Always use bullet points", tags=["core"])
    out = p.prefetch("anything", "s1")
    assert "subordinate" in out
    assert "Core memory" in out
    p.shutdown()


# --------------------------------------------------------------------------- #
# Noise filtering in recall formatting
# --------------------------------------------------------------------------- #


def test_recall_filters_shell_noise(tmp_path):
    p = _init_provider(tmp_path)
    good = _fake_memory(1, "The deploy target is the staging cluster.")
    bad_shell = _fake_memory(2, "ls -la && echo === checking === folderdump")
    out = p._format_recall_block([good, bad_shell], [0.9, 0.8])
    assert "deploy target" in out
    assert "&&" not in out
    assert "echo === checking" not in out
    p.shutdown()


def test_is_noise_memory_flags_artifacts():
    assert _is_noise_memory("ls -la && echo === test ===")
    assert _is_noise_memory("short")
    assert not _is_noise_memory("The deploy target is the staging cluster.")
    assert not _is_noise_memory("User prefers concise bullet responses.")


# --------------------------------------------------------------------------- #
# Destructive-imperative detection + suppression in prefetch
# --------------------------------------------------------------------------- #


def test_destructive_imperative_detected():
    for q in ("hapus A", "delete A", "remove the file", "stop reminder", "matikan cron"):
        assert _is_destructive_imperative(q), q
    for q in ("bagaimana cara deploy", "sebutkan project aktif", "apa itu luminary"):
        assert not _is_destructive_imperative(q), q


def test_destructive_imperative_suppresses_recall(tmp_path, monkeypatch):
    p = _init_provider(tmp_path)
    p._config["recall_sync"] = True
    p._config["auto_recall"] = True

    fake_result = SimpleNamespace(
        memories=[_fake_memory(1, "The item A is very important, keep it always.")],
        scores=[0.97],
    )

    def fake_recall(query, **kw):
        return fake_result

    monkeypatch.setattr(p._client, "recall", fake_recall)

    # Non-destructive query -> recall block is surfaced.
    out_normal = p.prefetch("apakah A penting?", "s1")
    assert "item A" in out_normal

    # Destructive query -> recall block is suppressed entirely.
    out_del = p.prefetch("hapus A", "s1")
    assert "Recalled relevant memories" not in out_del
    p.shutdown()