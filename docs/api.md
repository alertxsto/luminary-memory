# Python API

## MemoryClient

The single entry point. All methods are synchronous.

```python
from luminary_memory import MemoryClient

client = MemoryClient(
    db_path="memory.db",           # or Settings(backend="pgvector", pg_dsn=...)
    ingest_whitelist=[r"port", r"config"],  # optional regex patterns
)
```

### ingest

```python
ingest(text: str, tags: list[str] | None = None, source: str | None = None) -> int | None
```

Stores a memory. Returns its id, or `None` if the whitelist rejected it.

### recall

```python
recall(query: str, limit: int = 10, token_budget: int | None = None) -> RecallResult
```

Runs the four-strategy pipeline and returns a `RecallResult` with `.memories`, `.scores`, and `.strategies_hit`.

### search

```python
search(query: str, limit: int = 10) -> list[tuple[Memory, float]]
```

Keyword (FTS) search only — bypasses the full fusion pipeline.

### get / update / delete

```python
get(id: int) -> Memory | None
update(memory: Memory) -> None
delete(id: int) -> None
```

### list

```python
list(limit: int = 100, offset: int = 0) -> list[Memory]
```

Most recent first (datetime-aware sort).

### lifecycle / stats / count

```python
run_lifecycle() -> dict[str, int]   # {"cleanup": n, "consolidate": n, "prune": n}
stats() -> dict                      # count, oldest/newest, avg_importance, top_tags
count() -> int
```

### close

```python
close() -> None
```

Releases the backend connection.
