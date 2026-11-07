"""Bounded inspector projections over the existing backend connection."""
from __future__ import annotations

from luminary_memory.types import utc_timestamp


class InspectorFeatureQueries:
    def __init__(self, backend):
        self.backend = backend

    @staticmethod
    def predicate(scopes, alias="m"):
        if not scopes:
            return "1=0", []
        clauses, values = [], []
        for scope in scopes:
            clauses.append(f"({alias}.user_id=? AND {alias}.workspace_id=? AND {alias}.agent_id=?)")
            values.extend(scope[key] for key in ("user_id", "workspace_id", "agent_id"))
        return "(" + " OR ".join(clauses) + ")", values

    def summary(self, scopes):
        where, values = self.predicate(scopes)
        statuses = ("active", "candidate", "conflicted", "superseded", "expired", "deleted")
        columns = ["COUNT(*)"] + [
            f"COALESCE(SUM(CASE WHEN m.status='{status}' THEN 1 ELSE 0 END),0)" for status in statuses
        ]
        # SQLite stores text: normalize offsets before MIN/MAX, preserving microseconds.
        created, updated = ("m.created_at", "m.updated_at")
        if not hasattr(self.backend, "_psycopg"):
            created, updated = (f"inspector_utc({column})" for column in (created, updated))
        columns.extend((f"MIN({created})", f"MAX({created})", f"MIN({updated})", f"MAX({updated})",
                        f"COALESCE(SUM(CASE WHEN {created} IS NULL OR {updated} IS NULL THEN 1 ELSE 0 END),0)"))
        table = self.backend._inspector_table("memories")
        row = self.backend._sql(f"SELECT {','.join(columns)} FROM {table} m WHERE {where}", values).fetchone()
        totals = dict(zip(("memories", *statuses), (int(value) for value in row[:7])))
        bounds = dict(zip(("created_from", "created_to", "updated_from", "updated_to"),
                          (utc_timestamp(value) for value in row[7:11])))
        bounds["status"] = "partial" if row[11] else "available" if totals["memories"] else "empty"
        return {"totals": totals, "time_range": bounds}

    def graph(self, scopes, *, entity_id=None, after=0, limit=100):
        where, values = self.predicate(scopes)
        if entity_id is not None:
            where += " AND (r.source_id=? OR r.target_id=?)"
            values.extend((entity_id, entity_id))
        values.extend((after, limit + 1))
        relations = self.backend._inspector_table("relations")
        memories = self.backend._inspector_table("memories")
        entities = self.backend._inspector_table("entities")
        rows = self.backend._sql(
            "SELECT r.id,r.source_id,s.name,r.target_id,t.name,r.relation_type,r.weight,r.memory_id "
            f"FROM {relations} r JOIN {memories} m ON m.id=r.memory_id "
            f"JOIN {entities} s ON s.id=r.source_id JOIN {entities} t ON t.id=r.target_id "
            "WHERE " + where + " AND m.status='active' AND r.id>? ORDER BY r.id LIMIT ?", values,
        ).fetchall()
        page = rows[:limit]
        nodes, edges, adjacency = {}, [], []
        for edge_id, source, source_label, target, target_label, relation, weight, memory_id in page:
            nodes[source] = {"id": source, "label": source_label[:128]}
            nodes[target] = {"id": target, "label": target_label[:128]}
            edges.append({"id": edge_id, "source": source, "target": target, "kind": relation,
                          "weight": float(weight), "memory_id": memory_id})
            adjacency.append({"source": source_label[:128], "target": target_label[:128],
                              "kind": relation, "memory_id": memory_id})
        return {"nodes": list(nodes.values()), "edges": edges, "items": adjacency,
                "after": page[-1][0] if len(rows) > limit else None,
                "label": "Co-occurrence, not causation"}

    def events_since(self, scopes, since, limit, *, memory_id=None):
        where, values = self.predicate(scopes, "e")
        if memory_id is not None:
            where += " AND e.memory_id=?"
            values.append(memory_id)
        values.extend((since, limit + 1))
        rows = self.backend._sql(
            "SELECT e.id,e.memory_id,e.event_type,e.created_at,e.before_json,e.after_json,e.actor FROM memory_events e WHERE "
            + where + " AND e.id>? ORDER BY e.id LIMIT ?", values,
        ).fetchall()
        return [dict(zip(("event_id", "memory_id", "kind", "created_at", "before", "after", "actor"), row))
                for row in rows[:limit]], len(rows) > limit

    def event_position(self, scopes, *, through=None, memory_id=None):
        where, values = self.predicate(scopes, "e")
        if memory_id is not None:
            where += " AND e.memory_id=?"
            values.append(memory_id)
        if through is not None:
            where += " AND e.id<=?"
            values.append(through)
        head, count = self.backend._sql(
            "SELECT COALESCE(MAX(e.id),0),COUNT(*) FROM memory_events e WHERE " + where, values,
        ).fetchone()
        return int(head), int(count)
