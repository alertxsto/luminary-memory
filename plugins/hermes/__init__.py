"""Ordinary inspector plugin, never a memory-provider registration."""


def register(ctx):
    from luminary_memory.hermes.cli import register_cli

    ctx.register_cli_command(
        "luminary-inspector",
        "Configure profile-local Luminary settings or bind an exact owner-approved inspector scope",
        register_cli,
    )
