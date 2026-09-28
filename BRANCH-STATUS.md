# Branch status — partial, not a release candidate

This branch carries an incomplete data-integrity fix set. It exists so the work
stays reviewable; it is not a release candidate and not a merge source.

## What is verified

| Class | Count | Meaning |
|---|---|---|
| Byte-exact | 33 files | Identical to the last complete read of the file. Effectively settled. |
| Parse-clean, unverified | 89 files | Valid Python, but no independent record confirms the content. Probably right; not proven. |
| Broken | 4 files | Do not build. See below. |

`AUDIT.md` (29,022 B) and `FIXES.md` (15,489 B) are byte-exact: the full audit
and the fix ledger survived intact.

## Files that do not build

- `src/luminary_memory/api.py` — core client.
- `src/luminary_memory/backends/sqlite.py`
- `src/luminary_memory/export.py`
- `tests/test_pg_hot_paths.py`

The test suite cannot run while `api.py` fails to parse, and nearly every module
imports it.

## Consequences

- Treat every number produced on this branch as unverified.
- Do not attribute test results from any other tree to this branch.
- The fix set is re-derivable from `FIXES.md`, which records every finding with
  `file:line`; re-doing it is a fresh effort, not a restore.
