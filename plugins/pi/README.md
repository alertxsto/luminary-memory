# Luminary memory for pi

Official **Luminary-maintained** pi package. This does not mean endorsement by
pi's maintainers. The package builds the canonical Luminary pi adapter, not a
second memory engine. Its native extension contract targets
`@earendil-works/pi-coding-agent` 1.4.0; the host requires Node.js 22.19 or newer.
Building this repository uses Node.js 22.22.2+ in the 22.x LTS line (or the other
versions accepted by the root manifest).

## Install from this checkout now

These package names are not published to npm as part of this change. Before the
coordinated Python/npm release, install the Python bridge from the same source
checkout, using Python 3.11 or newer:

```sh
# Run in the luminary-memory repository, with the intended Python environment active.
python -m pip install -e .
npm ci --ignore-scripts
npm run build:plugins
export LUMINARY_PYTHON=/absolute/path/to/venv/bin/python
pi install /absolute/path/to/luminary-memory/plugins/pi
```

On PowerShell, set the interpreter before starting pi:

```powershell
$env:LUMINARY_PYTHON = 'C:\absolute\path\to\venv\Scripts\python.exe'
```

The interpreter must be executable and able to import `luminary_memory.integrations`.
The package runs `python -m luminary_memory.integrations bridge` in that interpreter;
without `LUMINARY_PYTHON` it uses `python` on the host process's `PATH`. There is
no embedded machine-specific Python path, bundled Python, automatic pip install,
or postinstall download. Set this environment in the process launching pi.

**Do not also load the file-copy adapter** installed by
`luminary-memory hook install pi`. Remove its `luminary.ts` from the project or
user extension directory, and remove any explicit settings entry for that copy,
before enabling this package. Keep unrelated extensions.

Restart pi after installation. `pi list` shows the configured package. For a
project-scoped install add `--local`; pi requires project trust before loading it.
The package manifest declares `pi.extensions: ["./dist/index.js"]`, relative to
the package root. `dist/index.js` has one ESM default extension factory. Host
packages `typebox` and `@earendil-works/pi-coding-agent` are optional `"*"` peers,
not bundled or installed runtime dependencies; pi supplies them when loading.

For a portable local artifact, run `npm run pack:plugins`, extract
`artifacts/plugins/luminary-memory-pi-<version>.tgz`, then use
`pi install /absolute/path/to/extracted/package`. Keep that directory: local
packages load in place. The extracted package needs no repository TypeScript
files, but still needs the separately installed Python bridge.

Only **after actual npm publication**, the registry installation is:

```sh
pi install npm:luminary-memory-pi
```

Do not use that command as evidence that the package currently exists on npm.

### Official package catalog

The [pi.dev package catalog](https://pi.dev/packages) discovers npm packages
with the `pi-package` keyword, which this manifest includes. Build preflight
rejects a release if that discovery keyword is removed. A public npm release
must exist and be indexed before `pi.dev/packages/luminary-memory-pi` can be
verified live. The current local package is not a claim that the catalog page
already exists.

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
without starting a model turn; UI status/dialogs require pi's native UI.

Recall runs before normal user turns and treats retrieved content as untrusted
historical data, not instructions. Strict, evidence-required retrieval can
abstain. Explicit `remember` reports `stored: 1` only for a committed new row;
`duplicate` has `stored: 0`. `skipped` and `error` are not successful writes.
`forget` retracts only a scope-visible ID and retains audit history. Activity is
a scoped snapshot, not a count of writes by the current turn.

The default database is `~/.luminary/memory.db`; set `LUMINARY_DB_PATH` in pi's
environment to change it. Ownership binds `LUMINARY_USER_ID` (otherwise the OS
login), resolved workspace path, and agent `pi`. Native session IDs are recorded
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

For a local package, rebuild it in the same directory and restart pi. Remove it
with `pi remove /absolute/path/to/luminary-memory/plugins/pi`, using the installed
source (or the extracted directory's path), plus `--local` if installed locally.
For a published registry install, use `pi update --extensions` to update packages
and `pi remove npm:luminary-memory-pi` to remove this one. Pinned versions stay
pinned; install a different version explicitly to change the pin. Bare
`pi update` updates pi itself, not just extensions. Update the Python bridge
separately to the matching coordinated Luminary version.

See the [Luminary integration guide](https://github.com/alertxsto/luminary-memory/blob/main/docs/agent-integrations.md),
[pi package contract](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/packages.md),
and [pi package commands](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/cli.md#package-commands).
