from __future__ import annotations

ALL_STRATEGIES = frozenset({"semantic", "keyword", "temporal", "graph"})


def plan_strategies(
    query: str,
    keyword_top_score: float | None = None,
    planner: bool = True,
    keyword_threshold: float = 0.9,
) -> frozenset[str]:
    """Decide which recall strategies to run for *query*.

    Conservative v1 heuristics:
    - Skip **graph** when the query yields no entity tokens (graph_recall
      already returns [] in that case).
    - Skip **temporal** when a strong keyword match is present
      (``keyword_top_score >= keyword_threshold``).
    - Never skip **semantic** or **keyword**.
    - Never skip anything when ``planner`` is False.
    """
    if not planner:
        return ALL_STRATEGIES

    enabled: set[str] = set(ALL_STRATEGIES)

    # Graph guard: no entities -> no graph.
    try:
        from luminary_memory.recall.graph import _query_entities

        if not _query_entities(query or ""):
            enabled.discard("graph")
    except Exception:  # noqa: BLE001, S110
        pass

    # Temporal guard: strong keyword hit makes recency noise.
    if keyword_top_score is not None:
        try:
            if float(keyword_top_score) >= float(keyword_threshold):
                enabled.discard("temporal")
        except Exception:  # noqa: BLE001, S110
            pass

    # Invariant: semantic + keyword never skipped.
    enabled.add("semantic")
    enabled.add("keyword")
    return frozenset(enabled)
