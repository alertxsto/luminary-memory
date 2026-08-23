from luminary_memory.hermes.activation import activate_config, main


def test_activation_preserves_unrelated_yaml_and_is_idempotent(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "models:\n"
        "  provider: command-code\n"
        "memory:\n"
        "  provider: old\n"
        "  keep: yes\n"
        "tools:\n"
        "  enabled: true\n",
        encoding="utf-8",
    )

    activate_config(path)
    first = path.read_text(encoding="utf-8")
    activate_config(path)

    assert path.read_text(encoding="utf-8") == first
    assert first == (
        "models:\n"
        "  provider: command-code\n"
        "memory:\n"
        "  provider: luminary\n"
        "  keep: yes\n"
        "  memory_enabled: false\n"
        "  user_profile_enabled: false\n"
        "tools:\n"
        "  enabled: true\n"
    )


def test_activation_creates_a_minimal_config(tmp_path):
    path = tmp_path / "nested" / "config.yaml"

    activate_config(path)

    assert path.read_text(encoding="utf-8") == (
        "memory:\n"
        "  provider: luminary\n"
        "  memory_enabled: false\n"
        "  user_profile_enabled: false\n"
    )


def test_activation_rejects_inline_memory_mapping(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("memory: {provider: old}\n", encoding="utf-8")

    try:
        activate_config(path)
    except ValueError as exc:
        assert "inline YAML mapping" in str(exc)
    else:
        raise AssertionError("inline memory mappings must not be rewritten implicitly")


def test_activation_help_is_non_mutating(capsys):
    assert main(["--help"]) == 0
    assert "usage:" in capsys.readouterr().out
