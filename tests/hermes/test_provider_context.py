"""v0.2.18: importance repurposed to retrieval-only.

Covers persistent-context decoupling and noise filtering. Live user
instructions remain the highest-priority input at the agent boundary; the
provider deliberately does not classify commands by a hardcoded language
vocabulary.
"""

from types import SimpleNamespace

from luminary_memory.hermes.provider import (
    LuminaryMemoryProvider,
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
# Core block carries an explicit durable-context authority boundary
# --------------------------------------------------------------------------- #


def test_core_block_authority_boundary(tmp_path):
    p = _init_provider(tmp_path)
    p._client.ingest("Always use bullet points", tags=["core"])
    out = p.prefetch("anything", "s1")
    assert "curated persistent context" in out
    assert "current user explicitly corrects" in out
    assert "never higher-priority system instruction" in out
    assert "Core memory" in out
    p.shutdown()


def test_provider_declares_single_memory_authority(tmp_path):
    p = _init_provider(tmp_path)

    # Hermes' public provider contract asks the external provider whether it
    # owns the persistent memory surface. Luminary must answer explicitly so
    # native files are not combined with the DB-backed core.
    assert p.replaces_builtin_memory() is True

    p.shutdown()


def test_post_setup_disables_native_surfaces_idempotently(tmp_path):
    p = LuminaryMemoryProvider()
    config = tmp_path / "config.yaml"
    config.write_text(
        "models:\n"
        "  provider: command-code\n"
        "memory:\n"
        "  provider: old\n"
        "  memory_enabled: true\n"
        "  user_profile_enabled: true\n"
        "  keep: yes\n"
        "tools:\n"
        "  enabled: true\n",
        encoding="utf-8",
    )

    p.post_setup(str(tmp_path), {"memory": {"provider": "old"}})

    assert config.read_text(encoding="utf-8") == (
        "models:\n"
        "  provider: command-code\n"
        "memory:\n"
        "  provider: luminary\n"
        "  memory_enabled: false\n"
        "  user_profile_enabled: false\n"
        "  keep: yes\n"
        "tools:\n"
        "  enabled: true\n"
    )
    assert (tmp_path / "luminary" / "config.json").exists()


def test_post_setup_activates_existing_profiles_without_creating_new_ones(tmp_path):
    profiles = tmp_path / "profiles"
    (profiles / "telegram").mkdir(parents=True)
    (profiles / "telegram" / "config.yaml").write_text(
        "memory:\n"
        "  provider: cline\n"
        "  memory_enabled: true\n"
        "  user_profile_enabled: true\n",
        encoding="utf-8",
    )

    p = LuminaryMemoryProvider()
    p.post_setup(str(tmp_path), {"memory": {}})

    profile = (profiles / "telegram" / "config.yaml").read_text(encoding="utf-8")
    assert "provider: luminary" in profile
    assert "memory_enabled: false" in profile
    assert "user_profile_enabled: false" in profile
    assert not (profiles / "default" / "config.yaml").exists()


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
    assert not _is_noise_memory("The agent uses && in JavaScript conditions for feature flags.")
    assert not _is_noise_memory("Use the === operator for strict comparisons in JavaScript.")
    assert not _is_noise_memory("The HTML response includes a <main> element.")
