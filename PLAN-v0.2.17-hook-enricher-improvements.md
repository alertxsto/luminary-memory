# PLAN — v0.2.17 Hook & Enricher Polish Improvements

**Status:** Ready to Implement  
**Target:** v0.2.17  
**Branch:** `develop`  

---

## 1. Objectives

1. **Telegram Hook Robustness & Markdown Escaping:**
   Prevent HTTP 400 Bad Request errors from Telegram API when memory content contains unescaped special characters (such as `_`, `*`, `` ` ``, `[`, `]`).
2. **Visual Differentiation for Rules vs Regular Facts:**
   Display `📌` icon for durable rules (memories with `importance >= 0.85` or tagged `core`/`rule`), and `•` for normal facts.
3. **Batch Overflow Indicator:**
   When an agent turn stores $> 3$ memories, display the top 3 with a clear summary counter (e.g. `... (+2 more)`), and advance `last_shown_id` across the entire batch to avoid repeated notifications.
4. **Enricher Resilience (1x Quick Retry):**
   Add a 1x defensive retry with backoff on transient network glitches (HTTP 502/503/504 or connection reset) before gracefully falling back.

---

## 2. Technical Specification & Proposed Changes

### 2.1 `hermes/hooks/luminary-activity/handler.py`

#### A. Markdown Escape Helper:
```python
def _escape_md(text: str) -> str:
    """Escape Telegram Markdown special characters to prevent API formatting errors."""
    for ch in ("_", "*", "`", "[", "]"):
        text = text.replace(ch, f"\\{ch}")
    return text
```

#### B. Visual Icon & Batching in `_recent_activity()`:
```python
def _recent_activity(seconds: int = 30) -> str | None:
    db = DB_PATH
    if not Path(db).exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        last_id = _last_shown_id()
        
        if last_id == 0:
            row = conn.execute("SELECT MAX(id) as max_id FROM memories").fetchone()
            max_id = int(row["max_id"] or 0) if row else 0
            if max_id == 0:
                conn.close()
                return None
            all_rows = conn.execute(
                "SELECT id, content, importance, tags FROM memories WHERE id = ?",
                (max_id,),
            ).fetchall()
        else:
            all_rows = conn.execute(
                "SELECT id, content, importance, tags FROM memories WHERE id > ? ORDER BY id ASC",
                (last_id,),
            ).fetchall()
            if not all_rows:
                conn.close()
                return None
                
        n_new = len(all_rows)
        noun = "memory" if n_new == 1 else "memories"
        lines = [f"🌙 Luminary — {n_new} {noun} stored"]
        
        display_rows = all_rows[:3]
        for r in display_rows:
            raw = str(r["content"] or "").replace("\n", " ").strip()
            if len(raw) > 120:
                raw = raw[:120].rsplit(" ", 1)[0] + "…"
            if raw:
                imp = float(r["importance"] or 0.0) if "importance" in r.keys() else 0.0
                tags = str(r["tags"] or "") if "tags" in r.keys() else ""
                is_rule = imp >= 0.85 or "core" in tags or "rule" in tags
                icon = "📌" if is_rule else "•"
                lines.append(f"  {icon} {_escape_md(raw)}")
                
        if n_new > 3:
            lines.append(f"  ... (+{n_new - 3} more)")
            
        max_shown = max(int(r["id"]) for r in all_rows)
        _set_last_shown_id(max_shown)
        conn.close()
        return "\n".join(lines)
    except Exception:
        logger.exception("activity read failed")
        return None
```

### 2.2 `src/luminary_memory/ingest/llm.py`
In `_call_llm()`:
Implement a 1x immediate retry loop on `urllib.error.URLError` or transient 5xx HTTP errors with 0.3s delay.

### 2.3 Unit & Integration Tests
* Update `tests/hermes/test_activity_hook.py`:
  - `test_recent_activity_escapes_markdown_underscores`
  - `test_recent_activity_shows_pin_icon_for_rules`
  - `test_recent_activity_handles_batch_overflow`
* Verify all 375+ tests pass with 100% green status.
* Sync `handler.py` to `~/.hermes/hooks/luminary-activity/handler.py`.

---

## 3. Execution Checklist

- [ ] Apply changes to `hermes/hooks/luminary-activity/handler.py`.
- [ ] Apply 1x retry in `src/luminary_memory/ingest/llm.py`.
- [ ] Update `tests/hermes/test_activity_hook.py` with test cases for markdown escaping and icons.
- [ ] Run `pytest` & `ruff check .` to verify 100% pass and 0 lint errors.
- [ ] Sync updated hook to `~/.hermes/hooks/luminary-activity/handler.py`.
- [ ] Update `CHANGELOG.md` & `ROADMAP.md`.
