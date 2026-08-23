# Changelog

## [Unreleased]

### Fixed

- **Active-task session continuity** — every accepted Hermes turn now enters a
  strictly scoped, non-durable episode ledger before LLM curation. When durable
  recall abstains, recent current-session turns are injected as untrusted
  reference context, and ambiguous follow-ups stay within the active task
  unless the user requests a history-wide operation. No Hermes source patch or
  language-specific classifier is used.
- **Autonomous post-turn reconciliation** — Hermes now runs a serialized,
  provider-owned evidence review after curated automatic retains. It can save a
  grounded new fact or explicitly supersede/retract a scoped claim without
  language-specific heuristics, a second memory authority, or a Hermes source
  patch. Malformed/failed reviews fail closed and leave the writer alive.
- **Language-neutral graph entities** — graph extraction no longer uses an
  English stopword list or ASCII-only tokenization; Unicode tokens are retained
  through a structural filter so retrieval does not privilege one language.
- **Atomic cross-process exact deduplication** — SQLite and pgvector now
  enforce a scoped unique active-memory invariant, repair legacy duplicates
  during schema initialization, and return the winning row without creating
  duplicate episode/evidence/graph lineage.
- **Rule-replacement source lineage** — every in-place replacement now records
  a distinct raw episode and claim version, retiring the old structured claims
  as `superseded` instead of leaving the source ledger stale.
- **Evidence fail-closed in every recall mode** — `evidence_required` now
  filters permissive recall and importance/temporal fallbacks too; fabricated
  quotes and source labels cannot become answer support.
- **Scoped JSONL transparency events** — Hermes logs per-home `trace_id`,
  operation, scope, status/reason, result counts, confidence, and latency while
  omitting prompt/memory content and credentials.
- **PostgreSQL import/transaction polish** — missing export timestamps receive
  UTC defaults, inactive history does not block an active restore, scoped
  imports do not dedup against global compatibility rows, and unique-conflict
  recovery closes the lookup transaction for long-lived writers.
- **Deep long-term correctness audit** — scoped clients no longer mutate
  compatibility-visible global rows during recall, lifecycle, or LLM
  maintenance; malformed update state is normalized and content hashes are
  repaired before future deduplication.
- **Atomic claim ledger writes** — a failed `claim_evidence` insert rolls back
  its parent claim, while independent claims continue to be recorded when one
  malformed/external claim fails.
- **Truthful Telegram activity delivery** — the hook requires Telegram's
  `{"ok": true}` envelope, retries malformed/API/network failures, excludes
  soft-deleted rows from counts and content, and acknowledges inactive-only
  backlog rows without emitting a misleading message; HTTP error logging does
  not stringify token-bearing request URLs.
- **CI coverage of the actual integration surface** — `develop` pushes now
  trigger CI and Ruff checks include the Telegram hook.
- **Hermes activation boundary** — the installer and standalone activation
  helper update only the documented top-level `memory` block, preserve
  unrelated YAML and existing profiles, use the selected Hermes interpreter,
  and fail visibly when the public provider capability is unavailable.
- **Authority repair utility** — added a dry-run-first SQLite migration helper
  that identifies imported authority snapshots and structurally uncurated
  Hermes rows, creates a consistent backup before `--apply`, archives instead
  of deleting, and records an audit event.
- **Documentation contract sync** — tracked guides and the static website now
  describe the three context surfaces, exact tool schemas, stable core ordering,
  provider/runtime boundary, hook cursor resolution, and the current `505`
  regression baseline.

### Tests & documentation

- Added scope, lifecycle, hash-repair, claim-rollback, inactive-hook, and
  malformed-Telegram-response invariants to the long-term regression suite.
- Current verification: `505 passed, 3 skipped`, `83%` full-source coverage
  (`4,866` statements, `837` missed), and clean Ruff. The controlled gold
  fixture remains a regression signal, not a matched Mem0/Hindsight accuracy
  claim.

## [0.2.18] - 2026-08-20

### Changed

- **Importance is now retrieval-only.** The importance-based persistent-context
  family (`context_top_n`, `context_budget`, `context_min_importance`) was
  **removed**. Importance now scores query relevance and drives pruning only; it
  no longer pins memory into the system prompt as rules that could override a
  live user instruction.
- **Core = DB-backed `MEMORY.md`.** Rules tagged `core` remain auto-loaded every
  session (the durable-rules channel the user chooses), injected with an
  explicit subordinate label so a live instruction always wins.
- **Docs & skill** synced to the new importance model; skill version bumped to
  `2.1.0`.
- **Accuracy-first provider path** — Hermes and the CLI now force strict
  recall, evidence-required results, and non-destructive rule handling. Scope,
  validity, status, confidence, content hashes, evidence quotes, claim
  history, and append-only audit events are preserved through ingest/recall.

### Added

- **Recall noise filter** — shell/terminal artifacts (`&&`, `===`, `echo `,
  etc.) and near-empty content are dropped before they can pollute context.
- **Destructive-imperative suppression** — a query that is a destructive
  instruction (`hapus`, `delete`, `remove`, `stop`, `disable`, ...) suppresses
  the recall block so the agent follows the instruction instead of re-anchoring
  on the stored topic.
- **Scoped claim/evidence schema** — ownership fields, episodes, claims,
  claim evidence, memory evidence, conflict/supersession status, and
  `needs_reindex` repair state are migrated idempotently for existing SQLite
  stores and represented in pgvector.
- **Independent gold regression arm** — the benchmark now reports abstention,
  unsupported-answer, evidence-support, and cross-scope metrics from a fixed
  fixture instead of presenting circular synthetic labels as accuracy proof.

### Removed

- `context_top_n`, `context_budget`, `context_min_importance` from provider
  `_DEFAULTS`, dashboard schema, and `Settings`. Recalled context is capped by
  `token_budget` (`2048`) / `recall_limit` (`10`); core by `core_top_n` (`12`) /
  `core_budget` (`8000`).

## [0.2.17] - 2026-08-19

### Fixed

- **OpenAI-compatible gateway envelope unwrapping** — gateways and reverse
  proxies (such as the Cline Pass Gateway `api.cline.bot` or certain API
  aggregators) wrap standard ChatCompletion response bodies inside a top-level
  `{"data": {"choices": [...]}}` envelope. `_call_llm()` now automatically
  unwraps the `data` dictionary if present, preventing empty strings from
  causing silent memory curation drops (`retain skipped (LLM: no curated summary)`).
  Fully backward-compatible with standard OpenAI endpoints.

### Enhanced

- **Telegram activity hook robustness (`luminary-activity`)**:
  - **Special character escaping** — memory content with unescaped Markdown
    special characters (`_`, `*`, `` ` ``, `[`, `]`) is now automatically escaped,
    preventing HTTP 400 Bad Request parsing rejections from Telegram Bot API.
  - **Visual pin indicator** — durable rules (`importance >= 0.85` or tagged
    `core`/`rule`) are now rendered with a `📌` icon for immediate visual clarity,
    distinguishing rules from regular factual notes (`•`).
  - **Batch overflow counter** — turns with $> 3$ memories display the top 3 items
    and a summary counter `... (+N more)`, tracking all processed IDs cleanly.
  - **Self-recovery `.env` fallback & topic thread routing** — parses `~/.hermes/.env`
    automatically if subprocess environment variables are missing, and routes to
    `TELEGRAM_HOME_CHANNEL_THREAD_ID` forum topics.
- **LLM enricher transient error retry** — 1x defensive retry on transient network
  glitches with exponential backoff. When provider curation is enabled but no
  durable summary is produced, Hermes drops the turn instead of storing a raw
  transcript as a false fact.

### Tests

- Added regression tests `test_unwrap_data_envelope` and `test_unwrap_data_envelope_plain_shape`.
- Added retry resilience test `test_call_llm_retries_on_transient_error`.
- Added hook test cases for Markdown character escaping, visual pin icons, and batch overflow.


## [0.2.16] - 2026-08-19

### Added

- **Complete dashboard config coverage** — 7 provider-config keys that were
  active at runtime but invisible in the dashboard (`context_top_n`,
  `context_budget`, `context_min_importance`, `core_tag`, `core_top_n`,
  `core_budget`, `extract_on_session_end`) are now exposed in `CONFIG_SCHEMA`
  and editable via `Settings → Memory` in the Hermes dashboard.
- **`importance_recall_boost` in provider config** — previously env-var-only
  (`LUMINARY_IMPORTANCE_RECALL_BOOST`), now also available as a `config.json`
  key and dashboard field. Dashboard value overrides the env-var default.
  Controls the ranking multiplier for high-importance (≥ 0.8) memories in recall.

### Docs

- **`docs/config-reference.md`** (new) — single authoritative reference for
  every config input: all 37 `Settings` env vars (library-level) + all
  `_DEFAULTS` provider keys, with defaults, allowed values, and meaning.
- `docs/index.md` — link to config-reference.
- `docs/hermes-integration.md` — link to config-reference; `importance_recall_boost`
  now correctly documented as both a provider config key and env var.

## [0.2.15] - 2026-08-18

### Added

- **Adaptive importance on recall** — memories that keep getting recalled are
  re-estimated immediately after the access bump (same `estimate_importance`
  as the lifecycle), so frequently-used memories climb toward the top of the
  next turn's persistent-context block. Pinned rules (≥ 0.9) are never
  downgraded. Enabled via the existing `LUMINARY_IMPORTANCE_AUTO`.
- **Rule-aware query expansion** — when the knowledge graph yields no entity
  to expand a short query, up to two keywords from a durable rule whose topic
  overlaps the query are appended before embedding. The original query tokens
  stay, so recall quality can never regress.

### Fixed

- **Content-level anti-duplication** — a memory whose text is already in the
  core block was still re-injected by persistent context or recall when it had
  a different id (e.g. the same rule stored both as `core` and as a plain
  high-importance memory). Dedup now tracks content hashes alongside ids, so
  identical text appears **exactly once** per turn across core/persistent/
  recall.

### Tests

- Core memory integrity: core sourced only from the DB `core` tag (never from
  recall/injected ids), high-importance non-core memory never leaks into the
  core block, content independent of `_injected_ids`.
- Anti-dup 3-way (core/persistent/recall) appears-once invariant.
- Adaptive importance: recalled memory outranks idle memory; pinned rule never
  drops below 0.9.
- Query expansion: rule keyword appended on topic overlap; unrelated query
  unchanged.

### Docs

- `docs/hermes-integration.md` — core memory sourcing + content-level dedup.
- `docs/recall.md` — rule-aware query expansion.
- `docs/lifecycle.md` — adaptive importance on recall.

## [0.2.14] - 2026-08-18

### Fixed

- **FTS5 index rebuild on schema upgrade** — a database created before the
  FTS5 virtual table existed left every pre-existing memory keyword-invisible
  (keyword recall returned zero hits even though the store was full). `init_schema`
  now detects the upgrade and runs a one-time FTS `rebuild`.

### Changed

- `by_tags` uses the top-level `json` import instead of a redundant local one.

### Removed

- Dead `_FTS5_SPECIAL` constant (unused; `_sanitize_fts_query` relies on a regex).

### Tests

- Extended backend coverage (real `SQLiteBackend`, no stubs): FTS injection
  sanitization, FTS sync through update/delete, keyword OR-join multi-term,
  `vector_search` ordering/limits/degenerate-query, `by_tags` multi/corrupt,
  `temporal_scan`, `scan_embeddings` vs matrix consistency, `recent`
  pagination edges, embedding float32 round-trip, and a 4-thread
  concurrent recall+ingest test.
- Schema: FTS rebuild on upgrade + idempotent reopen tests.

### Docs

- `docs/backends.md` — SQLite section now documents FTS5 external-content
  triggers + rebuild migration, thread-local connections, lean scans, and the
  WAL status.

## [0.2.13] - 2026-08-18

### Added

- **Core memory (DB-backed)** — memories tagged `core` are auto-loaded into the system prompt every session, before persistent context and recall. The luminary equivalent of Hermes' native `MEMORY.md`, stored in the database: durable rules are present from the very first prompt with no query match needed.
  - Configurable via `LUMINARY_CORE_TAG` (default `core`), `LUMINARY_CORE_TOP_N` (12), `LUMINARY_CORE_BUDGET` (8000 chars).
  - New tools: `luminary_core_add` (pin a rule, importance ≥ 0.9), `luminary_core_remove` (unpin, keeps the memory), `luminary_core_list`.
  - Deduplicated against persistent context and recall (a core memory never appears twice).
- **English default rule keywords** — `LUMINARY_RULE_KEYWORDS` now defaults to English instruction words (`NEVER,ALWAYS,MUST,REQUIRED,MANDATORY,FORBIDDEN,DO NOT,...`) instead of Indonesian, since this is a global open-source repo. Fully configurable per deployment language.

### Fixed

- **`prefetch()` now includes the core-memory block** — previously core rules only reached the system prompt; mid-session turns got core rules only via system prompt. Now merged into every prefetch like persistent context.
- **Anti-duplication across core / persistent / recall** — persistent context no longer overwrites injected ids and now skips memories already in the core block.
- **Keyword recall OR join** — multi-term queries ("use tables in reports") returned 0 hits with FTS5 default AND; terms now join with OR and bm25 ranking lifts the best matches.

## [0.2.12] - 2026-08-18

### Added

- **`max_memories` store cap now actually enforced** — `run_lifecycle()` passes
  the cap to prune; previously the documented cap was never wired into the
  lifecycle, so oversized stores never shrank. Configurable via
  `LUMINARY_MAX_MEMORIES` / `Settings.max_memories` / provider config.
- **`context_*` persistent-context knobs as real env vars** —
  `LUMINARY_CONTEXT_TOP_N`, `LUMINARY_CONTEXT_BUDGET`,
  `LUMINARY_CONTEXT_MIN_IMPORTANCE` now exist on `Settings` (previously only
  provider config.json, which contradicted docs claiming env vars).
- **Vectorized rule auto-replace** — the anti-contradiction scan now uses a single numpy matmul over stored embeddings (`scan_embeddings_matrix`), ~40× faster than the per-memory Python cosine loop on a 5k store, with identical results.
- **Lean persistent-context scan** — the per-turn top-N-by-importance build (`top_by_importance`) reads only `id/content/importance/access_count` columns, never embedding blobs: ~100 ms → ~5 ms on a 5k store.
- **Batched access bookkeeping** — recalled memories are marked accessed in one `UPDATE ... WHERE id IN (...)` (`touch_memories`) instead of one write per result row.
- **Batched lifecycle passes** — prune uses `delete_many`, importance re-estimation uses `update_importances`; one statement per pass instead of one write per memory.
- **Batched temporal fetch** — temporal recall fetches top ids with one `SELECT ... WHERE id IN (...)` (`get_many`) instead of N per-id queries: ~30-67 ms → ~16-19 ms on 5k.

### Fixed

- **`max_memories` was documented but never enforced** by the lifecycle — now wired end-to-end (Settings → `run_lifecycle` → `prune(max_count)`).
- **Docs env-var drift** — `LUMINARY_CONTEXT_*` and `LUMINARY_MAX_MEMORIES` are now real env vars; docs and benchmark numbers (77 ms @ 5k, 9 ms @ 1k) match measured results.

## [0.2.11] - 2026-08-18

### Added

- **Persistent context injection** — the system prompt injects top-N memories by importance (configurable `context_top_n` / `context_budget` / `context_min_importance`), so durable rules are always visible regardless of query.
- **Rule pinning** — memories at importance ≥ 0.9 are pinned: they survive lifecycle prune and consolidation (never deleted as duplicates or pruned by the max-count cap).
- **Rule auto-replace (anti-contradiction)** — ingesting a rule semantically similar to an existing one (cosine ≥ `rule_auto_replace_threshold`, default 0.85) replaces it in place instead of stacking conflicting rows.
- **Per-turn persistent context** — the persistent-context build runs on every prefetch (not just session-start system prompt), so memories ingested mid-session reach the model; merged with query recall under anti-duplication.
- **Recall hook notification** — Telegram hook (`luminary-activity`) surfaces stored/recalled memories to the chat.

### Fixed

- **Prefetch recall cross-thread crash** — SQLite thread-local connections; background recall no longer crashes with `ProgrammingError`, so recall actually triggers.
- **`max_tokens` sent in enricher LLM call** — Command Code returned empty content without it (issue #8); configurable via `LUMINARY_LLM_MAX_TOKENS`.
- **Raw transcripts pinned as rules** — rule keywords are now checked only against the LLM-curated summary, never the raw turn text; a transcript that merely mentions a keyword is no longer flagged importance 0.9.
- **Raw-transcript store pollution** — with `ingest_llm` on, turns whose curation yields no summary are dropped instead of stored verbatim.
- **Dashboard config save** — `save_config` accepts the `hermes_home` argument (dashboard contract).

## [0.2.10] - 2026-08-18

### Added

- **Smarter recall** — weighted RRF fusion (semantic 0.4, keyword 0.3, graph 0.2, temporal 0.1) so high-signal strategies dominate; query expansion appends co-occurring graph entities to short queries before embedding.
- **`max_memories` store cap** — hard limit on store size (default 1000); oldest/lowest-importance memories pruned when exceeded. Configurable via dashboard (21 settings).

### Fixed

- **Memory store overflow** — the LLM curation prompt is now selective (no duplicates, one fact per entry, skip meta-talk), so work-log turns no longer bloat the store (139 → 46 memories after cleanup).
- **`import_memories` dedup guard** — bulk imports (e.g. MEMORY.md/USER.md merges) skip content that already exists, reporting `skipped_duplicates`.
- **SQLite cross-thread close crash** — `close()` no longer raises when the connection is owned by another thread (provider writer-thread shutdown).

### Website

- Redesigned benchmarks (line table in panel), architecture (turn-loop flow), use cases (narrative list) — moonlit editorial preserved, contrast fixed (text-faint 3.9:1 → 7:1), zero em-dashes.

## [0.2.9] - 2026-08-18

### Added

- **pgvector integration tests in CI** — real Postgres service (HNSW index, JSONB round-trips, update, by_tags, delete) — contribution from @qtjg (PR #2).
- **`add_many` rollback fix** — pgvector batch insert now rolls back and re-raises on failure (mirrors the SQLite backend). Contribution from @qtjg (PR #2).
- **Three new CI workflows:**
  - **Triage** — auto-labels issues/PRs, welcomes first-time contributors.
  - **Stale** — auto-closes inactive issues/PRs (exempts `help wanted` / `good first issue`).
  - **Contributor check** — soft account + language triage hint for maintainers on every PR.
- **Branch protection on `main`** — required status checks + PR review; `develop` is the integration branch.
- **`CONTRIBUTING.md`** — AI assistance notice, branch model, automated checks section, updated pgvector instructions.

## [0.2.8] - 2026-08-18

### Fixed

- **Dashboard save bug** — `consolidate_semantic` and `importance_auto` were missing from `_DEFAULTS`, so the Hermes dashboard rendered them but silently dropped the values on save. Now persisted correctly.

### Docs

- `docs/hermes-integration.md` — config table now covers all **20 provider settings** (added `retain_user_prefix`, `retain_assistant_prefix`, `consolidate_semantic`, `importance_auto`).

### Website

- New use-case card **"A Graph You Can See"** (showcases `luminary-memory graph`).
- New FAQ: **"Can I see how my memories connect?"**.

## [0.2.7] - 2026-08-18

### Added

- **`MemoryClient.graph()`** — returns the knowledge graph as `{entities: [{name, degree, memories}], relations: [{source, target, weight}]}`. Empty-store and non-SQLite safe.
- **`luminary-memory graph` CLI** — top entities as a table (degree + memory count), `--relations` for edges, `--json` for raw output, `--limit`.
- **`luminary-memory version`** — prints installed version + Python runtime.

### Changed

- Roadmap v0.3.0: graph visualization (CLI phase) ticked.

All notable changes to this project are documented in this file. The format follows [Keep a Changelog](https://keepachangelog.com/), and the project adheres to [Semantic Versioning](https://semver.org/).

## [0.2.6] - 2026-08-18

### Polish & hardening

- **Lifecycle logging** — `cleanup`, `consolidate` (mode + merged count), `prune`, and `run_lifecycle` (result + duration) now log their activity; `estimate_importance` logs via the runner.
- **SQLite batch errors logged** — `add_many` failures log the exception before rollback/re-raise (was silent).
- **CLI recall JSON richer** — each memory now includes `source`, `created_at`, and `importance`.
- **Env var warnings** — invalid `LUMINARY_*` int/float values warn instead of silently falling back.
- **Dashboard schema 20 fields** — `consolidate_semantic` (Semantic consolidation) and `importance_auto` (Auto importance estimation) added to the Hermes provider config.
- **`recall(limit=0)` truly unlimited** — passes `None` to backends instead of a 10k magic cap.
- **Dedup capped window** — `dedup_jaccard(max_pairs=500)` keeps recall O(n·k) instead of O(n²) on large result sets.
- **`import_memories` error logging** — failures log the path before re-raise.
- **pgvector JSON columns safe** — `metadata`/`tags` parse via a `_json_load` helper (corrupt data falls back instead of crashing); HNSW index failure now logged.
- **Prefetch thread join** — `queue_prefetch` joins any in-flight worker before spawning a new one (no thread leak / stale-cache overwrite).
- **Degenerate embedding guard** — semantic consolidation falls back to Jaccard when embeddings are all-equal (no false merges of unrelated memories).
- **`CONTRIBUTING.md`** — new Testing section (Postgres/pgvector setup, coverage ≥ 90%) pointing at [issue #1](https://github.com/alertxsto/luminary-memory/issues/1) (add Postgres to CI).

## [0.2.5] - 2026-08-18

### Added

- **Semantic consolidation** — `consolidate(semantic=True)` merges memories by embedding-cosine similarity (default `LUMINARY_CONSOLIDATE_SEMANTIC=true`), catching paraphrases that token-overlap misses; falls back to Jaccard when embeddings are missing. CLI: `luminary-memory lifecycle --semantic/--no-semantic`.
- **Auto importance estimation** — `lifecycle/importance.py:estimate_importance()` scores each memory from access (`log1p`), recency (24h decay), and graph centrality; applied on ingest and re-estimated before every prune (`LUMINARY_IMPORTANCE_AUTO=true`). Pruning and the health score's importance dimension now use live values.

### Changed

- `run_lifecycle()` now also re-estimates importances (returns `reestimated` count).

## [0.2.4] - 2026-08-18

### Added

- **`MemoryClient.health_score()`** — store health report (0-100) across five dimensions: duplicate rate, staleness, importance, graph density, and size — plus actionable recommendations. Empty store scores 100.
- **`luminary-memory health` CLI** — human-readable bar + `--json` output.
- **Test coverage raised 82% → 90%** (roadmap DoD): config_schema standalone shim, enricher `_call_llm`/`review_memories` paths, maintenance CRUD edges, provider lifecycle/maintenance/shutdown, CLI whitelist/limit errors, recall strategy failure fallbacks.

### Fixed

- **`run_maintenance` bad-response detection** — `data.get("actions") or []` masked non-list responses as "no actions"; now correctly reports `{"error": "bad LLM response"}`.

## [0.2.3] - 2026-08-18

### Added

- **Hermes dashboard config schema** — exposes 18 luminary settings (mode, backend, recall limit, token budget, auto-recall/retain, **LLM memory curation**, **auto-maintain**, LLM endpoint, indicators) in the Hermes dashboard Provider panel. `auto_maintain` added; `ingest_llm` label corrected to "LLM memory curation".

### Changed

- **Balanced LLM curation** — the enricher now rejects work/task logs and meta-talk about the memory system itself, while still keeping durable facts (not over-strict). Verified: work logs → `worth_saving: false`; facts → stored.

## [0.2.2] - 2026-08-18

### Added

- **LLM memory curation** — with `ingest_llm: true`, the provider's enricher evaluates every retained turn:
  - `worth_saving` — chit-chat, greetings, and trivial turns are **dropped** instead of polluting the store.
  - `summary` — kept turns are stored as concise factual summaries (e.g. `"Deploy target is the staging cluster."`) instead of raw `User: ... / Assistant: ...` transcripts.
  - `entities` / `tags` — attached for richer recall.
- **LLM store maintenance** — `MemoryClient.run_maintenance()` + provider `auto_maintain` (session-end): the LLM reviews the store and **deletes obsolete/contradicted/duplicate facts**, **updates changed ones**, and **keeps** current ones (verified: stale deploy target auto-removed).
- **Transparency log** — provider writes `$HERMES_HOME/luminary/luminary.log` recording initialize/recall/retain/maintenance/errors.
- **`OpenAICompatibleEnricher` User-Agent header** — required by some OpenAI-compatible gateways (e.g. Command Code 403s without it).

### Fixed

- **Shutdown SQLite thread-affinity crash** — the writer thread now closes its own client (closing from the main thread raised `sqlite3.ProgrammingError`).
- **Hermes installer** — `hermes/install.sh` gains `--llm` (enables memory curation), handles a missing `config.yaml`, and no longer warns about the missing `[hermes]` extra (now declared).

## [0.2.1] - 2026-08-18

### Added

- **Hermes Memory Provider** — `LuminaryMemoryProvider` plugging into Hermes via the `hermes_agent.memory_providers` entry-point group; registered as a standalone package.
  - **Auto-recall every turn** — warm background prefetch (`queue_prefetch` → cached `prefetch`) or synchronous recall (`recall_sync`), formatted as a deterministic context block.
  - **Auto-save every session** — buffered `sync_turn` on a single writer thread, batched by `retain_every_n_turns`, with session/parent/platform/agent lineage tags.
  - **Session-boundary handling** — `on_session_end` flush + `on_session_switch` rebind with reset guard.
  - **Explicit tools** — `luminary_recall`, `luminary_ingest`, `luminary_list` (OpenAI-format schemas, JSON dispatch, local error helper).
  - **Deterministic indicator** — `RecallStatus("Luminary", count, 🌙)` surfaced via `recall_status()`.
  - **Config layer** — `$HERMES_HOME/luminary/config.json` (0600, atomic write), `get_config_schema()`, dashboard `config_schema.py` (pure data).
  - **Lifecycle hooks** — `is_available`, `initialize`, `shutdown`, `system_prompt_block`, `on_memory_write`, `on_delegation`, `on_pre_compress`, `backup_paths`.
  - **Packaging** — entry point + `plugin.yaml` directory-install fallback.
  - **Test harness** — `tests/hermes_stubs/agent/memory_provider.py` ABC stub injected via `tests/conftest.py` so tests run without a hermes-agent install.
- **`MemoryClient.ingest(metadata=...)`** — optional metadata dict merged into stored memory metadata (backward compatible).

### Performance (identical results, no approximation)

- **Vectorized cosine similarity** — per-row numpy loop → single matmul; recall @ 5k memories **3,400 ms → 832 ms (4.1×)**.
- **SQL graph aggregation** — 210k relation rows → `SUM/COUNT ... GROUP BY` in the database.
- **`temporal_scan()`** — temporal recall fetches only `(id, created_at, access_count)`; **486 ms → 62 ms (7.8×)**.
- **Relation cap (8/memory) + indexes** — dense graph (280k rows) → sparse (80k); store 3.5× smaller; ingest 1.6× faster.

### Fixed

- `config_schema.py` import fallback — module now imports standalone (no hermes runtime) so CI is green on 3.11/3.12.
- Publish workflow — skill zip moved out of `dist/` (invalid distribution); dropped `generate_release_notes` (permission).

## [0.2.0] - 2026-08-18

### Added

- **Query planner** — skips graph/temporal strategies when not needed (conservative v1; semantic + keyword never skipped).
- **Batch ingest** — `ingest_batch()` with single `embed_batch` call and per-item whitelist/enrichment.
- **Export / import** — versioned JSON backup/restore (`export`, `import_memories`, `--include-embeddings`).
- **LLM enricher (provider-agnostic)** — `OpenAICompatibleEnricher` over any OpenAI-compatible endpoint; stdlib-only, passthrough on failure.
- **Result snippets** — matched-fragment highlights attached to recall results.
- **Tag-scoped recall** — `recall(query, tags=[...])`.
- **HNSW index** for pgvector (`pg_hnsw_*` settings, idempotent `build_index()`).
- **Benchmark suite** — `benchmarks/` (latency p50/p95 per strategy + recall@k/MRR, deterministic).
- **CLI JSON output** for `search` and `list` (parity with `recall --json`).
- **`--limit 0` semantics** — unlimited; negative values raise.
- **`updated_at` auto-bump** in `update()`.
- **API docs** generated from docstrings (pdoc → `docs/api/`).
- **GitHub Pages workflow** (`pages.yml` → `/website`).
- **PyPI auto-publish workflow** (`publish.yml`, trusted publishing/OIDC, tag `v*`) + Hermes skill zip release asset.

### Fixed

- Ruff lint: unused-variable in HNSW tests, missing `noqa` on intentional defensive excepts (CI now green).

## [0.1.1] - 2026-08-17

### Fixed

- `MemoryClient.ingest` crashed when `ingest_llm=True` (enricher could be `None`). Now always falls back to a no-op enricher.
- `_parse_dt` crashed on corrupt/non-ISO timestamps in lifecycle and temporal recall. Now falls back safely.
- FTS5 keyword search accepted raw query syntax (`*`, `NEAR`, `OR`, quotes) which could alter query semantics or raise. Queries are now sanitized to plain terms.
- `list()` loaded and sorted all memories in memory; now uses SQL-level pagination (`recent()`).
- CLI commands could print raw tracebacks on backend errors; now caught with a clean error message. `--limit` values are clamped to `>= 1`.
- `WhitelistFilter` crashed on an invalid regex pattern; invalid patterns are now skipped.
- pgvector integration smoke test was a no-op; now a real add/get/search/delete round-trip.

### Added

- Test coverage for pgvector backend raised from 51% to 82% (get/update/delete/count/row parsing).

## [0.1.0] - 2026-08-17

### Added

- SQLite backend with FTS5 keyword search and in-process vector search.
- Optional pgvector backend (HNSW-ready).
- Four-strategy recall: semantic, keyword, temporal, graph.
- Reciprocal Rank Fusion (RRF) + Jaccard dedup + token budget.
- Ingest pipeline with whitelist filter and optional LLM enrichment.
- Lifecycle: TTL cleanup, near-duplicate consolidation, low-value pruning.
- Python API (`MemoryClient`) and CLI (`luminary-memory`).
- Environment-variable configuration (`LUMINARY_*`).
