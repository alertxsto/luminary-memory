"""Scoped durable event pages and bounded reconnect replay."""
from luminary_memory.backends.inspector_features import InspectorFeatureQueries
from luminary_memory.inspector import queries
from luminary_memory.inspector.identity import digest


def events(service, context, request):
    authorization = service.authorizer(context, request)
    memory_id = queries._event_memory(service, authorization, request)
    scopes = authorization.scopes("read")
    features = InspectorFeatureQueries(service.client.backend)
    binding = digest({"purpose": "activity-replay", "context": context.context_epoch,
                      "project": authorization.project_id, "policy": authorization.policy_revision,
                      "memory_id": memory_id})
    since = request.arguments.get("since_event_id")
    if since is None:
        page = queries.history(service, context, request)
        head, count = features.event_position(scopes, memory_id=memory_id)
        page.update(snapshot_boundary=head, replayed=False,
                    replay_context=queries._cursor(context, binding, [head, count]))
        return page
    if type(since) is not int or since < 0:
        raise ValueError("invalid event boundary")
    witnessed = 0
    token = request.arguments.get("replay_context")
    if since > 0 or token is not None:
        proof = queries.decode_token(context, token)
        if not isinstance(proof, dict) or proof.get("binding") != binding:
            raise ValueError("replay context changed")
        position = proof.get("after")
        if (not isinstance(position, list) or len(position) != 2
                or any(type(value) is not int or value < 0 for value in position)
                or position[0] != since):
            raise ValueError("replay boundary disagrees with its context")
        witnessed = position[1]
    limit, _, _ = queries._page(service, context, request, authorization)
    _, current_count = features.event_position(scopes, through=since, memory_id=memory_id)
    if current_count != witnessed:
        return {"items": [], "next_event_id": since, "has_more": False, "replayed": True,
                "gap": True, "snapshot_required": True, "replay_context": None}
    items, more = features.events_since(scopes, since, limit, memory_id=memory_id)
    items = [queries.event_view(row, authorization) for row in items]
    boundary = items[-1]["event_id"] if items else since
    return {"items": items, "next_event_id": boundary, "has_more": more, "replayed": True,
            "replay_context": queries._cursor(context, binding, [boundary, current_count + len(items)]),
            "gap": False, "snapshot_required": False,
            "retention": "append-only scoped event ledger; missing witnessed history requires a new snapshot"}


def graph(service, context, request):
    authorization = service.authorizer(context, request)
    limit, binding, after = queries._page(service, context, request, authorization)
    entity = request.arguments.get("entity_id")
    if entity is not None and (type(entity) is not int or entity < 1):
        raise ValueError("invalid entity reference")
    page = InspectorFeatureQueries(service.client.backend).graph(
        authorization.scopes("read"), entity_id=entity, after=after or 0, limit=limit,
    )
    boundary = page.pop("after")
    page["next_cursor"] = queries._cursor(context, binding, boundary) if boundary else None
    page["focus_entity_id"] = entity
    page["ranking_status"] = "not_recorded"
    page["weight_basis"] = "Graph co-occurrence weights are not recall ranking scores."
    return page
