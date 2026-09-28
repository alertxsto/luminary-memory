# Repository audit — luminary-memory

## Method and limits

Read the retrieval, API, storage, migration, export/import, tests, documentation, packaging, and release paths. Reproductions used disposable SQLite databases or in-process strategy doubles; no production data was changed. `uv run --extra dev pytest -q` completed at 100% with three skips and no failures. An AST inventory found 527 `test_` function definitions in 59 files; that count is not a claim that every test exercises an independent behavior. The current package version is **0.3.0** in `pyproject.toml:7`, `src/luminary_memory/__init__.py:3`, `src/luminary_memory/hermes/plugin.yaml:2`, and `CHANGELOG.md:3`; there is no *current* version mismatch. A live PostgreSQL server, actual Fastembed model, real Hermes host, and release publication were **not** exercised. PostgreSQL latency and future release outcomes below are identified as code-path inferences rather than measured incidents.

**Critical:** none confirmed. Findings are ranked by user impact within each severity.

## High

### H1. Explicit supersession overwrites an unrelated fact

- **Evidence:** `src/luminary_memory/api.py:554-584,598-607,651-679,682-700`. The claimed `supersedes_id` retires the old same-key row, then `_maybe_replace_explicit` scans **all** active rows in the scope and overwrites its highest-cosine match without requiring the selected ID or claim key to match the specified predecessor. Reproduction with an embedder returning `[1, 0]` for every input: ingest Alice/Acme (`claim_key=alice-employer`, ID 1), Bob/green (`claim_key=bob-color`, ID 2), then Alice/Beta (`claim_key=alice-employer`, `supersedes_id=1`). Result: ID 1 superseded, **ID 2 rewritten to Alice/Beta**, and the third ingest returns 2.
- **Impact:** A legitimate correction destroys a different active memory and corrupts its ownership of the claim lineage. This contradicts the explicit-versioning contract in `docs/api.md:64-70`.
- **Fix:** Resolve and validate the exact predecessor (same scope, key, and ID) before mutation; insert a new version or replace only that validated ID. Make predecessor retirement and new-version write atomic.

### H2. A nonexistent predecessor ID retires valid claims

- **Evidence:** `src/luminary_memory/api.py:554-584,950-956`. In the same-key loop, any non-`None` `supersedes_id` retires another claim; the batch path behaves similarly. Reproduction with `rule_auto_replace=False`: ingest `Alice works at Acme`, key `employer` (ID 1); ingest `Alice works at Beta`, same key, `supersedes_id=99999` (ID 2). ID 1 becomes `superseded`, ID 2 stays `active` with a dangling reference to 99999.
- **Impact:** A typo, stale reference, or caller error makes a valid current fact disappear without a real predecessor relationship.
- **Fix:** Require the referenced ID to exist, be eligible, have the same exact owner and claim key, and be the row being superseded. Reject mismatches before writing either record.

### H3. Malformed ingestion allowlists fail open

- **Evidence:** `src/luminary_memory/ingest/whitelist.py:7-26` ignores invalid regexes and treats an empty compiled set as unrestricted. `src/luminary_memory/api.py:210,431-432` uses this filter at ingest. Reproduction: `Settings(ingest_whitelist=['['])` plus `ingest('secret not approved', enrich=False)` returned an inserted ID; a valid `['^allowed$']` rejected that text.
- **Impact:** A misconfigured restriction can persist material the operator explicitly intended to exclude, including secrets.
- **Fix:** Validate every configured regex at startup and reject invalid configuration; distinguish “no policy configured” from “policy configured but none compiled.”

### H4. Expired rows can exhaust per-strategy top-K before validity filtering

- **Evidence:** Candidate limits are set in `src/luminary_memory/api.py:1866-1911`, but `valid_to` is checked only later at `:1997-2030,2056-2065`; SQL candidate scope at `src/luminary_memory/scope.py:30-79` checks status, **not validity**. Reproduction with zero-vector embedder, strict recall, two recently observed expired rows containing `xy` many times and one older active `xy blueprint approved`: `recall('xy', limit=1, strict=True)` returned `abstain/no_supported_candidate`, while limits 2 or 3 found the valid row. SQLite keyword top-1 was expired, temporal top-2 were expired, and two-character `xy` supplied no graph candidate.
- **Impact:** A current answer exists but is missed solely because expired facts consumed finite candidate slots. Expired graph edges can also expand embeddings: an active row whose `valid_to` was in 2020 made `_expand_query(backend, 'alpha')` return `alpha secretproject` (`src/luminary_memory/recall/semantic.py:140-153`).
- **Fix:** Apply validity windows in backend candidate queries/scans and graph expansion before top-K; retain final checks as defense in depth. Regression-test valid results behind multiple expired hits for small limits.

### H5. Import drops identical text owned by a different tenant

- **Evidence:** `src/luminary_memory/export.py:242-276` deduplicates on content hash alone, omitting user/workspace/agent/session despite the ownership-aware DB invariant at `src/luminary_memory/schema.py:294-299`. Importing two JSON rows containing `same durable fact`, one with `user_id=alice` and one with `user_id=bob`, yielded `{'imported': 1, 'skipped_duplicates': 1}` and only Alice's row in a disposable SQLite store.
- **Impact:** Backups and migrations silently lose one tenant's memories, or mistake another scope's row for an existing copy.
- **Fix:** Key preexisting and within-batch deduplication by the normalized **full ownership tuple plus normalized content hash**, consistent with the unique index.

### H6. Restored supersession references can point to unrelated records

- **Evidence:** Export serializes `supersedes_id` but not original `id` at `src/luminary_memory/export.py:22-56`; import reuses the old ID at `:192-220` while inserts assign new IDs at `:285-303`. Reproduction: export parent ID 1 and child ID 2 (`supersedes_id=1`), seed an unrelated destination ID 1, then import. Destination child ID 3 still has `supersedes_id=1`, now pointing at the unrelated record.
- **Impact:** Restore corrupts claim history and may make later version resolution act on the wrong fact.
- **Fix:** Export stable source IDs; perform a two-pass import mapping old IDs to destination IDs, including deduplicated rows. Reject or explicitly flag unresolved ancestors.

### H7. Version bump stops updating release metadata after 0.2.x

- **Evidence:** `scripts/bump-version.sh:9,22-52` discovers the current version generically but all replacement regexes match `0.2.x` only; `:65-75` warns rather than failing. Read-only regex checks against current `pyproject.toml`, `src/luminary_memory/__init__.py`, and `src/luminary_memory/hermes/plugin.yaml` each found **zero** matches. Plugin dependency text is `luminary-memory>=0.3.0` (`plugin.yaml:4-5`), which also does not match the script's `[hermes]>=0.2.x` pattern.
- **Impact:** Running the script for 0.3.1 only prepends a changelog section, while package/runtime/plugin versions remain 0.3.0; the subsequent release can publish the wrong wheel or fail as a duplicate.
- **Fix:** Replace only an escaped literal `OLD` version in an explicit list of required files, account for actual plugin syntax, and fail on missing replacements or disagreement with the built distribution/tag.

### H8. Publishing is not gated on a passing release build or matching tag

- **Evidence:** `.github/workflows/publish.yml:3-6,12-38` accepts `v*` tags and manual dispatch and builds/publishes without test jobs or a tag-to-wheel version check. `.github/workflows/ci.yml:3-6` runs ordinary CI on branch pushes and PRs, not tag-only pushes. Code path: tag `v0.3.1` on a commit never validated by branch CI; publish runs even if its tests fail or its wheel still reports 0.3.0.
- **Impact:** Broken or misversioned distributions can reach PyPI; the H7 scenario is not caught before publication. **Not release-tested**: this follows the workflow configuration, not an observed publish.
- **Fix:** Gate publish on release-commit tests, package import/smoke, and equality of tag, `pyproject.toml`, runtime version, and built wheel metadata; validate manual dispatch too.

## Medium

### M1. Batch ingest does not detect conflicts introduced earlier in the same batch

- **Evidence:** `src/luminary_memory/api.py:908-979` resolves each prepared row against already-persisted claims, then `:980-1004` inserts the whole batch. On an empty SQLite DB, `ingest_batch(['Alice works at Acme','Alice works at Beta'], metadata=[{'claim_key':'employer'},{'claim_key':'employer'}], enrich=False)` returned two IDs with **both statuses `active`**. Sequential `ingest()` instead marks conflicting claims (`:551-592`).
- **Impact:** Ordinary recall may present contradictory current facts after a documented batch write (`docs/api.md:68-73`).
- **Fix:** Resolve claim-key groups within the batch before insertion or serialize affected groups under one transaction using sequential conflict semantics.

### M2. SQLite FTS repair misses a previously absent update trigger

- **Evidence:** `src/luminary_memory/schema.py:189-212` checks trigger existence **after** `conn.executescript(SCHEMA_SQL)` has recreated missing triggers. Reproduction: write `originalalpha`, drop `memories_au`, SQL-update the text to `replacementbeta`, close/reopen. After reopen `keyword_search('originalalpha')` returned the row with new content; `keyword_search('replacementbeta')` returned nothing.
- **Impact:** A damaged or partly migrated store can return stale keyword evidence indefinitely.
- **Fix:** Record trigger presence before applying DDL and rebuild FTS if any were absent; optionally run a real FTS integrity check on recovery.

### M3. Import revives claim-ledger rows for inactive memories

- **Evidence:** `src/luminary_memory/export.py:211,316-334` restores the memory's status but calls `add_claim` without a claim status; defaults are active in `src/luminary_memory/backends/sqlite.py:436-438` and `src/luminary_memory/backends/pgvector.py:668-670`. Reproduction: export a superseded memory with a superseded structured claim, import into fresh SQLite; restored memory remained superseded but its claim became active.
- **Impact:** Inspection/maintenance of structured claims sees a retired assertion as current.
- **Fix:** Restore claim status/validity with the parent, preferably from exported ledger entries; verify inactive parent cannot have active restored claims.

### M4. SQLite keyword scores do not use the planner's cross-backend scale

- **Evidence:** `src/luminary_memory/backends/sqlite.py:805-820` returns `-bm25`; `src/luminary_memory/backends/pgvector.py:910-935` returns matched-term fraction. Planner `src/luminary_memory/recall/planner.py:36-40` compares both directly with 0.9, and `src/luminary_memory/api.py:1924-1930,2240-2241` also feeds raw keyword scores into confidence. A one-row exact SQLite match returned `1e-06`, leaving `temporal` enabled, whereas the PG formula for one matched term would be 1.0. `tests/test_t3_planner.py:15-17` injects 0.95 instead of exercising real SQLite scoring. PG result here is a **code-path calculation, not a live PG run**.
- **Impact:** Planner behavior and keyword confidence differ by backend; the documented “strong keyword skips temporal” rule (`docs/recall.md:93-95`) fails on ordinary small SQLite stores.
- **Fix:** Normalize lexical evidence to the same defined scale before planner/confidence decisions, or base the gate on term coverage independently of BM25 rank; keep BM25 for within-list ordering.

### M5. Final ranking and public scores replace weighted RRF with confidence

- **Evidence:** RRF correctly adds `weight/(k+rank+1)` for labeled lists at `src/luminary_memory/recall/fusion.py:15-35`; default rank-one semantic and keyword contributions are 0.4/61 and 0.3/61. But `src/luminary_memory/api.py:2274-2276,2342-2343` sorts by a separately constructed confidence and returns confidence, not fused score. With only keyword candidates `[('alpha', 0.2), ('alpha beta', 0.1)]` for query `alpha beta`, RRF ranks the first ID above the second (0.004918 vs 0.004839); `recall(limit=0)` returned the **second first**, with scores 0.9 and 0.3375.
- **Impact:** Tuning RRF weights/rank constant may not control returned order as `README.md:225-228` and `docs/recall.md:79-95` imply; callers cannot interpret `RecallResult.scores` as the documented RRF score.
- **Fix:** Specify whether the contract is confidence-first or fused-rank-first. Preserve fusion order when only gating is intended, or document the final rerank and expose fused score and confidence separately; test the chosen ordering.

### M6. Graph edge cap omits entities based on alphabetical position

- **Evidence:** `src/luminary_memory/recall/graph.py:36-47,63-106` sorts all extracted entity names, then creates only the first eight pairs; the “earliest entities are most salient” comment is false after sorting. A memory containing `alpha bravo charlie delta echo foxtrot golf hotel india juliet` indexed successfully but `graph_recall('juliet')` returned `[]` while `graph_recall('alpha')` found it. With 120 distinct tokens, indexing issued roughly 120 entity inserts plus 120 lookups but retained only 16 directed edges; a query for the last token still returned no graph hit.
- **Impact:** Graph recall and graph-based query expansion silently miss valid relations; indexing large text performs avoidable SQL even though edges are capped.
- **Fix:** Choose salient entities before the edge cap, ensure each indexed entity can have a meaningful relationship, and batch entity ID resolution/inserts.

### M7. `recall(limit=0)` silently loses every candidate beyond 500

- **Evidence:** `src/luminary_memory/api.py:1826-1830,2328,2376-2395` declares zero unlimited; `src/luminary_memory/recall/dedup.py:33-50` first truncates scored candidates to `scored[:500]`, then deduplicates that prefix. A public `recall('item', limit=0)` with 501 distinct strategy candidates and sufficient token budget returned 500, last ID 500; `tests/test_t11_limit_zero.py:36-44` only requires one result.
- **Impact:** Large-K and unlimited exports via recall omit relevant distinct rows without warning.
- **Fix:** Compare each candidate against at most 500 retained candidates without discarding the rest, or document/enforce an explicit output cap distinct from dedup comparison cost.

### M8. Fallback results bypass the promised token budget

- **Evidence:** `src/luminary_memory/api.py:2154-2222` returns importance/temporal fallback results early; common-path `truncate(..., token_budget=budget)` runs only at `:2328-2331`. A memory with six words, importance 0.99 and `access_count=-1` (accepted by `update`) made temporal scoring fail, then `recall('unmatchedquery', token_budget=1)` returned `status='fallback'` with all six words. A strategy-double reproduction with all four strategies empty produced the same result. `docs/config-reference.md:76` calls the budget a hard cap.
- **Impact:** Context limits fail exactly when a degraded strategy triggers fallback.
- **Fix:** Send every fallback through shared dedup/budget/limit finalization; reject negative access counts or make temporal scoring resilient so degraded operation does not become routine.

### M9. Storage/search failures appear to be successful empty searches

- **Evidence:** `src/luminary_memory/api.py:1251-1280` catches every backend error and returns `[]`; `:1924-1950` silently drops failed recall strategies. Replacing `backend.keyword_search` with a function raising `RuntimeError('database failure')` made `client.search('anything')` return `[]`. `tests/test_api_extended.py:179-188` explicitly pins empty-on-error behavior.
- **Impact:** Callers cannot distinguish an outage/corrupt index from a genuine negative answer; recall may present an unrelated fallback instead.
- **Fix:** Preserve expected compatibility-signature handling, but surface operational failures as typed errors or explicit degraded/error status; log per-strategy failures and avoid claiming a normal empty result if all paths fail.

### M10. Public `Settings.recall_min_score` is ignored by `MemoryClient.recall`

- **Evidence:** `src/luminary_memory/config.py:70,141` exposes the setting, and `docs/config-reference.md:78` says sub-floor memories are dropped. No consumer exists in `src/luminary_memory/api.py:1815-2399`; the Hermes provider independently applies its own `_config` floor at `src/luminary_memory/hermes/provider.py:1949-1951,2378-2380`. With `Settings(recall_min_score=1.0)`, direct `client.recall('xy')` returned a memory scored **0.95**.
- **Impact:** Applications relying on the advertised score floor may treat weak evidence as an acceptable answer.
- **Fix:** Apply the setting to the finalized public results in both normal and fallback branches, or remove it from the public Settings contract and explicitly limit it to Hermes configuration.

### M11. Invalid RRF constants cause runtime division by zero

- **Evidence:** `src/luminary_memory/config.py:18-26,67` accepts any integer, `src/luminary_memory/api.py:1859-1861,2114-2119` passes it through, and `src/luminary_memory/recall/fusion.py:33-34` divides by `k+rank+1`. With `Settings(rrf_k=-1)`, ingesting a matching fact and calling `recall('deploy target')` raised `ZeroDivisionError` on its first candidate.
- **Impact:** A single bad environment value takes recall down instead of producing a clear configuration error.
- **Fix:** Validate `rrf_k >= 0` at configuration creation and reject nonfinite/negative score weights and other bounded numeric settings before they reach ranking.

### M12. Corrupt numeric SQLite cells escape the corruption guards

- **Evidence:** `src/luminary_memory/backends/sqlite.py:31-44,113-164` catches `TypeError`/`ValueError` around `int(float(value))` but not `OverflowError`. After SQL-updating a row's `ttl_seconds='1e999'` and `access_count='NaN'`, `get(1)`, `all()`, and `keyword_search('robust')` each raised `OverflowError: cannot convert float infinity to integer`.
- **Impact:** One malformed persisted row can make reading/searching the store fail; this contradicts the intended graceful corruption handling.
- **Fix:** Reject nonfinite intermediates and catch `OverflowError`, then apply safe defaults to the affected field only.

### M13. PostgreSQL hot paths still use full-row scans, per-row writes and missing FK-side indexes

- **Evidence:** PG defines no `temporal_scan`, `get_many`, `delete_many`, or `touch_memories`; thus `src/luminary_memory/recall/temporal.py:125-134` calls PG `all()` (`src/luminary_memory/backends/pgvector.py:779-783`, `SELECT *`), `src/luminary_memory/api.py:2368-2374` updates each recalled memory individually, and base `get_many`/`delete_many` loop at `src/luminary_memory/backends/base.py:39-50`. The PG schema at `src/luminary_memory/backends/pgvector.py:161-164,174-198,233-274` does not index `relations.memory_id`, `claims.memory_id`, `memory_evidence.memory_id`, or `claim_evidence.claim_id`, despite FK-side filters such as `:755-759`.
- **Impact:** **[INFERENCE; no live PG benchmark]** Every temporal pass can transfer/decode the entire store, retrieval/access marking and batch maintenance require N round trips, and FK updates/deletes may scan large tables.
- **Fix:** Implement lean scoped temporal scan, batched access bumps/gets/deletes, and indexes for the actual join/filter columns; benchmark under a live PG workload.

### M14. SQLite semantic and temporal paths allocate/scan entire stores per query

- **Evidence:** `src/luminary_memory/backends/sqlite.py:875-908` fetches every embedding BLOB, constructs NumPy views and `np.vstack(valid)` copies them into a dense matrix on every vector search; `src/luminary_memory/recall/temporal.py:55-104` scores and fully sorts every lightweight temporal row even when the caller requests one result. Top-K optimization only occurs **after** full vector loading and after the temporal sort.
- **Impact:** **[INFERENCE; no large-store memory benchmark]** Cost and transient allocations grow with corpus size and embedding dimensions, not the requested K; e.g. 100k × 384 float32 vectors occupy about 154 MB for the copied matrix alone, in addition to fetched BLOBs.
- **Fix:** Use a maintained vector index/cached matrix with correct write invalidation, and a bounded heap/SQL top-K for temporal scans; measure allocations and latency against the documented corpus sizes.

### M15. Hermes integration is tested against a synthetic host, not the real contract

- **Evidence:** `tests/conftest.py:16-29` installs a stub `agent.memory_provider` into every test run; `hermes/test.sh:59-82` injects the same stub for its advertised runtime smoke and substitutes the embedder. `tests/hermes/test_entrypoint.py:6-21` inspects metadata, not a real host lifecycle.
- **Impact:** **[INFERENCE; real host not exercised]** An upstream callback/signature or dispatch change can pass all local tests and fail on user installation.
- **Fix:** Retain fast stub unit tests but add a separately isolated, versioned real-Hermes install/entry-point/session smoke job.

### M16. Default model behavior is not exercised by the test suite

- **Evidence:** `tests/test_embeddings.py:6-19,22-46` replaces `TextEmbedding` with a constant-vector fake; `tests/test_recall_semantic.py:6-25` injects vectors; `hermes/test.sh:79-82` also substitutes a fake. `pyproject.toml:24` permits any future `fastembed>=0.4.0` version. The suite can be green without running the actual default embedding model.
- **Impact:** **[INFERENCE; real model not exercised]** First-use model load or semantic behavior may regress undetected, particularly as dependencies change.
- **Fix:** Add a cached model-backed smoke case with a nontrivial semantic retrieval assertion in release CI, separate from deterministic vector unit tests.

### M17. Hermes installer can activate a stale installed package

- **Evidence:** `hermes/install.sh:51-53` invokes `pip install -q 'luminary-memory[hermes]'` without `--upgrade` or a version floor; `:58-95` verifies host capabilities and the existence of an entry point but not the installed Luminary version. On a Hermes interpreter with an older distribution already satisfying the unconstrained requirement, pip leaves it installed while the script proceeds to activation.
- **Impact:** **[INFERENCE; not run against a preinstalled old distribution]** A user running the current install script can end up with old provider behavior despite current hooks/config.
- **Fix:** Install a specified checkout/release or use a pinned minimum with upgrade, verify installed distribution metadata and entry-point import before changing Hermes authority.

## Low

### L1. SQLite core-tag lookup treats tag characters as SQL wildcards

- **Evidence:** `src/luminary_memory/backends/sqlite.py:651-657` uses `LIKE '%"{tag}"%'` without escaping `%` or `_`; `by_tag_top('co%re', 3)` returned a memory tagged only `core` in a disposable store.
- **Impact:** A requested literal core tag containing wildcards can load a different tag's memory into always-loaded context. SQL is parameterized, so this is matching semantics, not SQL injection.
- **Fix:** Query JSON array membership with `json_each` or escape LIKE wildcards explicitly; test literal `%` and `_`.

### L2. Several fusion/limit tests cannot catch the reported regressions

- **Evidence:** `tests/test_fusion_rrf.py:25-37` compares a function call with itself for determinism and checks only ID sets for different `k`; no assertion checks weighted fractions, tie policy, invalid constants, or final API ordering. `tests/test_recall_orchestrator.py:40-46` ingests exactly the same text twice, exercising write-time dedup rather than near-duplicate recall. `tests/test_t11_limit_zero.py:36-44` tests unlimited recall with one relevant fact.
- **Impact:** The M5/M7 behavior can change while these tests remain green.
- **Fix:** Replace tautologies with expected numerical weights and observable final order; use distinct near-duplicate rows and more than 500 distinct candidates for the unlimited contract.

### L3. Degraded-path tests accept empty output as success

- **Evidence:** `tests/test_api_extended.py:191-211,288-309` stores a fact, breaks retrieval/snippets, then asserts only `result is not None`; `hermes/test.sh:103-105` asserts `len(res.memories) >= 0`, which every list satisfies.
- **Impact:** Dropping all fallback memories or snippets passes the purported resilience checks.
- **Fix:** Assert the stored fact is returned when an alternative strategy exists, or assert a precise abstention/error when none does; delete the `>= 0` assertion.

### L4. Algorithm descriptions also disagree on ordering of stages

- **Evidence:** `README.md:29` depicts scope/status/time filtering after RRF, while `src/luminary_memory/api.py:1952-2065` filters before fusion. `docs/config-reference.md:74-75,80` says cliff compares with the top score, dedup precedes ranking, and a strong keyword skips semantic/graph; the code compares adjacent confidence values at `src/luminary_memory/api.py:2316-2326`, deduplicates afterward at `:2328`, and skips **temporal** only at `src/luminary_memory/recall/planner.py:36-47`. The fusion docstring at `src/luminary_memory/recall/fusion.py:21-26` omits the actual `+1` in `:33-34`; `docs/recall.md:83` has the correct zero-based formula.
- **Impact:** Tuning the documented settings does not have the advertised effect and masks H4/M4/M5.
- **Fix:** State candidate filtering, confidence reranking, adjacent-score cliff, dedup, and planner gates in actual execution order; update the docs when the intended behavior changes.

## What is actually solid

- Labeled weighted RRF itself uses the documented zero-based `weight/(k+rank+1)` formula; absent lists contribute nothing (`src/luminary_memory/recall/fusion.py:28-35`). Ties retain first-insertion order in Python's stable sort, **not** an explicit memory-ID tie breaker. Public results subsequently reorder by confidence (M5).
- Empty public recall queries return an explicit empty/abstain result (`src/luminary_memory/api.py:1843-1852`); zero query vectors cause no semantic hit (`src/luminary_memory/backends/sqlite.py:864-869`); nonfinite input embeddings and persisted importance/confidence have guards (`src/luminary_memory/api.py:62-90`, `src/luminary_memory/backends/sqlite.py:113-175`). Ordinary SQLite FTS user text is escaped into terms and query values are bound (`src/luminary_memory/backends/sqlite.py:47-72,802-817`).
- SQLite list pagination returned IDs `[3, 2, 1]` for `list(limit=0)` and `[2, 1]` for `list(limit=2, offset=1)` in a three-row disposable store; `offset=-1` raised `ValueError` (`src/luminary_memory/api.py:1178-1212`). An empty strict query returned `abstain/empty_query`. These small-page cases do **not** negate the separate 500-candidate recall cap (M7).
- Active exact duplicates have a full-scope unique database index (`src/luminary_memory/schema.py:294-299` and `src/luminary_memory/backends/pgvector.py:321-325`). A disposable two-writer SQLite race returned `[1, 1]` and one stored row; the suite also has a cross-process episode-count assertion (`tests/test_long_term_stability.py:92-131`). SQLite has thread-local WAL connections, a busy timeout, and enabled foreign keys (`src/luminary_memory/backends/sqlite.py:83-106`).
- Some tests assert real invariants: scope isolation (`tests/test_accuracy_safety.py:120-143`), reopen/retrieval/provenance (`tests/test_long_term_stability.py:43-72`), and idempotence across 100 writes (`:75-89`). CI includes a PostgreSQL/pgvector service (`.github/workflows/ci.yml:29-63`), though it was not available for this local audit.

## Prioritized fix order

1. **Protect existing facts and ownership:** H1/H2 validate and atomically apply explicit supersession; H3 fail closed on invalid allowlists; H5/H6 correct scoped import and lineage remapping; M1/M3 bring batch/import claims into the same lifecycle invariants.
2. **Restore answer correctness:** H4 push validity before top-K/expansion; M2 repair FTS; M4/M5 define normalized evidence, planner threshold, and final score/rank semantics; M6 cover all graph entities.
3. **Enforce public contracts and surface failures:** M7/M8 make unlimited recall and token budgets truthful, M9 expose store failures, M10/M11 validate and apply settings, M12 harden corruption paths; L1 fix exact tag matching.
4. **Make releases safe:** H7/H8 fix version bump and add a release gate, then M17 ensure installs upgrade; M15/M16 add real-host/model smokes and replace tautological tests (L2/L3).
5. **Scale measured hot paths:** M13/M14 add PostgreSQL batch/index paths and SQLite bounded/cache-aware ranking; benchmark before claiming performance gains. Update algorithm docs (L4) with the chosen contract.
