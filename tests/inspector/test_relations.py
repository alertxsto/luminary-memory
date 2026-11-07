"""Graph projections must not leak a shared label's foreign neighbors."""
import json
import uuid


def test_foreign_shared_entity_does_not_leak_graph_neighborhood(scenario):
    from luminary_memory.recall.graph import index_memory_entities
    own = scenario.client.backend.get(scenario.own_id)
    other = scenario.client.backend.get(scenario.foreign_id)
    own.content = "Luminary deploys to Production."
    other.content = "Luminary stores BOB_SECRET at PrivateCluster."
    scenario.client.backend.update(own)
    scenario.client.backend.update(other)
    index_memory_entities(scenario.client.backend, own)
    index_memory_entities(scenario.client.backend, other)
    result = scenario.request("graph")
    assert result.status == "ok", result.to_dict()
    body = json.dumps(result.to_dict()).casefold()
    assert "bob_secret" not in body
    assert "privatecluster" not in body
    assert all(edge["memory_id"] == scenario.own_id for edge in result.data["edges"])


def test_entity_expansion_ranks_unique_authorized_neighbors_by_strongest_edge(scenario):
    from luminary_memory.recall.graph import index_memory_entities
    from luminary_memory.recall.semantic import _expand_with_entities
    from luminary_memory.types import Memory

    backend = scenario.client.backend
    own = backend.get(scenario.own_id)
    own.content = "Luminary AlphaNode BetaNode"
    backend.update(own)
    sibling = Memory(content="Luminary AlphaNode", **scenario.client.scope)
    sibling.id = backend.add(sibling)
    foreign = backend.get(scenario.foreign_id)
    foreign.content = "Luminary SecretNode"
    backend.update(foreign)
    for memory in (own, sibling, foreign):
        index_memory_entities(backend, memory)
    with backend.transaction():
        for memory, target, weight in ((own, "alphanode", 2.0), (sibling, "alphanode", 2.0),
                                       (own, "betanode", 3.0), (foreign, "secretnode", 100.0)):
            backend._sql("UPDATE relations SET weight=? WHERE memory_id=? AND "
                         "target_id=(SELECT id FROM entities WHERE name=?)",
                         (weight, memory.id, target))
    expanded = _expand_with_entities(backend, "luminary", ["luminary"], 1,
                                     scope=scenario.client.scope, include_global=False)
    assert expanded == "luminary betanode"


def test_missing_graph_storage_is_unavailable_not_a_healthy_empty_graph(scenario):
    backend = scenario.client.backend
    fallback = original_path = None
    if hasattr(backend, "_psycopg"):
        from psycopg import sql

        namespace = backend.conn.execute("SELECT current_schema()").fetchone()[0]
        original_path = backend.conn.execute("SHOW search_path").fetchone()[0]
        fallback = "graph_fallback_" + uuid.uuid4().hex
        backend.conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(fallback)))
        backend.conn.execute(sql.SQL("CREATE TABLE {} (LIKE {})").format(
            sql.Identifier(fallback, "relations"), sql.Identifier(namespace, "relations")))
        path = ",".join(sql.Identifier(name).as_string(backend.conn) for name in (namespace, fallback, "public"))
        backend.conn.execute("SELECT set_config('search_path',%s,false)", (path,))
    try:
        with backend.transaction():
            backend._sql("DROP TABLE relations")
        result = scenario.request("graph")
        assert result.status == "unavailable", result.to_dict()
        assert result.data is None
    finally:
        if fallback:
            backend.conn.execute("SELECT set_config('search_path',%s,false)", (original_path,))
            backend.conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(fallback)))
