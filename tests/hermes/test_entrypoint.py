"""T1: Verify the hermes memory-provider entry point is registered in the wheel metadata."""

import importlib.metadata


def test_entry_point_group_exists():
    """The hermes_agent.memory_providers entry-point group must exist."""
    eps = importlib.metadata.entry_points()
    groups = eps.groups if hasattr(eps, "groups") else []
    assert "hermes_agent.memory_providers" in groups


def test_entry_point_maps_to_luminary_module():
    """The luminary entry point must resolve to the provider package."""
    eps = importlib.metadata.entry_points()
    group = eps.select(group="hermes_agent.memory_providers") if hasattr(eps, "select") else [
        e for e in eps if e.group == "hermes_agent.memory_providers"
    ]
    matches = [e for e in group if e.name == "luminary"]
    assert matches, "no 'luminary' entry point under hermes_agent.memory_providers"
    assert matches[0].value == "luminary_memory.hermes"
