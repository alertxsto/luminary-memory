# luminary-memory

> A lightweight, self-hosted memory layer for AI agents.

**luminary-memory** gives AI agents durable, cross-session memory without shipping data to a third party. It runs entirely on your infrastructure, embeds and retrieves memories locally, and exposes a clean Python API and CLI that drop into any agent workflow. No external services required — SQLite out of the box, optional pgvector when you need scale.

---

## Why luminary-memory

Agents are only as good as what they remember. Stateless agents re-learn the same context every session; luminary-memory closes that gap with a local memory store that persists between runs, retrieves the right context on demand, and keeps itself tidy over time.

### Value proposition

- **Self-hosted and private** — all data stays on your machine. No cloud dependency, no API keys to leak, no per-token memory cost.
- **Four retrieval strategies in one recall** — semantic (embeddings), keyword (FTS5), temporal (recency/access), and graph (entity co-occurrence) run in parallel and fuse into a single ranked result.
- **Zero hard dependencies** — the default backend is SQLite + FTS5 (standard library). Embeddings run locally on CPU via ONNX. You can be ingesting and recalling memories in minutes.
- **Budget-aware by design** — results are deduplicated and truncated to a configurable token budget, so memory injection never blows up your agent's context window.
- **Self-maintaining** — a built-in lifecycle handles TTL expiry, near-duplicate consolidation, and low-value pruning, so the store stays lean without manual cleanup.
- **Scales when you do** — a pluggable backend lets you move from SQLite to pgvector without changing your code.

### Use cases

- **Long-running assistants** that need to remember user preferences, decisions, and context across sessions.
- **Coding agents** that persist project conventions, past fixes, and design decisions between tasks.
- **Research pipelines** that accumulate findings and want ranked, relevant recall over a growing corpus.
- **Multi-agent systems** that share a common memory store as a coordination layer.

### Key features

| Feature | Description |
|---|---|
| Hybrid recall | Semantic + keyword + temporal + graph strategies fused via Reciprocal Rank Fusion |
| Deduplication | Jaccard similarity removes near-identical memories before return |
| Token budget | Results clipped to a configurable token ceiling, ranked by fused score |
| Ingest control | Regex whitelist filters what enters the store; optional LLM enrichment |
| Lifecycle | TTL cleanup, consolidation, and pruning via a single command or API call |
| Pluggable backends | SQLite FTS5 (default) and pgvector (optional) |
| Two interfaces | `MemoryClient` Python API and a `typer` CLI with JSON output |

---

## Architecture

```
                    ┌─────────────────────────────────────────────┐
                    │                  luminary_memory              │
                    │                                             │
  Ingest path:      │  whitelist ──► (optional LLM) ──► embed ──►  │
  text + tags ──────►  filter        enrichment       (fastembed)  │
                    │                                             │
                    │              ┌── backend (pluggable) ──┐     │
                    │   persist ──►│ SQLite FTS5 / pgvector  │     │
                    │              └─────────────────────────┘     │
                    │                                             │
  Recall path:      │  semantic ─┐                                 │
  query ───────────►│  keyword  ─┤──► RRF fusion ─► dedup ─►       │
                    │  temporal ─┘                  (Jaccard)      │
                    │  graph    ─┘                                  │
                    │        └──► token budget ──► RecallResult    │
                    │                                             │
  Lifecycle:        │  cleanup ── consolidate ── prune (on demand) │
                    └─────────────────────────────────────────────┘

  Interfaces:  MemoryClient (Python API)   ·   luminary-memory (CLI)
```

**Ingestion pipeline** — raw text passes through a regex whitelist filter, optionally through a provider-agnostic LLM enricher (summaries, entities, tags), then is embedded locally and persisted with its content, FTS5 index, and embedding vector.

**Recall pipeline** — four strategies run in parallel, each returning a ranked list. Results are fused with Reciprocal Rank Fusion, deduplicated by Jaccard similarity, and truncated to a token budget. The result is a single ranked list of the most relevant memories.

**Lifecycle** — a dedicated runner executes cleanup (TTL expiry), consolidation (near-duplicate merge), and pruning (low-importance/LRU removal) as a single operation, exposed through both the API and CLI.

## Tech Stack

- **Python 3.11+**
- **fastembed** (ONNX CPU, `BAAI/bge-small-en-v1.5` = 384-dim)
- **sqlite3** stdlib + FTS5 (default backend)
- **psycopg[binary] + pgvector** (optional backend)
- **typer + rich** (CLI)
- **pytest**, **numpy**, **ruff** (testing, math, linting)

---

## Quickstart

```bash
git clone <repo-url> luminary-memory
cd luminary-memory
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

```python
from luminary_memory import MemoryClient

client = MemoryClient()                       # SQLite backend, default settings
client.ingest("The build uses pytest with xdist for parallel tests", tags=["testing"])

results = client.recall("how do we run tests?")
for mem in results.memories:
    print(mem.content)
```

```bash
luminary-memory add "Deploy target is the staging cluster" --tags deploy
luminary-memory recall "where do we deploy?" --limit 5 --json
```

---

# Implementation Plan (MVP — 5 days)

> **For Hermes:** use the subagent-driven-development skill to implement this plan task-by-task. Every task follows strict TDD: write a failing test first, implement, confirm the test passes, then commit.

This plan delivers a production-quality MVP in 8 phases over 5 days. Each phase builds on the last and ends with a green test suite and a clean commit.

---

## Repository Structure (Target)

```
luminary-memory/
├── pyproject.toml
├── README.md
├── LICENSE                        # Apache-2.0
├── .gitignore
├── src/luminary_memory/
│   ├── __init__.py                # exports MemoryClient, __version__
│   ├── config.py                  # Settings dataclass + env loader
│   ├── schema.py                  # DDL SQL + migration runner
│   ├── types.py                   # Memory dataclass, RecallResult, ScoredMemory
│   ├── backends/
│   │   ├── __init__.py
│   │   ├── base.py                # MemoryBackend ABC
│   │   ├── sqlite.py              # SQLite FTS5 backend
│   │   └── pgvector.py            # pgvector backend (optional)
│   ├── embeddings/
│   │   ├── __init__.py
│   │   └── fastembed.py           # EmbeddingEngine wrapper
│   ├── ingest/
│   │   ├── __init__.py
│   │   ├── whitelist.py           # regex whitelist filter
│   │   └── llm.py                 # optional LLM enrichment (provider-agnostic)
│   ├── recall/
│   │   ├── __init__.py
│   │   ├── semantic.py
│   │   ├── keyword.py
│   │   ├── temporal.py
│   │   ├── graph.py               # graph-lite (entity co-occurrence)
│   │   ├── fusion.py              # RRF
│   │   └── dedup.py               # Jaccard
│   ├── lifecycle/
│   │   ├── __init__.py
│   │   ├── cleanup.py
│   │   ├── consolidate.py
│   │   └── prune.py
│   ├── budget.py                  # token budget manager
│   ├── api.py                     # MemoryClient (public Python API)
│   └── cli.py                     # typer CLI
├── tests/
│   ├── conftest.py
│   ├── test_schema.py
│   ├── test_ingest_whitelist.py
│   ├── test_embeddings.py
│   ├── test_backend_sqlite.py
│   ├── test_recall_semantic.py
│   ├── test_recall_keyword.py
│   ├── test_recall_temporal.py
│   ├── test_recall_graph.py
│   ├── test_fusion_rrf.py
│   ├── test_dedup_jaccard.py
│   ├── test_budget.py
│   ├── test_lifecycle.py
│   ├── test_api.py
│   └── test_cli.py
└── hermes/
    └── SKILL.md                   # Hermes integration skill (day 5)
```

---

## Phase 0 — Scaffolding & CI (Day 1, morning)

### Task 0.1: Initialize project skeleton

**Objective:** A buildable Python package with pinned dependencies and test configuration.

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `src/luminary_memory/__init__.py`
- Create: `tests/__init__.py`

**Step 1: Write `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "luminary-memory"
version = "0.1.0"
description = "Self-hosted memory layer for AI agents"
readme = "README.md"
license = { text = "Apache-2.0" }
requires-python = ">=3.11"
dependencies = [
    "fastembed>=0.4.0",
    "numpy>=1.26",
    "typer>=0.12",
    "rich>=13.0",
    "psycopg[binary]>=3.1",
    "pgvector>=0.2.5",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-cov>=5.0", "ruff>=0.4"]

[project.scripts]
luminary-memory = "luminary_memory.cli:app"

[tool.hatch.build.targets.wheel]
packages = ["src/luminary_memory"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"

[tool.ruff]
line-length = 100
```

**Step 2: Write `src/luminary_memory/__init__.py`**

```python
__version__ = "0.1.0"
```

**Step 3: Install & verify**

```bash
cd luminary-memory
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -c "import luminary_memory; print(luminary_memory.__version__)"
```
Expected: `0.1.0`

**Step 4: Commit**

```bash
git init && git add -A && git commit -m "chore: scaffold luminary-memory package"
```

### Task 0.2: Configuration & core types

**Objective:** The settings model and core dataclasses shared by every module.

**Files:**
- Create: `src/luminary_memory/config.py`
- Create: `src/luminary_memory/types.py`
- Test: `tests/test_schema.py` (partial; config validated later via `test_api`)

**Step 1: Write `src/luminary_memory/types.py`**

```python
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

@dataclass
class Memory:
    id: int | None = None
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    source: str | None = None
    tags: list[str] = field(default_factory=list)
    importance: float = 0.5
    ttl_seconds: int | None = None
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    last_accessed_at: str | None = None
    access_count: int = 0
    embedding: list[float] | None = None

@dataclass
class ScoredMemory:
    memory: Memory
    score: float
    strategy: str  # "semantic" | "keyword" | "temporal" | "graph"

@dataclass
class RecallResult:
    memories: list[Memory]
    scores: list[float]
    strategies_hit: dict[str, int]
```

**Step 2: Write `src/luminary_memory/config.py`**

```python
from __future__ import annotations
from dataclasses import dataclass, field

@dataclass
class Settings:
    backend: str = "sqlite"                 # "sqlite" | "pgvector"
    db_path: str = "luminary_memory.db"
    # pgvector (only used when backend == "pgvector")
    pg_dsn: str = "postgresql://localhost/luminary_memory"
    # embeddings
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384
    # ingest
    ingest_whitelist: list[str] = field(default_factory=list)  # regex patterns
    ingest_llm: bool = False
    # recall fusion
    rrf_k: int = 60
    dedup_jaccard_threshold: float = 0.85
    token_budget: int = 4096
    # lifecycle
    ttl_default_seconds: int | None = None
    prune_min_importance: float = 0.2
    consolidate_jaccard_threshold: float = 0.9
```

**Step 3: Verify**

```bash
python -c "from luminary_memory.config import Settings; print(Settings().embedding_dim)"
```
Expected: `384`

**Step 4: Commit**

```bash
git add -A && git commit -m "feat: settings + core dataclasses"
```

---

## Phase 1 — Schema & SQLite FTS5 Backend (Day 1, afternoon)

### Task 1.1: Schema DDL + migration runner

**Objective:** The `memories` table plus an FTS5 virtual table with trigger-based sync.

**Files:**
- Create: `src/luminary_memory/schema.py`
- Test: `tests/test_schema.py`

**Step 1: Write failing test**

```python
# tests/test_schema.py
import sqlite3
from luminary_memory.schema import SCHEMA_SQL, init_schema

def test_init_schema_creates_tables(tmp_path):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    init_schema(conn)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"memories", "memories_fts", "entities", "relations"} <= tables
    conn.close()

def test_fts_trigger_syncs_content(tmp_path):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    init_schema(conn)
    conn.execute(
        "INSERT INTO memories (content) VALUES (?)", ("hello world token",))
    conn.commit()
    row = conn.execute(
        "SELECT COUNT(*) FROM memories_fts WHERE memories_fts MATCH 'world'").fetchone()
    assert row[0] == 1
    conn.close()
```

**Step 2: Run, expect FAIL** (module does not exist yet)

```bash
pytest tests/test_schema.py -v
```
Expected: FAIL — `ModuleNotFoundError: luminary_memory.schema`

**Step 3: Implement `src/luminary_memory/schema.py`**

```python
from __future__ import annotations
import sqlite3

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    source TEXT,
    tags TEXT NOT NULL DEFAULT '[]',
    importance REAL NOT NULL DEFAULT 0.5,
    ttl_seconds INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_accessed_at TEXT,
    access_count INTEGER NOT NULL DEFAULT 0,
    embedding BLOB
);
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    content, tags, content='memories', content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, content, tags)
    VALUES (new.id, new.content, new.tags);
END;
CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, tags)
    VALUES ('delete', old.id, old.content, old.tags);
END;
CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, tags)
    VALUES ('delete', old.id, old.content, old.tags);
    INSERT INTO memories_fts(rowid, content, tags)
    VALUES (new.id, new.content, new.tags);
END;
CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL DEFAULT 'generic'
);
CREATE TABLE IF NOT EXISTS relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL REFERENCES entities(id),
    target_id INTEGER NOT NULL REFERENCES entities(id),
    relation_type TEXT NOT NULL DEFAULT 'cooccur',
    weight REAL NOT NULL DEFAULT 1.0,
    memory_id INTEGER REFERENCES memories(id)
);
"""

def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()
```

**Step 4: Run, expect PASS**

```bash
pytest tests/test_schema.py -v
```
Expected: 2 passed

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: SQLite schema + FTS5 triggers"
```

### Task 1.2: Backend ABC + SQLite backend

**Objective:** A backend abstraction exposing CRUD plus search operations.

**Files:**
- Create: `src/luminary_memory/backends/__init__.py`
- Create: `src/luminary_memory/backends/base.py`
- Create: `src/luminary_memory/backends/sqlite.py`
- Test: `tests/test_backend_sqlite.py`

**Step 1: Write `base.py`**

```python
from __future__ import annotations
from abc import ABC, abstractmethod
from luminary_memory.types import Memory

class MemoryBackend(ABC):
    @abstractmethod
    def add(self, m: Memory) -> int: ...
    @abstractmethod
    def get(self, id: int) -> Memory | None: ...
    @abstractmethod
    def update(self, m: Memory) -> None: ...
    @abstractmethod
    def delete(self, id: int) -> None: ...
    @abstractmethod
    def all(self) -> list[Memory]: ...
    @abstractmethod
    def keyword_search(self, query: str, limit: int) -> list[tuple[Memory, float]]: ...
    @abstractmethod
    def vector_search(self, vec: list[float], limit: int) -> list[tuple[Memory, float]]: ...
    @abstractmethod
    def count(self) -> int: ...
```

**Step 2: Write failing test `tests/test_backend_sqlite.py`**

```python
import sqlite3
from luminary_memory.backends.sqlite import SQLiteBackend
from luminary_memory.types import Memory

def _mk(tmp_path):
    return SQLiteBackend(str(tmp_path / "t.db"))

def test_add_and_get(tmp_path):
    b = _mk(tmp_path)
    mid = b.add(Memory(content="The sky is blue", tags=["nature"]))
    m = b.get(mid)
    assert m is not None and m.content == "The sky is blue"
    assert b.count() == 1

def test_keyword_search_ranks(tmp_path):
    b = _mk(tmp_path)
    b.add(Memory(content="database indexing with sqlite fts5"))
    b.add(Memory(content="making a sandwich for lunch"))
    res = b.keyword_search("sqlite fts5", limit=5)
    assert res and res[0][0].content.startswith("database")
```

**Step 3: Implement `sqlite.py`** — register a memory row mapper, store the embedding as a BLOB via `struct`/`numpy.tobytes`, keyword search via FTS5 `MATCH`, vector search via cosine similarity in Python.

Key detail — keyword search uses FTS5 `MATCH` with `bm25` ranking:

```python
def keyword_search(self, query, limit=10):
    safe = query.replace('"', ' ')
    rows = self.conn.execute(
        "SELECT m.*, bm25(memories_fts) AS rank "
        "FROM memories_fts JOIN memories m ON m.id = memories_fts.rowid "
        "WHERE memories_fts MATCH ? ORDER BY rank LIMIT ?",
        (safe, limit),
    ).fetchall()
    return [(self._row_to_memory(r), -float(r["rank"])) for r in rows]
```

`vector_search` = cosine similarity via numpy over all embeddings (MVP linear scan; pgvector uses the `<=>` operator).

**Step 4: Run, expect PASS** · **Step 5: Commit**

```bash
pytest tests/test_backend_sqlite.py -v
git add -A && git commit -m "feat: SQLite backend (CRUD + FTS5 keyword + vector scan)"
```

---

## Phase 2 — Embeddings & Ingest (Day 1 evening → Day 2 morning)

### Task 2.1: Fastembed wrapper

**Objective:** An engine that turns text into 384-dim vectors via local CPU fastembed.

**Files:**
- Create: `src/luminary_memory/embeddings/__init__.py`
- Create: `src/luminary_memory/embeddings/fastembed.py`
- Test: `tests/test_embeddings.py`

**Step 1: Write failing test** (mock fastembed so tests don't download the model — a stub returns a fixed vector)

```python
def test_embed_returns_384d(monkeypatch):
    class FakeModel:
        def embed(self, texts):
            return [ [0.1] * 384 for _ in texts ]
    monkeypatch.setattr("luminary_memory.embeddings.fastembed.TextEmbedding",
                        lambda **kw: FakeModel())
    from luminary_memory.embeddings.fastembed import FastembedEngine
    e = FastembedEngine()
    vec = e.embed("hello")
    assert len(vec) == 384
```

**Step 2/3:** Implement `FastembedEngine` — lazy-load `TextEmbedding(model_name=..., threads=1)`, cache the model, provide `embed(text) -> list[float]` and `embed_batch(list[str]) -> list[list[float]]`.

**Step 4/5:** Run pass + commit `feat: fastembed embedding engine`.

### Task 2.2: Whitelist regex filter

**Objective:** Gate ingestion — accept only text that matches at least one whitelist regex and passes quality checks (minimum length, non-empty, non-spam).

**Files:**
- Create: `src/luminary_memory/ingest/__init__.py`
- Create: `src/luminary_memory/ingest/whitelist.py`
- Test: `tests/test_ingest_whitelist.py`

**Step 1: Write failing test**

```python
from luminary_memory.ingest.whitelist import WhitelistFilter

def test_allows_matching_content():
    f = WhitelistFilter(patterns=[r"python", r"database"])
    assert f.accepts("learning python decorators")

def test_rejects_non_matching():
    f = WhitelistFilter(patterns=[r"python"])
    assert not f.accepts("my cat ate a sandwich")

def test_rejects_too_short():
    f = WhitelistFilter(patterns=[r".*"], min_length=10)
    assert not f.accepts("hi")

def test_empty_patterns_allow_all():
    f = WhitelistFilter(patterns=[])
    assert f.accepts("anything at all here")
```

**Step 2/3:** Implement — compile patterns (`re.compile(p, re.IGNORECASE)`), `accepts(text) -> bool` = (length >= min_length) AND (no patterns OR any match).

**Step 4/5:** Run + commit `feat: ingest whitelist regex filter`.

### Task 2.3: Ingest pipeline (whitelist → embed → store) + optional LLM

**Objective:** End-to-end `ingest`; LLM enrichment is provider-agnostic (callable injection, not a hardcoded provider).

**Files:**
- Create: `src/luminary_memory/ingest/llm.py`
- Create: `src/luminary_memory/api.py` (ingest portion)
- Test: `tests/test_api.py` (partial)

**Step 1: Write `llm.py`** — an `LLMEnricher` interface with `enrich(text) -> EnrichedContent(content, summary, entities, tags)`. Default implementation is `NoopEnricher`; callers can inject a custom callable/object (e.g. an OpenAI-compatible endpoint). No paid API calls in tests.

**Step 2: Write failing test**

```python
from luminary_memory.api import MemoryClient
from luminary_memory.ingest.llm import NoopEnricher

def test_ingest_stores_and_recalls(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "t.db"), enricher=NoopEnricher())
    c.ingest("postgres vector similarity search is fast", tags=["db"])
    assert c.count() == 1

def test_ingest_rejected_by_whitelist(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "t.db"),
                     ingest_whitelist=[r"kubernetes"])
    c.ingest("postgres vector search")
    assert c.count() == 0
```

**Step 3:** Implement `MemoryClient.ingest(text, ...)` — whitelist filter → (enrich if configured) → embed → build `Memory` → `backend.add`.

**Step 4/5:** Run + commit `feat: ingest pipeline with optional LLM enrichment`.

---

## Phase 3 — Four Retrieval Strategies (Day 2)

Each task is a full TDD cycle (failing test → implement → pass → commit).

### Task 3.1: Semantic recall

**Files:** `src/luminary_memory/recall/semantic.py`, test `tests/test_recall_semantic.py`

Embed the query → `backend.vector_search` → return top-k with cosine score. Verify ranking: the most similar memory scores highest.

### Task 3.2: Keyword recall (FTS5)

**Files:** `src/luminary_memory/recall/keyword.py`, test `tests/test_recall_keyword.py`

Query `"sqlite fts5"` → return memories containing the keywords, scored from bm25 (negated so higher relevance = higher score).

### Task 3.3: Temporal recall (recency)

**Files:** `src/luminary_memory/recall/temporal.py`, test `tests/test_recall_temporal.py`

Scoring: `score = exp(-age_hours / half_life) * (1 + log(1 + access_count))`. Test: newer memory beats older; frequently accessed beats rarely accessed.

### Task 3.4: Graph-lite recall (entity co-occurrence)

**Files:** `src/luminary_memory/recall/graph.py`, test `tests/test_recall_graph.py`

Extract entities (simple noun/keyword/tag heuristics, no mandatory LLM), build `entities` + `relations` (co-occurrence within the same memory). Recall: given query entities → find neighbors via relations → return related memories weighted by `weight`.

Test: two memories sharing an entity → recalling one surfaces the other.

---

## Phase 4 — RRF Fusion + Dedup + Budget (Day 3, morning)

### Task 4.1: RRF fusion

**Files:** `src/luminary_memory/recall/fusion.py`, test `tests/test_fusion_rrf.py`

```python
def reciprocal_rank_fusion(ranked_lists, k=60):
    # ranked_lists: list[list[memory_id]] ordered best-first per strategy
    scores = {}
    for lst in ranked_lists:
        for rank, mid in enumerate(lst):
            scores[mid] = scores.get(mid, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: -x[1])
```

Test: a memory ranked highly across multiple strategies gets the highest fused score; deterministic.

### Task 4.2: Jaccard dedup

**Files:** `src/luminary_memory/recall/dedup.py`, test `tests/test_dedup_jaccard.py`

Tokenize (word-level, lowercase, optional stopwords) → `jaccard(a, b) = |A∩B| / |A∪B|`. If two memories exceed the threshold → keep the one with higher score/recency. Test: near-identical duplicates collapse to one.

### Task 4.3: Token budget manager

**Files:** `src/luminary_memory/budget.py`, test `tests/test_budget.py`

`Budget.truncate(memories, token_budget, tokenizer=simple_split)` — accumulate tokens up to the budget, drop the rest, prioritize highest score (the fusion output order). Test: total tokens ≤ budget; no overflow; empty in → empty out.

### Task 4.4: Recall orchestrator (four strategies → RRF → dedup → budget)

**Files:** `src/luminary_memory/api.py` (method `recall`), test `tests/test_api.py`

End-to-end test: ingest several memories, `recall(query)` returns a `RecallResult` with relevance-ordered `memories`, populated `strategies_hit`, and total tokens ≤ budget.

---

## Phase 5 — Lifecycle (Day 3, afternoon)

### Task 5.1: Cleanup (TTL expiry)

**Files:** `src/luminary_memory/lifecycle/cleanup.py`, test `tests/test_lifecycle.py`

Remove memories whose `ttl_seconds` means `created_at + ttl < now`. Test: expired memory is gone, valid one remains.

### Task 5.2: Consolidate (merge near-duplicates)

**Files:** `src/luminary_memory/lifecycle/consolidate.py`

Pairwise Jaccard > threshold → merge into a canonical memory (longest/most recent content), combine `access_count` + `tags`, delete duplicates. Test: two similar memories become one with combined `access_count`.

### Task 5.3: Prune (low-importance / LRU)

**Files:** `src/luminary_memory/lifecycle/prune.py`

Remove memories below `prune_min_importance` that are rarely accessed (low `access_count` + stale `last_accessed_at`), respecting a max-count ceiling. Test: unimportant & stale memories are removed, important ones retained.

### Task 5.4: Lifecycle runner + CLI command

**Files:** `src/luminary_memory/lifecycle/__init__.py` (`run_lifecycle`), `src/luminary_memory/cli.py` (subcommand `lifecycle`)

---

## Phase 6 — pgvector Backend (Day 4)

### Task 6.1: pgvector backend implementation

**Files:** `src/luminary_memory/backends/pgvector.py`, test `tests/test_backend_sqlite.py` (skip when no DSN — mark `@pytest.mark.skipif`)

Implement the same ABC: `vector_search` via the `<=>` operator (cosine distance), keyword via `tsvector`/ILIKE fallback, embeddings stored as `Vector(384)`. Integration test is optional (requires a running pgvector), default skip.

### Task 6.2: Backend factory & config wiring

**Files:** `src/luminary_memory/backends/__init__.py` (`get_backend(settings)`), update `api.py` to select the backend via config.

---

## Phase 7 — CLI + Python API polish + Docs (Day 4 evening → Day 5)

### Task 7.1: Complete CLI (typer + rich)

**Files:** `src/luminary_memory/cli.py`, test `tests/test_cli.py`

Subcommands:
- `luminary-memory add "text" --tags a,b --source x`
- `luminary-memory recall "query" --limit 5 --json`
- `luminary-memory search "keyword"`
- `luminary-memory list`
- `luminary-memory lifecycle`
- `luminary-memory stats`

Test via `typer.testing.CliRunner` — verify output & exit code, no permanent side effects (tmp db).

### Task 7.2: Final Python API (`MemoryClient`)

**Files:** `src/luminary_memory/api.py`

Public methods: `ingest`, `recall`, `search`, `get`, `update`, `delete`, `list`, `run_lifecycle`, `stats`, `count`. All covered by `tests/test_api.py`.

### Task 7.3: README + LICENSE + Hermes skill

**Files:**
- Create: `README.md` (quickstart, architecture, Python API + CLI examples, config table)
- Create: `LICENSE` (Apache-2.0 full text)
- Create: `hermes/SKILL.md` — Hermes integration skill: installation, agent usage (cross-session ingest, recall into system prompt, lifecycle via cron). Author = Dwiky Candra.

### Task 7.4: Documentation structure (GitHub-ready)

**Objective:** Full documentation tree so the repo is immediately publishable and community-friendly.

**Files:**
- Create: `CONTRIBUTING.md` — contribution guide: setup, dev workflow, PR process, coding standards (ruff, pytest), commit conventions.
- Create: `CHANGELOG.md` — keep-a-changelog format, v0.1.0 entry (MVP release).
- Create: `SECURITY.md` — security policy: reporting process, supported versions, no-data-leak guarantee (all local).
- Create: `CODE_OF_CONDUCT.md` — standard Contributor Covenant 2.1.
- Create: `docs/index.md` — documentation home (landing, feature overview).
- Create: `docs/architecture.md` — pipeline diagrams (ingest → persist → recall → lifecycle), backend abstraction, data flow.
- Create: `docs/quickstart.md` — install, first add, first recall, config reference.
- Create: `docs/api.md` — full Python API reference (MemoryClient methods, signatures, examples).
- Create: `docs/cli.md` — CLI reference (all subcommands, flags, examples).
- Create: `docs/backends.md` — SQLite vs pgvector comparison, when to use which, migration guide.
- Create: `docs/recall.md` — how the four retrieval strategies work, fusion, dedup, budget, tuning knobs.
- Create: `docs/lifecycle.md` — TTL cleanup, consolidation, pruning, scheduling via cron.
- Create: `docs/hermes-integration.md` — how to use with Hermes Agent (skill install, recall into system prompt, cron lifecycle).
- Create: `.github/ISSUE_TEMPLATE/bug_report.md` — bug template.
- Create: `.github/ISSUE_TEMPLATE/feature_request.md` — feature template.
- Create: `.github/PULL_REQUEST_TEMPLATE.md` — PR template.
- Create: `.github/workflows/ci.yml` — CI: lint (ruff) + test (pytest) on push/PR, matrix Python 3.11/3.12.
- Update: `pyproject.toml` — project metadata: name `luminary-memory`, author Dwiky Candra, `readme = "README.md"`, `license = "Apache-2.0"`, classifiers, homepage/repository URLs.

**Verification:**
```bash
# all docs exist
ls README.md CONTRIBUTING.md CHANGELOG.md SECURITY.md CODE_OF_CONDUCT.md docs/ .github/
# links in README resolve (manual spot-check)
# CI runs clean on push (after first commit)
```

### Task 7.5: Final verification & release prep

```bash
pytest -v                 # all pass
ruff check src tests      # clean
pip install -e . && luminary-memory --help   # CLI runs
```

Final commit `chore: MVP release v0.1.0` + push public repo.

---

## Release & Publishing Checklist (post-MVP)

- [ ] Tag `v0.1.0` + GitHub release with notes
- [ ] PyPI publish (optional; `python -m build && twine upload`)
- [ ] Social announcement copy (product-first, no competitor mention)
- [ ] Screenshot demo: `luminary-memory add` + `recall` in terminal
- [ ] Badges in README: license, CI status, PyPI version, Python versions

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| fastembed model download is slow in CI | cache the model; tests use a stub embedding |
| FTS5 `MATCH` syntax errors on user queries (special characters) | sanitize the query, escape quotes |
| Linear vector scan is slow beyond ~100k memories | MVP linear scan; pgvector backend for scale; HNSW index on the roadmap |
| Jaccard dedup is O(n²) on long lists | dedup only the top-N fusion results (N ≤ 50) |
| Entity extraction without an LLM is coarse | graph-lite uses tags + keyword heuristics; optional LLM enricher for precise entities |
| pgvector requires a running service in dev | SQLite is the default backend; pgvector optional + skipped tests |
| Aggressive dedup merges distinct meanings | conservative 0.85 threshold; consolidation threshold 0.9 |

## Roadmap (post-MVP)

1. HNSW/pgvector indexing + quantization for million-memory scale
2. Pluggable embedding models (OpenAI/Cohere endpoints, not just fastembed)
3. Full graph-lite: LLM entity extraction + relation typing + weighted BFS traversal
4. Scheduled incremental consolidation (cron) + distributed locking
5. HTTP server / MCP server wrapper for broader agent integrations
6. Memory versioning + rollback
7. Multi-tenant namespaces (`MemoryClient(namespace="proj-x")`)

## MVP Definition of Done

- [ ] Clean `pip install`, green `pytest`, clean `ruff`
- [ ] Four-strategy recall + RRF fusion + dedup + token budget working end-to-end via the Python API
- [ ] Ingest whitelist + optional LLM enrichment functional
- [ ] Lifecycle cleanup/consolidate/prune functional
- [ ] SQLite FTS5 default; pgvector backend available (optional)
- [ ] CLI with 7 subcommands working; complete `MemoryClient` Python API
- [ ] Public Apache-2.0 repo + README + Hermes skill
