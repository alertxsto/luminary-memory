"""Secret-free effective configuration and explicit profile-local changes."""
import json


def test_config_response_never_contains_credentials(scenario):
    scenario.client.settings.llm_api_key = "API_KEY_MUST_NOT_LEAK"
    scenario.client.settings.pg_dsn = "postgresql://owner:DSN_PASSWORD@host/db"
    scenario.client.settings.llm_base_url = "https://name:URL_PASSWORD@api.example/v1?key=QUERY_KEY"
    result = scenario.request("get_settings")
    assert result.status == "ok", result.to_dict()
    body = json.dumps(result.to_dict())
    for secret in ("API_KEY_MUST_NOT_LEAK", "DSN_PASSWORD", "URL_PASSWORD", "QUERY_KEY"):
        assert secret not in body
    assert result.data["secret_presence"]["llm_api_key"] is True


def test_preferences_roundtrip_preserves_saving_and_other_profile(scenario):
    original = scenario.client.settings.ingest_llm
    settings = scenario.request("get_settings").data
    preview = scenario.request("preview_change", kind="set_settings", changes={"page_size": 7}, expected_revision=settings["revision"])
    assert preview.status == "ok", preview.to_dict()
    receipt = scenario.service.confirm(scenario.context, preview.data["preview_id"])
    committed = scenario.request("set_settings", preview_id=preview.data["preview_id"], confirmation_receipt=receipt)
    assert committed.status == "ok", committed.to_dict()
    assert scenario.request("get_settings").data["values"]["page_size"] == 7
    assert scenario.client.settings.ingest_llm == original
    stale = scenario.request("preview_change", kind="set_settings", changes={"page_size": 10}, expected_revision=settings["revision"])
    assert stale.status == "conflict"
    from luminary_memory.api import MemoryClient
    from luminary_memory.inspector.identity import resolve_context
    from luminary_memory.inspector.service import InspectorService

    binding = scenario.preview("bind_location", location={
        "host_id": scenario.native["host_id"], "profile_id": "sibling",
        "workspace": scenario.native["workspace"],
    })
    assert scenario.commit(binding).status == "ok"
    sibling = resolve_context(scenario.client, {**scenario.native, "profile_id": "sibling"})
    assert scenario.request("get_settings", context=sibling).data["values"]["page_size"] == 50
    previous = scenario.client
    backend, engine, enricher, scope = previous.backend, previous.engine, previous.enricher, previous.scope
    previous.close()
    backend = (type(backend)(backend.dsn, embedding_dim=backend.embedding_dim, hnsw=False)
               if hasattr(backend, "_psycopg") else type(backend)(previous.settings.db_path))
    scenario.client = MemoryClient(settings=previous.settings, backend=backend, engine=engine,
                                   enricher=enricher, scope=scope)
    scenario.service = InspectorService(scenario.client)
    scenario.context = resolve_context(scenario.client, scenario.native)
    assert scenario.request("get_settings").data["values"]["page_size"] == 7
    assert scenario.request("get_settings", context=sibling).data["values"]["page_size"] == 50
    assert scenario.client.settings.ingest_llm == original


def test_unsupported_setting_cannot_enable_retention(scenario):
    before = scenario.client.settings.ingest_llm
    result = scenario.request("preview_change", kind="set_settings", changes={"ingest_llm": not before}, expected_revision=0)
    assert result.status in {"unsupported", "invalid_request", "denied"}
    assert scenario.client.settings.ingest_llm == before


def test_saved_page_preferences_change_real_views_and_invalidate_old_page_cursor(scenario):
    scenario.client.ingest("Another authorized page record", enrich=False)
    settings = scenario.request("get_settings").data
    preview = scenario.request("preview_change", kind="set_settings",
                               changes={"page_size": 1, "activity_limit": 1},
                               expected_revision=settings["revision"])
    receipt = scenario.service.confirm(scenario.context, preview.data["preview_id"])
    result = scenario.request("set_settings", preview_id=preview.data["preview_id"],
                              confirmation_receipt=receipt)
    assert result.status == "ok", result.to_dict()
    page = scenario.request("browse")
    assert len(page.data["items"]) == 1
    assert page.data["next_cursor"]
    second = scenario.request("browse", cursor=page.data["next_cursor"])
    assert len(second.data["items"]) == 1
    assert second.data["items"][0]["id"] != page.data["items"][0]["id"]
    assert len(scenario.request("events").data["items"]) == 1
    newer = scenario.request("preview_change", kind="set_settings", changes={"page_size": 2},
                             expected_revision=result.data["revision"])
    receipt = scenario.service.confirm(scenario.context, newer.data["preview_id"])
    changed = scenario.request("set_settings", preview_id=newer.data["preview_id"],
                               confirmation_receipt=receipt)
    assert changed.status == "ok"
    assert len(scenario.request("browse").data["items"]) == 2
    assert scenario.request("browse", cursor=page.data["next_cursor"]).status == "invalid_request"


def test_unselected_explanation_model_cannot_create_an_outbound_disclosure(scenario):
    scenario.client.settings.llm_base_url = "http://127.0.0.1:1/v1"
    scenario.client.settings.llm_model = "   "
    result = scenario.request("explain", phase="preview")
    assert result.status == "unavailable", result.to_dict()
    assert result.data is None
