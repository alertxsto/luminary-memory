# Recovery status — PARTIAL, NOT a verified replica

`~/Projects/luminary-memory` was deleted from disk on 2026-09-29 00:13 WIB.
All fix-pass work was uncommitted and unpushed, so nothing existed on the remote.
`git log` on `origin/main` is still at `420e6ca` (pre-audit).

This tree was reconstructed by replaying every `edit`/`write` tool call recorded
in the omp session transcripts under
`~/.omp/agent/sessions/-Projects-luminary-memory/`.

## What is trustworthy

| Class | Count | Meaning |
|---|---|---|
| Byte-exact | 33 files | Replay output is identical to a complete `read` snapshot of the file taken after its last edit. These are effectively recovered. |
| Parse-clean, unverified | 89 files | Syntactically valid Python, but no independent snapshot confirms the content. Probably right; not proven. |
| Broken | 4 files | Did not reconstruct. See below. |

`AUDIT.md` (29,022 B) and `FIXES.md` (15,489 B) are byte-exact — the full audit
and fix ledger survived intact.

## What is NOT recovered

- `src/luminary_memory/api.py` — core client; only ~27% of final content was ever
  captured in snapshots.
- `src/luminary_memory/backends/sqlite.py`
- `src/luminary_memory/export.py`
- `tests/test_pg_hot_paths.py`

Replay applied all 228 recorded operations with zero parser errors, so these
files were written — but they were later edited in ways whose patches did not
reconstruct cleanly, and no complete post-edit snapshot exists to fall back on.

## Consequences

- The test suite cannot be run: `api.py` is a syntax error, and it is imported by
  essentially everything.
- The earlier verified result (**599 passed, 4 skipped**, vs **524 passed, 3
  skipped** on pristine HEAD) applies to the *original* tree, which no longer
  exists. It must not be attributed to this reconstruction.
- This tree is **not** a release candidate and **not** a substitute for the lost
  work.

## What genuinely survives

1. `AUDIT.md` + `FIXES.md` — the findings, evidence, fixes and their rationale.
2. GitHub issues #11–#14 on `alertxsto/luminary-memory` (pushed, so they are safe):
   graph-expansion false positive, confidence-gate false negative,
   real-model release gate, benchmark comparability.
3. The subagent reports under
   `~/.omp/agent/sessions/-Projects-luminary-memory/.../*.md`
   (`SupersessionFix.md`, `PipelineFix.md`, `ExportFix.md`, `CandidateFix.md`,
   `SqliteHotPathFix.md`, `PgHotPathFix.md`, `ReleaseSafetyFix.md`, and the three
   audit reports).

Because `FIXES.md` records every finding with `file:line`, the fix set is
re-derivable — but re-doing it is a fresh effort, not a restore.

## Preserved on the remote

Committed and pushed as branch `recovered/fix-pass` (commit `d49b2fa`, based on
`420e6ca` = `origin/main`), so this partial state is no longer only on one disk:

    https://github.com/alertxsto/luminary-memory/tree/recovered/fix-pass

Branch only. No pull request, no merge into `main`; the 4 broken files above
make this branch non-buildable by design.

## Attempt to recover the 4 broken files (option a)

Every reconstruction route was tried and exhausted:

1. **Replay all 228 recorded `edit`/`write` operations** with a correct
   simultaneous-coordinate patch interpreter (ops use *original* line numbers,
   so inserts must not shift later ops). Result: 0 parser errors, all ops
   applied — yet `api.py` came out at 2415 lines against a final size of 2318,
   and 4 files still failed `ast.parse`. Root cause: `PUT A.=B` replaces a range
   with a *replacement list*, not an insertion, and some ops were applied twice
   on retry; the exact semantics are not fully determined by the transcripts.
2. **Merge every partial `read` snapshot per file.** Snapshots span ~15 distinct
   file revisions (`total=N` in the `[Showing lines …]` footer). Line numbers are
   only valid within one revision, so cross-revision merges produce corrupted
   text — confirmed by duplicated decorators and impossible syntax.
3. **Era-restricted merge** (only snapshots whose declared `total` matches the
   file's final revision). Coverage collapses:

   | file | final lines | covered | % |
   |---|---|---|---|
   | `api.py` | 2318 | 524 | 22.6% |
   | `backends/sqlite.py` | 1026 | 105 | 10.2% |
   | `export.py` | 430 | 47 | 10.9% |
   | `tests/test_pg_hot_paths.py` | 314 | n/a | mixed eras, invalid |

   An earlier "100% coverage" reading for `test_pg_hot_paths.py` was an artifact
   of the `total=None` bucket, which mixes revisions and is therefore meaningless.
   The generated `.partial` files were deleted rather than shipped as plausible
   nonsense.

**Conclusion: these 4 files are not recoverable from the transcripts.** They are
the files with the largest post-edit deltas and the least complete snapshot
coverage. Re-deriving them from `FIXES.md` is a fresh implementation task.
