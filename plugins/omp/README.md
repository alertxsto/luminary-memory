# Luminary memory for omp

Official **Luminary-maintained** oh-my-pi package. This does not mean endorsement
by omp's maintainers. The package builds the canonical Luminary omp adapter, not
a second memory engine. The native extension/plugin contract targets omp
v18.12.6. Source build tooling uses Node.js 22.22.2+ in the 22.x LTS line
(or the other versions accepted by the root manifest); omp uses its own
embedded Bun runtime to load extensions.

## Recommended installer (unreleased source)

**Registry current: 0.3.4. Managed native setup: UNRELEASED.** The next release
version bump is deferred; 0.3.5 has not been staged. These source
instructions are not platform acceptance, registry proof, or release readiness.
Install omp first. Public entry points (`main` may differ from this checkout):

Windows (PowerShell):

```powershell
irm https://raw.githubusercontent.com/alertxsto/luminary-memory/main/install.ps1 | iex
```

Linux / macOS:

```sh
curl -fsSL https://raw.githubusercontent.com/alertxsto/luminary-memory/main/install.sh | sh
```

The installer provisions a uv-managed Python 3.12 bridge and uses native
`omp plugin install luminary-memory-omp@X` user-wide, with a matching available
release `X`. Native package installation alone never provisions Python.
omp supplies its embedded Bun runtime; no separate Bun installation is needed.
See the [full install guide](https://github.com/alertxsto/luminary-memory/blob/main/docs/install.md)
for selected-agent options and the unreleased/public-artifact boundary.

## Advanced: manual published 0.3.4 installation

Manage the Python bridge yourself, then register the matching native package:

```sh
python -m pip install "luminary-memory==0.3.4"
export LUMINARY_PYTHON=/absolute/path/to/venv/bin/python
omp plugin install luminary-memory-omp@0.3.4
```

No npm install script installs Python. The explicit copied adapter,
`luminary-memory hook install omp` (project) or with `--global` (user), is an
advanced alternative, never the managed installer's silent fallback.

## Install from this checkout now

The Python bridge and npm extension are separate packages. To build and install
both from a source checkout, use Python 3.11 or newer:

```sh
# Run in the luminary-memory repository, with the intended Python environment active.
python -m pip install -e .
npm ci --ignore-scripts
npm run build:plugins
export LUMINARY_PYTHON=/absolute/path/to/venv/bin/python
omp plugin link /absolute/path/to/luminary-memory/plugins/omp
```

On PowerShell, set the interpreter before starting omp:

```powershell
$env:LUMINARY_PYTHON = 'C:\absolute\path\to\venv\Scripts\python.exe'
```

The interpreter must be executable and import `luminary_memory.integrations`.
Current source uses the same discovery for memory and inspector:
**explicit `LUMINARY_PYTHON` > schema-1 `~/.luminary/bridge.json` omp record
> embedded interpreter > PATH**. An invalid explicit interpreter fails visibly
without fallback. Native package installation embeds no machine-specific Python
path, and discovery/ordinary turns never install Python or dependencies.
Managed tooling lives under `~/.luminary/bin`, versioned bridges under
`~/.luminary/venvs/<version>`, and the existing model cache under
`~/.luminary/models` via `~/.luminary/luminary.env`.

**Do not also load the copied adapter.** Source setup cuts over installer-owned
copies without duplicate registration; modified/unrecognized copies produce a
conflict and are preserved. Manual switching must remove only Luminary's old
owned copy and its explicit settings entry, keeping unrelated extensions.

Restart omp after linking. `omp plugin list` shows configured plugins. The native
link command registers the local package in the user's plugin store (a junction
on Windows); it is not a project-scoped install. The manifest declares
`omp.extensions: ["./dist/index.js"]`, relative to the package root, and the
entry exports one ESM default extension factory. The adapter uses injected
`pi.zod`; host imports are type-only and erased during build. No full omp host
package or separate Zod copy is installed as a runtime dependency.

For a portable local artifact, run `npm run pack:plugins`, extract
`artifacts/plugins/luminary-memory-omp-<version>.tgz`, then use
`omp plugin link /absolute/path/to/extracted/package`. Keep that directory: the
link loads it in place. The extracted package needs no repository TypeScript
files, but still needs the separately installed Python bridge.

### Project scope limitation

**Native omp project installation is unsupported.** Installed 18.20 CLI help
shows `--scope`, but the
[upstream plugin-manager contract](https://github.com/can1357/oh-my-pi/blob/main/docs/plugin-manager-installer-plumbing.md)
says npm/git/link CLI operations remain user-scoped and warn then ignore that
flag. Source setup refuses native omp `--project` before changes rather than
silently performing a global install. The explicit copied adapter
`luminary-memory hook install omp` remains the project-local alternative.

## Use and accuracy

```text
/luminary
/luminary remember Deploy target is staging
/luminary recall deploy target
/luminary activity
/luminary forget 12
```

Use an actual returned memory ID for `forget`. The bare command opens native UI
dialogs when available; headless callers must supply the action. The model tool
is `luminary_memory`. Commands emit structured `luminary_activity` messages
without starting a model turn; UI status/dialogs require omp's native UI.

Recall runs before normal user turns and treats retrieved content as untrusted
historical data, not instructions. Strict, evidence-required retrieval can
abstain. Explicit `remember` reports `stored: 1` only for a committed new row;
`duplicate` has `stored: 0`. `skipped` and `error` are not successful writes.
`forget` retracts only a scope-visible ID and retains audit history. Activity is
a scoped snapshot, not a count of writes by the current turn.

Model remember requires `evidence_quote` copied exactly from current native user
input (at most 4096 UTF-8 bytes). The adapter verifies it; model text/metadata
cannot certify their own evidence or confidence. Unverified writes return
`user_evidence_required`; grounded paraphrases retain the original quote with
unassessed confidence. Owner-typed `/luminary remember TEXT` remains an explicit
assertion. Core/rule promotion requires the owner-confirmed inspector.
Automatic recall is request-local, non-system historical data, not a transcript
entry. Empty recall adds no message. Core-tagged rows must pass normal retrieval;
they cannot turn abstention into success.

The default database is `~/.luminary/memory.db`; set `LUMINARY_DB_PATH` in omp's
environment to change it. Ownership binds `LUMINARY_USER_ID` (otherwise the OS
login), resolved workspace path, and agent `omp`. Native session IDs are recorded
on writes; durable recall spans sessions only inside that ownership scope.
Other users, workspaces, harnesses, and legacy/global rows are not implicitly
shared, even in the same database.

Automatic durable retention is off by default. Enabling `LUMINARY_INGEST_LLM=true`
also requires `LUMINARY_LLM_BASE_URL` and appropriate `LUMINARY_LLM_MODEL` /
`LUMINARY_LLM_API_KEY` settings. This sends bounded turn text to your configured
curation endpoint; only curated, user-evidenced claims are eligible. Failed or
malformed curation never falls back to saving raw transcripts. Explicit remember
needs no LLM. A subprocess timeout/cancellation can leave a committed write with
an unknown client-side outcome; inspect activity before retrying.

## Update and remove

For managed source setup, repeat installation repairs/reuses the selected
release; explicit `--upgrade --version X` through the **new installer** migrates
0.3.4 to an available target and updates native pins, not just bridge.json.
`--check`, `--dry-run`, and `setup --list` never provision or modify stores/config.
Selected-agent `--uninstall --agents omp` preserves other hosts and memories;
`--prune` separately removes unreferenced managed environments.
Offline operation requires a healthy cached runtime and the configured embedding
model in cache; an uncached model can still need network access.

For a local link, rebuild in place and restart omp; npm/git upgrade does not
upgrade local links. Manual native removal uses
`omp plugin uninstall luminary-memory-omp`. For a manual registry upgrade,
select an available release with `omp plugin install luminary-memory-omp@X`
and update the Python bridge to match. Plugin removal does not delete memories.

See the [Luminary integration guide](https://github.com/alertxsto/luminary-memory/blob/main/docs/agent-integrations.md),
[omp v18.12.6 plugin manager contract](https://github.com/can1357/oh-my-pi/blob/v18.12.6/docs/plugin-manager-installer-plumbing.md),
and [omp v18.12.6 extension loading contract](https://github.com/can1357/oh-my-pi/blob/v18.12.6/docs/extension-loading.md).
