# Luminary Memory — v0.2.1 Implementation Plan

> **Release:** v0.2.1 "Hermes Memory Provider" · **Base:** v0.2.0 (126 tests, 91% coverage) · **License:** Apache-2.0
>
> This plan is the authoritative implementation guide for the v0.2.1 roadmap item. It is derived from
> `ROADMAP.md` (§ "v0.2.1 — Hermes Memory Provider") and supersedes the standalone-skill approach
> documented in `docs/hermes-integration.md` and `hermes/SKILL.md`.

---

## 1. Goal

Turn luminary-memory into a **first-class Hermes Agent memory provider** — a drop-in alternative to
Hindsight that delivers the same core experience (auto-recall every turn, auto-save every session,
explicit memory tools, deterministic "memory was used" indicators) at a fraction of the resource
cost, with no cloud dependency and no per-token memory spend.

Concretely, v0.2.1 ships a `MemoryProvider` implementation that plugs into Hermes through its
official plugin surface and wires luminary's existing engine directly into the agent loop:

- **Auto-recall every turn** — the current user message is used to recall relevant memories from the
  local store, which are injected into the agent's context on the next turn (background recall, the
  same warm-prefetch model Hindsight uses).
- **Auto-save every session** — completed turns are captured into the store automatically; session
  boundaries flush buffered turns under the correct session lineage.
- **Explicit tools** — `luminary_recall` / `luminary_ingest` (and a read-only `luminary_list`) are
  exposed to the model for on-demand memory access.
- **Deterministic indicators** — a "🌙 Luminary — recalled N memories" status line that surfaces
  memory use independently of whether the model chooses to mention it.
- **Zero cloud, zero new heavy deps** — the provider runs on the existing SQLite/FTS5 + local-ONNX
  stack. The only runtime dependency added is `luminary-memory` itself (already the package under
  construction).

The product principles are unchanged: **private by default, lightweight by construction,
budget-aware, self-maintaining, pluggable.**

---

## 2. Architecture Notes

These notes constrain the implementation. They reflect the Hermes `MemoryProvider` contract and the
Hindsight reference plugin as verified at planning time.

### 2.1 How MemoryProvider integrates

Hermes defines a `MemoryProvider` ABC at `agent/memory_provider.py` (in the hermes-agent tree).
The lifecycle is driven by `MemoryManager` (`agent/memory_manager.py`) and wired through
`run_agent.py`:

| Hook | When it fires | What a provider does |
|------|---------------|----------------------|
| `is_available()` | agent init | gate activation (config + deps only, no network) |
| `initialize(session_id, **kwargs)` | once at startup | connect, load config, create resources, start threads |
| `system_prompt_block()` | system-prompt assembly | static provider info text |
| `prefetch(query, session_id)` | before each turn | return cached recall context (must be fast) |
| `queue_prefetch(query, session_id)` | after each turn | queue background recall for the NEXT turn |
| `recall_status()` | right after prefetch | `RecallStatus` for the deterministic indicator |
| `sync_turn(user, asst, ...)` | after each turn (background worker) | persist the completed turn |
| `get_tool_schemas()` | tool registration | OpenAI-format schemas for model-exposed tools |
| `handle_tool_call(name, args)` | tool dispatch | run the tool, return a JSON string |
| `shutdown()` | session teardown | flush queues, close connections |
| `on_session_end(messages)` | session boundary | end-of-session extraction/flush |
| `on_session_switch(new_id, ...)` | `/resume` `/branch` `/reset` `/new`, compression | rebind per-session state |
| `on_pre_compress(messages)` | before compression discards context | extract insights into the summary prompt |
| `on_delegation(task, result)` | parent observes subagent completion | persist delegation observations |
| `on_memory_write(action, target, content)` | built-in memory tool writes | mirror into the backend |
| `get_config_schema()` / `save_config()` | `hermes memory setup` | declare + persist config |
| `backup_paths()` | `hermes backup` | declare state outside HERMES_HOME |

Key facts verified from source:

- **Exactly one external provider** runs at a time, selected by `memory.provider = <name>` in
  `config.yaml`. The built-in provider (`MEMORY.md`/`USER.md`) is always active.
- **`prefetch()` is called on a background thread with a timeout** (default `external_prefetch_timeout`);
  the provider must return cached results fast, never block on recall.
- **`sync_turn()` is already dispatched on a single serialized background worker** by `MemoryManager`
  (`_submit_background` → single `ThreadPoolExecutor`). The provider does **not** need its own
  ordering guarantees for turn writes — but it must still be non-blocking and thread-safe because it
  runs on a shared worker thread.
- **`on_session_end` runs strictly before `on_session_switch`** at session boundaries (FIFO on the
  same worker), so the provider can rely on that ordering for flush-then-rotate.
- **Trivial-prompt gating is handled by the core** (`agent/memory_provider.is_trivial_prompt`,
  used by `turn_context.py`/`run_agent.py`). The provider does not re-implement it.
- **`RecallStatus(provider_label, count, glyph)`** is the deterministic indicator contract. A
  provider returns it from `recall_status()` only for the *last* prefetch; `count=0` renders as
  "recalled relevant memory" (no discrete count).

### 2.2 What Hindsight does that we replicate

The Hindsight plugin (`plugins/memory/hindsight/__init__.py`, ~2,400 lines) is the reference. The
parts worth replicating, and how luminary maps them:

| Hindsight concept | Luminary equivalent |
|-------------------|---------------------|
| Bank (server-side memory scope) | Local store file (`db_path`), one per profile |
| `arecall()` multi-strategy + rerank | `MemoryClient.recall()` — 4-strategy RRF + Jaccard dedup + token budget |
| `aretain_batch()` of conversation turns | `MemoryClient.ingest()` / `ingest_batch()` of turn text |
| `areflect()` synthesis | **Out of scope v0.2.1** (no synthesis primitive; documented as a future task) |
| Background warm prefetch (`queue_prefetch` → cached `prefetch`) | Same pattern: recall on a daemon thread, cache `(text, count)`, drain in `prefetch` |
| `retain_every_n_turns` batching | Same batching knob on `sync_turn` |
| `retain_async` single-writer queue | Single-writer thread draining an in-memory queue (luminary is local/SQLite, so the "async server op" tracking is unnecessary — the read-after-write race Hindsight guards against does not exist for a synchronous SQLite insert) |
| `_build_metadata` (session/platform/user/agent tags) | `source="hermes"` + `tags=["session:<id>", "platform:<p>", …]` + `metadata={...}` |
| Deterministic indicators (`_emit_saving_indicator`, `recall_status`) | Same, with a luminary glyph |
| `get_config_schema()` + `config_schema.py` | Same, adapted to luminary's settings |
| `backup_paths()` | Return the luminary DB path when it lives outside HERMES_HOME |

What we deliberately **simplify** (the "fraction of resources" pitch):

- **No embedded daemon, no Postgres, no sentence-transformers** — Hindsight's local_embedded mode
  downloads ~200MB and needs a GPU-sized embedding model. Luminary uses fastembed ONNX (bge-small,
  384-dim, CPU) already in its dependency tree.
- **No async event loop** — Hindsight maintains a process-global `asyncio` loop + `aiohttp` session
  for a network client. Luminary talks to SQLite directly, so the provider is synchronous and
  thread-safe with a plain `threading.Thread` prefetch worker.
- **No per-turn LLM retention by default** — Hindsight's retain calls a server-side extractor.
  Luminary's auto-save ingests raw turn text (optionally enriched via the existing
  `OpenAICompatibleEnricher` when the user enables it), so the default path spends zero tokens.
- **No update-mode/append negotiation** — irrelevant without a remote server; SQLite inserts are
  atomic and durable on commit.

### 2.3 Distribution decision: pip entry-point provider (standalone package)

Per hermes-agent's `AGENTS.md`, third-party products do **not** land under `plugins/` in the
hermes-agent tree — they ship as a standalone plugin. Luminary is already a standalone PyPI package,
so the provider ships **inside the `luminary-memory` wheel** and registers itself through the
official entry-point group:

```
hermes_agent.memory_providers → luminary = "luminary_memory.hermes"
```

`plugins/memory/__init__.py` scans four sources (bundled → `$HERMES_HOME/plugins/<name>` →
project-local → pip entry points). An entry point resolves to the module `luminary_memory.hermes`;
its `register(ctx)` calls `ctx.register_memory_provider(LuminaryMemoryProvider())`. The same module
directory carries a `config_schema.py` (found by `find_provider_dir` → `_entry_point_package_dir`,
which returns the package dir only when the entry-point module is a package `__init__.py`) and a
`plugin.yaml` for users who prefer a directory install into `~/.hermes/plugins/luminary/`.

Consequences for the code:

- The provider depends **only** on `agent.memory_provider` (the ABC, present in the hermes-agent
  runtime) and on `luminary_memory` itself. It must **not** import hermes internals like
  `tools.registry.tool_error`, `hermes_cli.config.cfg_get`, or `hermes_constants.get_hermes_home`
  — those make the provider untestable standalone. Use the `hermes_home` kwarg passed to
  `initialize()`, and a local JSON `tool_error`-style helper.
- Because `agent.memory_provider` does not exist when running `pytest` inside the luminary repo,
  tests inject a **fake ABC module** via `conftest.py` (see T2). The shipped provider code has
  exactly one ABC import and zero drift risk; the test double mirrors the real signatures.

### 2.4 Store layout

```
$HERMES_HOME/luminary/
├── config.json          # provider config (mode, budget, toggles, tags) — 0600
└── memory.db            # SQLite store (created by MemoryClient)
```

`db_path` defaults to `$HERMES_HOME/luminary/memory.db` so the store is profile-scoped and picked up
by `hermes backup` automatically (no `backup_paths()` needed for the default). `backup_paths()`
still returns the path when a user overrides `db_path` to a location outside HERMES_HOME.

### 2.5 Definition of Done (applies to every task)

1. New behavior is covered by a failing-then-passing test (TDD) or a documented verification command.
2. `pytest -q` is green (target: ≥ 91% coverage, no regression).
3. `ruff check src tests` is clean.
4. Commit message follows the existing `feat:` / `fix:` / `chore:` convention.
5. Public API/docstrings stay accurate; `CHANGELOG.md` updated at release.

---

## 3. Tasks

Tasks are numbered `T1`–`T12`. Hard ordering constraints: **T1 before T2** (skeleton before test
harness), **T1–T4 before T5+** (provider instance must exist and initialize before lifecycle
hooks). Recommended execution order follows the numbering.

---

### Phase 1 — Provider skeleton

#### T1 — Provider package, entry point, version bump

**Objective:** Add the provider package skeleton so `luminary_memory.hermes` is importable and
registers itself as a Hermes memory provider.

**Files:**
- `src/luminary_memory/hermes/__init__.py` (new) — `register(ctx)` + re-export
- `src/luminary_memory/hermes/provider.py` (new) — `LuminaryMemoryProvider(MemoryProvider)` (initial: `name`, `is_available`, `initialize`, `shutdown`, `get_tool_schemas` → `[]`)
- `src/luminary_memory/__init__.py` — bump `__version__` to `0.2.1`
- `pyproject.toml` — bump `version`, add entry point
- `CHANGELOG.md` — add `## [0.2.1] - Unreleased` header

**`pyproject.toml` changes:**

```toml
version = "0.2.1"

[project.entry-points."hermes_agent.memory_providers"]
luminary = "luminary_memory.hermes"
```

**`provider.py` initial shape:**

```python
from agent.memory_provider import MemoryProvider, RecallStatus  # present only in hermes runtime

_LUMINARY_GLYPH = "🌙"

class LuminaryMemoryProvider(MemoryProvider):
    @property
    def name(self) -> str:
        return "luminary"
```

`register(ctx)` in `__init__.py` mirrors hindsight:

```python
def register(ctx) -> None:
    ctx.register_memory_provider(LuminaryMemoryProvider())
```

**TDD / verification steps:**
1. **Failing test** (`tests/hermes/test_entrypoint.py`): build the wheel and assert the
   `hermes_agent.memory_providers` entry point metadata contains `luminary = luminary_memory.hermes`.
2. **Implement** package + entry point + bump.
3. **Pass:** `python -c "import importlib.metadata as m; eps=m.entry_points(group='hermes_agent.memory_providers'); print([e.value for e in eps])"` shows `luminary_memory.hermes`.
4. **Commit:** `feat: hermety provider package + entry point`

**Verification:**
```bash
python -m build
python -c "import importlib.metadata as m; print([e.value for e in m.entry_points(group='hermes_agent.memory_providers')])"
ruff check src/luminary_memory/hermes
```

**Risks:** hatchling must be configured to include the `hermes` subpackage in the wheel. The existing
`[tool.hatch.build.targets.wheel] packages = ["src/luminary_memory"]` already includes it — verify
with `python -m build` that `luminary_memory/hermes/__init__.py` is present in the wheel.

---

#### T2 — Test harness: fake MemoryProvider ABC

**Objective:** Let `tests/` exercise the provider without a hermes-agent install, by injecting a
minimal `agent.memory_provider` module that mirrors the real ABC signatures.

**Files:**
- `tests/conftest.py` (new) — register the fake `agent.memory_provider` in `sys.modules` before collection
- `tests/hermes_stubs/agent/memory_provider.py` (new) — `MemoryProvider`, `RecallStatus`, `is_trivial_prompt`

**Design:** The stub is a faithful copy of the ABC *signatures* only — default no-op bodies, the same
`RecallStatus` dataclass, and a trivial `is_trivial_prompt`. `conftest.py` does:

```python
import sys, types
from pathlib import Path

def _ensure_agent_stub():
    if "agent.memory_provider" in sys.modules:
        return
    agent = types.ModuleType("agent")
    agent.__path__ = []
    stub_path = Path(__file__).parent / "hermes_stubs" / "agent" / "memory_provider.py"
    spec = importlib.util.spec_from_file_location("agent.memory_provider", stub_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["agent"] = agent
    sys.modules["agent.memory_provider"] = mod
    spec.loader.exec_module(mod)

_ensure_agent_stub()
```

No `pytest_plugins` or plugin machinery — just module injection. This keeps the shipped provider
importing the *real* `agent.memory_provider` at runtime while tests run against the double.

**TDD / verification steps:**
1. **Failing test** (`tests/hermes/test_provider_import.py`): `from luminary_memory.hermes.provider import LuminaryMemoryProvider` succeeds and `LuminaryMemoryProvider().name == "luminary"` — this fails before the stub exists (ImportError).
2. **Implement** the stub + conftest.
3. **Pass.**
4. **Commit:** `test: fake MemoryProvider ABC harness`

**Verification:**
```bash
pytest tests/hermes/test_provider_import.py -q
```

**Risks:** The stub can drift from the real ABC. Mitigate by keeping the stub signatures minimal and
tagging it with a comment pointing at the authoritative source; any drift only affects luminary's
own tests, not runtime behavior.

---

### Phase 2 — Config & lifecycle

#### T3 — Config layer + schema

**Objective:** Load/save `$HERMES_HOME/luminary/config.json`, expose `get_config_schema()` for
`hermes memory setup`, and a `config_schema.py` for the desktop dashboard.

**Files:**
- `src/luminary_memory/hermes/config.py` (new) — `load_config(hermes_home)`, `save_config(values, hermes_home)`, `_default_config()`
- `src/luminary_memory/hermes/provider.py` — implement `get_config_schema()` and `save_config()`
- `src/luminary_memory/hermes/config_schema.py` (new) — `CONFIG_SCHEMA` (dashboard panel)
- `tests/hermes/test_config.py` (new)

**Config keys (defaults in parentheses):**
- `mode`: `"context" | "tools" | "hybrid"` (default `hybrid`)
- `db_path`: SQLite path override (default `""` → `$HERMES_HOME/luminary/memory.db`)
- `backend`: `"sqlite" | "pgvector"` (default `sqlite`)
- `recall_limit`: int (default `10`) — top-N memories per recall
- `token_budget`: int (default `2048`) — recall context budget (smaller than the 4096 core default; the provider injects, it doesn't hold the conversation)
- `auto_recall`: bool (default `True`)
- `recall_sync`: bool (default `False`) — synchronous recall against the current message
- `auto_retain`: bool (default `True`)
- `retain_every_n_turns`: int (default `1`)
- `retain_user_prefix` / `retain_assistant_prefix`: str (default `User` / `Assistant`)
- `ingest_llm`: bool (default `False`) — opt-in LLM enrichment on retain
- `llm_base_url` / `llm_model` / `llm_timeout`: str/int (only used when `ingest_llm`)
- `recall_indicator`: bool (default `True`) — show the deterministic indicator
- `retain_indicator`: bool (default `True`)

Secrets: none required by default (SQLite is local). If a user enables `ingest_llm` with a key,
`get_config_schema()` declares `llm_api_key` with `secret=True`, `env_var="LUMINARY_LLM_API_KEY"`.

**`config_schema.py`** declares `ProviderConfigSchema(name="luminary", label="Luminary Memory",
storage=STORAGE_FLAT_JSON, fields=...)` with `mode`, `db_path`, `backend`, `recall_limit`,
`token_budget`, `auto_recall`, `auto_retain` marked `inline=True`; the rest grouped. Import only
from `plugins.memory.config_schema` (the pure-data contract — no agent runtime).

**TDD steps:**
1. **Failing test:** `save_config({"backend": "pgvector"}, tmp_home)` writes
   `tmp_home/luminary/config.json` with mode `0600`; `load_config(tmp_home)` round-trips the value
   and fills defaults for unspecified keys.
2. **Failing test:** `get_config_schema()` returns a list of dicts each with `key`; the schema
   includes `mode` with `choices == ["context", "tools", "hybrid"]` and `llm_api_key` with
   `secret is True`.
3. **Implement** config module + both schema surfaces.
4. **Pass.**
5. **Commit:** `feat: luminary provider config layer + schema`

**Verification:**
```bash
pytest tests/hermes/test_config.py -q
ruff check src/luminary_memory/hermes/config.py src/luminary_memory/hermes/config_schema.py
```

**Risks:** `config_schema.py` must not import the agent runtime (dashboard loads it by path). Keep
it a pure `CONFIG_SCHEMA` literal importing only `plugins.memory.config_schema`.

---

#### T4 — `is_available`, `initialize`, `shutdown`

**Objective:** Gate activation cleanly and create the `MemoryClient` at startup with profile-scoped
state.

**Files:**
- `src/luminary_memory/hermes/provider.py`
- `tests/hermes/test_lifecycle.py` (new)

**Behavior:**
- `is_available()`: return `True` if `luminary_memory` imports and (when `backend == "pgvector"`)
  `psycopg`/`pgvector` are importable. **No network, no store creation.** Read config from the
  ambient HERMES_HOME if determinable, else the default.
- `unavailable_reason()`: actionable hint when the package import fails (e.g. `pip install
  luminary-memory`).
- `initialize(session_id, **kwargs)`: read `hermes_home`, `platform`, `agent_identity`,
  `agent_workspace`, `user_id` from kwargs (ignore extras). Resolve `db_path`, construct
  `MemoryClient(settings=...)`, load config into instance state, set `_session_id`, start the
  retain writer thread and (if `auto_recall` and not `recall_sync`) nothing else (prefetch workers
  are per-turn in `queue_prefetch`). Record `_status_callback` when provided.
- `shutdown()`: set a `_shutting_down` event, drain the writer queue via a sentinel, join threads
  (bounded), close the client.

**TDD steps:**
1. **Failing test:** `initialize("sess1", hermes_home=tmp, platform="cli")` creates
   `tmp/luminary/memory.db` and `provider._client` is a `MemoryClient`; a second call with
   `agent_identity="coder"` stores that identity.
2. **Failing test:** `is_available()` returns `True` in the normal path; monkeypatching the
   `luminary_memory` import to raise makes it return `False` and `unavailable_reason()` non-empty.
3. **Failing test:** after `initialize` + two queued retains, `shutdown()` drains the queue (assert
   `_retain_queue` empty / writer joined) and `_shutting_down` is set.
4. **Implement.**
5. **Pass.**
6. **Commit:** `feat: luminary provider initialize/shutdown lifecycle`

**Verification:**
```bash
pytest tests/hermes/test_lifecycle.py -q
```

**Risks:** `MemoryClient` lazily loads the fastembed model on first `embed()` (slow, ~tens of MB).
The provider must **not** trigger a model load in `initialize()` — only on the first recall. Verify
`initialize()` stays fast in the test (no embedding call).

---

#### T5 — `system_prompt_block`

**Objective:** Emit a compact, mode-aware static block for the system prompt.

**Files:**
- `src/luminary_memory/hermes/provider.py`
- `tests/hermes/test_system_prompt.py` (new)

**Behavior:** mirror hindsight's three-mode shape:

```
# Luminary Memory
Active (context mode). Store: $HERMES_HOME/luminary/memory.db.
Relevant memories are automatically injected into context.
```

`tools` mode: instruct to use `luminary_recall` / `luminary_ingest`. `hybrid`: both. Return `""`
when the provider was never initialized (safety).

**TDD steps:**
1. **Failing test:** uninitialized → `""`; `hybrid` → contains "luminary_recall" and "automatically
   injected"; `tools` → does **not** contain "automatically injected"; `context` → does **not**
   contain "luminary_recall".
2. **Implement.**
3. **Pass.**
4. **Commit:** `feat: system prompt block`

**Verification:**
```bash
pytest tests/hermes/test_system_prompt.py -q
```

---

### Phase 3 — Auto-save

#### T6 — `sync_turn` (buffered, non-blocking, single-writer)

**Objective:** Persist completed turns to the store automatically, batching per `retain_every_n_turns`,
on a single writer thread that never blocks the reply path.

**Files:**
- `src/luminary_memory/hermes/provider.py`
- `tests/hermes/test_sync_turn.py` (new)

**Behavior (adapted from hindsight's `sync_turn`, simplified for a synchronous local store):**
- If `auto_retain` is off or shutting down → return.
- Build turn content as `"User: <user>\nAssistant: <assistant>"` (respecting the configurable
  prefixes), append to `_session_turns`, bump `_turn_counter`.
- If `_turn_counter % retain_every_n_turns != 0` → buffer only (no write).
- On flush: snapshot `(content, session_id, parent_session_id, turn_index, metadata)`; enqueue a
  `_do_retain` callable on the writer queue; emit the retain indicator via `_status_callback`.
- `_do_retain` calls `client.ingest(content, tags=lineage_tags, source="hermes")`. Lineage tags:
  `session:<id>`, `parent:<id>`, `platform:<p>`, `agent:<identity>` (non-empty only). Metadata:
  `{"turn_index", "retained_at", "message_count", "session_id", "platform", "agent_identity"}`.
- When `ingest_llm` is enabled, construct an `OpenAICompatibleEnricher` (from config) once and pass
  it to the client; ingest is unchanged otherwise.

**TDD steps:**
1. **Failing test:** `sync_turn("u", "a", session_id="s")` then wait for the writer → store contains
   one memory with `tags` including `session:s` and `source == "hermes"`.
2. **Failing test:** `retain_every_n_turns=2` → first `sync_turn` writes nothing, second writes a
   single memory containing both turns.
3. **Failing test:** `auto_retain=False` → no write.
4. **Implement.**
5. **Pass.**
6. **Commit:** `feat: auto-save turns via sync_turn`

**Verification:**
```bash
pytest tests/hermes/test_sync_turn.py -q
```

**Risks:** fastembed embedding on every retain is the dominant cost. Batching by
`retain_every_n_turns` amortizes it; consider embedding lazily is already how `MemoryClient`
works (one `embed()` per ingest). The default of `retain_every_n_turns=1` is safe for correctness
first; the benchmark task (T12) quantifies the cost and can inform a smarter default.

---

#### T7 — `on_session_end` + `on_session_switch`

**Objective:** Flush buffered turns under the old session's lineage at boundaries, then rebind to
the new session without dropping data.

**Files:**
- `src/luminary_memory/hermes/provider.py`
- `tests/hermes/test_session_boundaries.py` (new)

**Behavior (adapted from hindsight's flush-on-switch, minus the append/overwrite negotiation):**
- `on_session_end(messages)`: if `_session_turns` non-empty, enqueue a final flush under the
  current session lineage. Optionally (config `extract_on_session_end`, default `False` for v0.2.1)
  run a lightweight end-of-session summary — keep it off in the first cut.
- `on_session_switch(new_session_id, parent_session_id, reset, ...)`: flush buffered turns under the
  **old** session id/tags first (enqueue on the writer), drain any in-flight prefetch, then rotate
  `_session_id = new_id`, `_parent_session_id`, clear `_session_turns` / `_turn_counter` / turn index.
  Guard against `new_id` empty.

**TDD steps:**
1. **Failing test:** buffered turn exists → `on_session_switch("s2", parent_session_id="s1")` →
   store has a memory tagged `session:s1` and the provider's `_session_id == "s2"`.
2. **Failing test:** `reset=True` clears `_session_turns` (no orphan turn leaks into the next
   session's write).
3. **Failing test:** `on_session_end(messages)` flushes pending turns.
4. **Implement.**
5. **Pass.**
6. **Commit:** `feat: session-boundary flush + rebind`

**Verification:**
```bash
pytest tests/hermes/test_session_boundaries.py -q
```

**Risks:** the core guarantees `on_session_end` → `on_session_switch` ordering on the same worker;
do not double-enqueue a flush (the switch path already flushes before clearing). Guard with the
`_session_turns` emptiness check.

---

#### T8 — `on_memory_write`, `on_pre_compress`, `on_delegation`

**Objective:** Mirror built-in memory writes and capture compression/delegation signals so the
store reflects the full span of the agent's activity.

**Files:**
- `src/luminary_memory/hermes/provider.py`
- `tests/hermes/test_hooks.py` (new)

**Behavior:**
- `on_memory_write(action, target, content, metadata)`: map `add` → `client.ingest(content,
  tags=["builtin", target], source="hermes-builtin")`; `replace` → ingest with a `replace:<n>`
  marker tag (v0.2.1 keeps it as a new ingest — no in-place dedup of the builtin store); `remove` →
  a soft marker memory (or a `delete by exact content match` when a `delete_by_content` helper is
  available). Keep it additive and idempotent.
- `on_pre_compress(messages)`: return `""` by default (v0.2.1 no-op; documented as a future
  extraction point) — implemented only to make the contract explicit and covered by a test that it
  returns a string.
- `on_delegation(task, result, child_session_id)`: ingest a single memory
  `"delegated: <task>"` with `tags=["delegation", "child:<id>"]` and metadata `{"result": <truncated
  result>}`.

**TDD steps:**
1. **Failing test:** `on_memory_write("add", "user", "prefers X")` → store contains a memory tagged
   `user` with source `hermes-builtin`.
2. **Failing test:** `on_delegation("task", "result", child_session_id="c")` → store contains a
   memory tagged `delegation`.
3. **Failing test:** `on_pre_compress([])` returns a `str`.
4. **Implement.**
5. **Pass.**
6. **Commit:** `feat: builtin-mirror + delegation + pre-compress hooks`

**Verification:**
```bash
pytest tests/hermes/test_hooks.py -q
```

---

### Phase 4 — Auto-recall

#### T9 — `queue_prefetch`, `prefetch`, `recall_status`

**Objective:** Recall relevant memories for the next turn in the background and inject a cached,
formatted context block; report a deterministic "recalled N memories" indicator.

**Files:**
- `src/luminary_memory/hermes/provider.py`
- `tests/hermes/test_recall.py` (new)

**Behavior (mirrors hindsight's warm-prefetch model):**
- `queue_prefetch(query, session_id)`: if `recall_sync` or recall disabled or shutting down → return.
  Spawn a daemon thread that calls `client.recall(query, limit=recall_limit, token_budget=...)`,
  formats the top memories as a bullet list, and stores `(text, count)` under a lock.
- `prefetch(query, session_id)`: if `recall_sync`, do a **live** recall against the current query;
  else return the cached `(text, count)` (join the worker up to a small timeout, e.g. 3s) and clear
  the cache. Record `_last_recall_returned` / `_last_recall_count` for the indicator.
- Formatting: header `# Luminary Memory (persistent cross-session context)` + instruction line +
  `- content` bullets. Return `""` when nothing recalled.
- `recall_status()`: return `RecallStatus("Luminary", count, _LUMINARY_GLYPH)` when the indicator is
  enabled and the last prefetch injected something, else `None`.

**TDD steps:**
1. **Failing test:** seed the store with 3 memories, `queue_prefetch("query")`, join, then
   `prefetch("query")` returns a non-empty block containing the header and the most relevant memory
   text, and `recall_status()` reports `count == 3` (or ≥1) with glyph `🌙`.
2. **Failing test:** `recall_sync=True` → `prefetch("query")` returns results without a prior
   `queue_prefetch` call.
3. **Failing test:** `auto_recall=False` → `prefetch` returns `""` and `recall_status()` is `None`.
4. **Failing test:** `mode == "tools"` → `queue_prefetch` is a no-op (recall is tool-only).
5. **Implement.**
6. **Pass.**
7. **Commit:** `feat: auto-recall + deterministic indicator`

**Verification:**
```bash
pytest tests/hermes/test_recall.py -q
```

**Risks:** the first recall triggers a fastembed model download/load (one-time, potentially seconds).
Mitigate by warming the engine in `initialize()` when `auto_recall` is on (load the model on a
background thread so startup stays fast), and document the one-time cost. `recall_status()` must
reflect only the **last** prefetch (clear the flag on empty turns).

---

### Phase 5 — Tools

#### T10 — `get_tool_schemas` + `handle_tool_call`

**Objective:** Expose `luminary_recall`, `luminary_ingest`, and `luminary_list` tools and dispatch
them to the client.

**Files:**
- `src/luminary_memory/hermes/provider.py`
- `tests/hermes/test_tools.py` (new)

**Schemas (OpenAI format):**
- `luminary_recall` — `{query: string, limit?: integer}` → ranked memory bullets as JSON.
- `luminary_ingest` — `{content: string, tags?: array<string>}` → `{"result": "Memory stored (id=N)."}`
  or whitelist-rejected notice.
- `luminary_list` — `{limit?: integer}` → recent memories as JSON (read-only).

**Dispatch:** `get_tool_schemas()` returns `[]` in `context` mode; otherwise the three schemas.
`handle_tool_call` validates required args, calls the client, returns a JSON string. Errors return a
`{"error": ...}` JSON (local helper, no `tools.registry.tool_error` import).

**TDD steps:**
1. **Failing test:** `get_tool_schemas()` (hybrid) returns 3 schemas with names
   `{luminary_recall, luminary_ingest, luminary_list}`; `context` mode returns `[]`.
2. **Failing test:** `handle_tool_call("luminary_ingest", {"content": "fact", "tags": ["t"]})`
   returns JSON with `"id"` and the store gains a memory.
3. **Failing test:** `handle_tool_call("luminary_recall", {"query": "..."})` returns valid JSON
   containing a memory; missing `query` returns an error JSON.
4. **Failing test:** unknown tool name returns an error JSON.
5. **Implement.**
6. **Pass.**
7. **Commit:** `feat: luminary recall/ingest/list tools`

**Verification:**
```bash
pytest tests/hermes/test_tools.py -q
```

---

### Phase 6 — Packaging, docs, benchmark

#### T11 — `backup_paths`, `plugin.yaml`, docs, CHANGELOG

**Objective:** Make the provider backup-safe and self-documenting; add the directory-install
fallback and refresh the integration docs.

**Files:**
- `src/luminary_memory/hermes/provider.py` — implement `backup_paths()`
- `src/luminary_memory/hermes/plugin.yaml` (new) — `name`, `version`, `description`, `pip_dependencies`, `hooks`
- `docs/hermes-integration.md` — rewrite for the provider (replacing the standalone-skill flow)
- `hermes/SKILL.md` — update to note the provider path is now preferred
- `CHANGELOG.md` — full `0.2.1` entry

**`plugin.yaml` (directory-install fallback):**

```yaml
name: luminary
version: 0.2.1
description: "Luminary Memory — self-hosted memory with 4-strategy recall (semantic, keyword, temporal, graph), RRF fusion, and lifecycle maintenance."
pip_dependencies:
  - "luminary-memory>=0.2.1"
requires_env: []
hooks:
  - on_session_end
```

**`backup_paths()`:** return `[db_path]` only when `db_path` is non-empty and lives outside the
resolved HERMES_HOME (the default is already under HERMES_HOME). Callable without `initialize()` —
resolve from config/env only.

**TDD / verification steps:**
1. **Failing test:** `backup_paths()` with a default config returns `[]`; with `db_path=/tmp/foo.db`
   returns `["/tmp/foo.db"]`.
2. **Implement** + write docs.
3. **Pass.**
4. **Commit:** `docs: provider packaging + backup + integration docs`

**Verification:**
```bash
pytest tests/hermes/test_config.py -q
ruff check src/luminary_memory/hermes
```

---

#### T12 — Hindsight-parity benchmark (resource + latency)

**Objective:** Produce the evidence for "matching/exceeding Hindsight with a fraction of the
resources": a small reproducible benchmark comparing luminary's recall latency and memory
footprint against Hindsight's local_embedded mode on the same synthetic dataset.

**Files:**
- `benchmarks/hermes_provider_bench.py` (new)
- `benchmarks/README.md` — document how to run and what the numbers mean

**Design:** extend the existing `benchmarks/` harness (deterministic, `synthetic.py` data). Measure,
for N memories with a fixed query set:
- luminary recall p50/p95 latency (end-to-end incl. embedding) and peak RSS;
- `luminary-memory lifecycle` duration;
- (reference, manual/opt-in) the same numbers for Hindsight local_embedded, so the comparison is
  reproducible but not a CI requirement (Hindsight's daemon download is heavy).

**Verification:**
```bash
python benchmarks/hermes_provider_bench.py --n 5000 --backend sqlite --report /tmp/lum_vs_hindsight.json
# assert: exit 0, report parses, contains recall p50/p95 + peak_rss_mb for luminary
```

**Commit:** `bench: hermes-provider parity benchmark`

**Risks:** Hindsight local_embedded is a multi-hundred-MB install and a moving target; keep it a
documented optional arm, not a CI gate. The luminary arm alone is CI-safe.

---

## 4. Release checklist (v0.2.1)

- [ ] All tasks `T1`–`T12` merged; `pytest -q` green (≥ 91% coverage)
- [ ] `ruff check src tests` clean
- [ ] `python -m build` produces a wheel containing `luminary_memory/hermes/` + entry point
- [ ] `pip install -e .` then `python -c "from luminary_memory.hermes import register; print(register)"` succeeds standalone (with the ABC stub path for tests)
- [ ] Smoke test in a real Hermes env: `hermes memory setup luminary` → `memory.provider: luminary`
  in `config.yaml` → new session shows the "🌙 Luminary — recalled N memories" indicator after the
  first recall and persists turns to `$HERMES_HOME/luminary/memory.db`
- [ ] `CHANGELOG.md` updated, `__version__ == "0.2.1"`, tag `v0.2.1` + GitHub release + PyPI publish
  (trusted-publisher workflow already in place)

---

## 5. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| First recall triggers a slow fastembed model load | Warm the engine on a background thread in `initialize()` (opt-in via `auto_recall`); document the one-time cost; keep `initialize()` itself non-blocking |
| `MemoryProvider` ABC drift between hermes-agent and the test stub | Stub mirrors signatures only, tagged with a pointer to the authoritative source; runtime always imports the real ABC |
| Retain-per-turn embedding cost grows with session length | `retain_every_n_turns` batching; `ingest_llm` off by default (zero token spend); T12 quantifies and can justify a smarter default |
| Provider imports hermes internals → untestable standalone | Explicit rule: depend only on `agent.memory_provider` + `luminary_memory`; local `tool_error` JSON helper; `hermes_home` via kwargs, never `hermes_constants` |
| Only one external provider at a time — switching away loses nothing but is silent | `backup_paths()` + export/import already cover the store; document migration in `docs/hermes-integration.md` |
| Entry-point discovery resolves `config_schema.py` only for package entry points | Point the entry point at the `luminary_memory.hermes` package (not a bare module); verify `find_provider_dir("luminary")` resolves the dir in the smoke test |
| Dashboard/CLI name collisions with a future bundled provider | The `luminary` name is unique to this package; `list_memory_provider_names()` will show it once installed |

---

*Implementation detail: see `PLAN-v0.2.0.md` for the quality/scale work already shipped. Changelog:
`CHANGELOG.md`. Roadmap: `ROADMAP.md`.*
