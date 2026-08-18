# Recall

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
