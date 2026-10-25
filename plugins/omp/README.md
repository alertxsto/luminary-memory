# Luminary memory for omp

Official **Luminary-maintained** oh-my-pi package. This does not mean endorsement
by omp's maintainers. The package builds the canonical Luminary omp adapter, not
a second memory engine. The native extension/plugin contract targets omp
v18.12.6. Source build tooling uses Node.js 22.22.2+ in the 22.x LTS line
(or the other versions accepted by the root manifest); omp uses its own
embedded Bun runtime to load extensions.

## Registry installation

Install the Python bridge from this verified public source commit, then install
the omp package. The older PyPI `0.3.1` release predates the native bridge, so use
this pinned source until a coordinated Python release contains it:

```sh
python -m pip install --upgrade "git+https://github.com/alertxsto/luminary-memory.git@9e35c5aa291414261835ac81d6bc9d197d42baf5"
export LUMINARY_PYTHON=/absolute/path/to/venv/bin/python
omp plugin install luminary-memory-omp
```

The Python source commit is immutable and publicly available independently of
whether its source PR has merged. No npm install script installs Python for you.

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

The interpreter must be executable and able to import `luminary_memory.integrations`.
The package runs `python -m luminary_memory.integrations bridge` in that interpreter;
without `LUMINARY_PYTHON` it uses `python` on the host process's `PATH`. There is
no embedded machine-specific Python path, bundled Python, automatic pip install,
or postinstall download. Set this environment in the process launching omp.

**Do not also load the file-copy adapter** installed by
`luminary-memory hook install omp`. Remove its `luminary.ts` from the project or
user extension directory, and remove any explicit settings entry for that copy,
before enabling this package. Keep unrelated extensions.

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

Only **after actual npm publication**, the registry installation is:

```sh
omp plugin install luminary-memory-omp
```

This uses a plain npm package name, not pi's `npm:` source syntax. Do not use the
command as evidence that the package currently exists on npm. omp's standalone
binary embeds Bun for plugin management; it does not require a separate Bun
installation for this npm command.

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

For a local link, rebuild it in the same directory and restart omp; the npm/git
upgrade command does not upgrade local links. Remove either a local link or a
registry install with `omp plugin uninstall luminary-memory-omp`. Only for an
actual npm installation, `omp plugin upgrade luminary-memory-omp` updates to the
latest published version; `omp plugin install luminary-memory-omp@VERSION`
selects a specific published version. Update the Python bridge separately to
the matching coordinated Luminary version.

See the [Luminary integration guide](https://github.com/alertxsto/luminary-memory/blob/main/docs/agent-integrations.md),
[omp v18.12.6 plugin manager contract](https://github.com/can1357/oh-my-pi/blob/v18.12.6/docs/plugin-manager-installer-plumbing.md),
and [omp v18.12.6 extension loading contract](https://github.com/can1357/oh-my-pi/blob/v18.12.6/docs/extension-loading.md).
