"""Embedded inspector path: authority already resolved by the native host."""
from __future__ import annotations

import pytest

from luminary_memory.inspector.contracts import ConsoleRequest


def request(**arguments):
    return ConsoleRequest(operation="browse", arguments=arguments, request_id="embedded-1")


def test_embedded_path_requires_an_explicitly_scoped_client(scenario):
    from luminary_memory.integrations.inspector_cli import run_inspector

    with pytest.raises(ValueError, match="explicitly configured scoped client"):
        run_inspector(scenario.context, request())


def test_embedded_path_executes_against_the_resolved_context(scenario):
    from luminary_memory.integrations.inspector_cli import run_inspector

    result = run_inspector(scenario.context, request(), client=scenario.client)
    assert result.status == "ok"
    assert [row["id"] for row in result.data["items"]] == [scenario.own_id]


def test_embedded_confirmation_returns_a_receipt_for_the_preview(scenario):
    from luminary_memory.integrations.inspector_cli import run_inspector

    preview = scenario.preview("grant", recipient_agent_id="omp", capabilities=["read"])
    result = run_inspector(scenario.context, ConsoleRequest(operation="mutate", arguments={}, request_id="embedded-2"),
                           client=scenario.client, confirmation=preview)
    assert result.status == "ok"
    assert result.data["preview_id"] == preview
    assert result.data["confirmation_receipt"]
    assert result.data["confirmation_receipt"] != preview


def test_embedded_path_cannot_read_a_foreign_scope(scenario):
    from luminary_memory.integrations.inspector_cli import run_inspector

    result = run_inspector(scenario.context, ConsoleRequest(operation="detail", arguments={"memory_id": scenario.foreign_id},
                                                            request_id="embedded-3"), client=scenario.client)
    assert result.status in {"denied", "invalid_request"}
    assert result.data is None
