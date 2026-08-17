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

**Reciprocal Rank Fusion (RRF)** combines the four ranked lists:

```
score(m) = Σ 1 / (k + rank(m) + 1)
```

`k` is configurable (`LUMINARY_RRF_K`, default 60).

## Dedup

Jaccard similarity (token overlap) removes near-duplicates above a threshold (`LUMINARY_DEDUP_JACCARD_THRESHOLD`, default 0.85).

## Budget

Results are truncated to a token budget (`LUMINARY_TOKEN_BUDGET`, default 4096) so memory injection never overflows the agent's context.

## Tuning

| Knob | Env var | Effect |
|------|---------|--------|
| `rrf_k` | `LUMINARY_RRF_K` | higher = smoother fusion across strategies |
| `dedup_jaccard_threshold` | `LUMINARY_DEDUP_JACCARD_THRESHOLD` | lower = more aggressive dedup |
| `token_budget` | `LUMINARY_TOKEN_BUDGET` | caps total injected tokens |
| `embedding_model` | `LUMINARY_EMBEDDING_MODEL` | quality/speed tradeoff |
