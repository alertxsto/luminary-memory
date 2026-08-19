# Recall

## Core memory (DB-backed, auto-loaded)

Rules tagged `core` are injected into the system prompt **every session**,
regardless of query match (the DB-backed equivalent of Hermes' `MEMORY.md`).
All other memories are surfaced through query retrieval only:

```
Core memory (auto-loaded every session):   <- always present, subordinate to live instruction
- <durable rule 1>
- <durable rule 2>

# Luminary Memory (persistent cross-session context)   <- query-recall block
- <query-relevant memory>                  <- skips anything already injected above
```

> Persistent-context injection (top-N by importance every turn) was **removed
> in v0.2.18**. Importance now scores query relevance and drives pruning only —
> it does not pin memory into the prompt as rules that override a live user
> instruction. Use the `core` tag for rules that must always be present.

Anti-duplication: memory ids injected by the core block are tracked per
turn and skipped by the query-recall block, so no memory appears twice in one
turn's context.

## Four strategies

`recall(query)` runs four complementary strategies in parallel and fuses them. No single query style dominates.

### 1. Semantic

Embedding similarity between the query and stored memories. Handles paraphrasing, synonyms, and conceptual matches.

### 2. Keyword

FTS5 (SQLite) or `ILIKE` (pgvector) term matching. Handles exact names, proper nouns, and technical terms.

### 3. Temporal

Recency decay × access popularity:

```
score = exp(-age_hours / half_life_hours) × (1 + log1p(access_count))
```

Handles "what did we do recently?" and surfaces frequently-used memories.

### 4. Graph

Entity co-occurrence traversal. Entities are extracted from tags + content; edges link co-occurring entities. Handles indirect relationships ("what's related to X?").

## Fusion

**Weighted Reciprocal Rank Fusion (RRF)** combines the four ranked lists.
Each strategy carries a weight so high-signal strategies dominate:

```
score(m) = Σ weight(strategy) / (k + rank(m) + 1)
```

| Strategy | Weight | Why |
|----------|--------|-----|
| semantic | 0.4 | matches meaning, strongest signal |
| keyword  | 0.3 | exact match |
| graph    | 0.2 | entity co-occurrence |
| temporal | 0.1 | recency/popularity only, kept low so "recent but irrelevant" cannot top the ranking |

`k` is configurable (`LUMINARY_RRF_K`, default 60). The query planner
additionally gates strategies: temporal is skipped when a strong keyword
match exists, and graph is skipped when the query has no entity tokens.

## Query expansion

Short queries ("deploy?") produce weak embeddings. Before semantic search,
the query is expanded with co-occurring entity names from the knowledge
graph, so relevant memories rank higher (`_expand_query`, best-effort , 
falls back to the raw query on any error).

When the graph yields nothing, **rule-aware expansion (v0.2.15)** kicks in:
if the query touches the topic of a durable rule (high-importance memory), up
to two of its keywords are appended so the rule surfaces in semantic recall
even when the query uses different words. Both expansions keep the original
query tokens, so recall quality can never get worse than baseline.


## Adaptive importance (v0.2.15)

Memories that keep getting recalled have their importance re-estimated immediately during the recall pass (based on access count and recency). This allows frequently accessed facts to naturally climb in score and rank higher in the next turn's query recall, adapting to the agent's current focus.

## Adaptive cutoff

After fusion, the ranked list is cut at the first **steep score drop**
(cliff detection). Only the relevant cluster survives:

```
if (prev_score - cur_score) / prev_score >= cliff_threshold: cut here
```

| Behavior | Example |
|----------|---------|
| Sparse store | 3 strong matches among 20 candidates → returns 3, not padded to the limit |
| Dense relevant store | 15 all-relevant candidates → keeps all 15 (no over-filtering) |

Threshold configurable via `LUMINARY_RECALL_CLIFF_THRESHOLD` (default `0.45`).

## Dedup

Jaccard similarity (token overlap) removes near-duplicates above a threshold (`LUMINARY_DEDUP_JACCARD_THRESHOLD`, default 0.85).

## Budget

Results are truncated to a token budget (`LUMINARY_TOKEN_BUDGET`, default 4096) so memory injection never overflows the agent's context.

## Tuning

| Knob | Env var | Effect |
|------|---------|--------|
| `rrf_k` | `LUMINARY_RRF_K` | higher = smoother fusion across strategies |
| `strategy_weights` | `LUMINARY_WEIGHT_{SEMANTIC,KEYWORD,GRAPH,TEMPORAL}` | per-strategy fusion weight (default 0.4/0.3/0.2/0.1) |
| `recall_cliff_threshold` | `LUMINARY_RECALL_CLIFF_THRESHOLD` | higher = more aggressive adaptive cutoff (default 0.45) |
| `dedup_jaccard_threshold` | `LUMINARY_DEDUP_JACCARD_THRESHOLD` | lower = more aggressive dedup |
| `token_budget` | `LUMINARY_TOKEN_BUDGET` | caps total injected tokens |
| `embedding_model` | `LUMINARY_EMBEDDING_MODEL` | quality/speed tradeoff |
| `importance_recall_boost` | `LUMINARY_IMPORTANCE_RECALL_BOOST` | ranking bonus for memories at importance ≥ 0.8 (default 1.0) |

> Persistent-context knobs (`context_top_n`, `context_budget`,
> `context_min_importance`) were removed in v0.2.18 — importance is now used
> only for query retrieval/recall and pruning, never to pin rules per turn.

## Performance

Recall runs four strategies in parallel and fuses them. On a 5k-memory store
(SQLite, local CPU embeddings):

| Stage | Typical latency |
|-------|-----------------|
| End-to-end recall | ~70–95 ms (p50), deterministic quality (MRR 1.0 on synthetic) |
| Semantic (vectorized cosine matmul) | ~35–50 ms |
| Keyword (FTS5 BM25) | ~2–5 ms |
| Temporal (batched fetch) | ~16–20 ms |
| Graph (SQL aggregation) | ~20–25 ms |
| Core memory (tag 'core', auto-load) | ~5 ms |

Per-turn bookkeeping (access-count bump) is batched into one UPDATE statement,
so agent turns stay cheap.
