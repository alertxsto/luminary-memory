# Luminary memory for pi

Official **Luminary-maintained** pi package. This does not mean endorsement by
pi's maintainers. The package builds the canonical Luminary pi adapter, not a
second memory engine. Its native extension contract targets
`@earendil-works/pi-coding-agent` 1.4.0; the host requires Node.js 22.19 or newer.
Building this repository uses Node.js 22.22.2+ in the 22.x LTS line (or the other
versions accepted by the root manifest).

## Install

**Registry current: 0.3.4. Self-provisioning install: UNRELEASED source.** The
published 0.3.4 package ships only the adapter, so it still needs the manual
Python step below. From source, installation is one command:

```sh
pi install npm:luminary-memory-pi@<available-release>
```

The package provisions the matching Python bridge itself: it reuses an explicit
`LUMINARY_PYTHON`, an existing `~/.luminary/bridge.json` record, or creates a
version-pinned venv under `~/.luminary/venvs/<version>`. It uses `uv` when one is
available (set `LUMINARY_UV` to point at it), a local Python 3.11+ otherwise, and
on a host with neither it downloads a standalone `uv` into `~/.luminary/bin` and
lets that install its own CPython. Progress and failures print on stderr; a
failed provision never removes the installed package.

npm 12 blocks dependency install scripts by default and a package cannot approve
itself, so the `postinstall` hook is only a fast path on older npm. The primary
path is the first pi session: the extension runs the same provisioning script
once, reports progress in the status line, and warns when no interpreter can
provide the engine. Set `LUMINARY_SKIP_BOOTSTRAP=1` to opt out of that runtime
path, or `LUMINARY_NO_DOWNLOAD=1` to forbid fetching `uv`. An invalid explicit
`LUMINARY_PYTHON` is reported rather than silently replaced.

Expect the first session on a bare host to take a few minutes: it fetches `uv`,
a CPython, and roughly 250 MB of wheels. Later sessions reuse the venv and start
immediately.

## Advanced: manual published 0.3.4 installation

Manage the Python bridge yourself, then register the matching native package:

```sh
python -m pip install "luminary-memory==0.3.4"
export LUMINARY_PYTHON=/absolute/path/to/venv/bin/python
pi install npm:luminary-memory-pi@0.3.4
```

No npm install script installs Python. The explicit copied adapter,
`luminary-memory hook install pi` (project) or with `--global` (user), is an
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
pi install /absolute/path/to/luminary-memory/plugins/pi
```

On PowerShell, set the interpreter before starting pi:

```powershell
$env:LUMINARY_PYTHON = 'C:\absolute\path\to\venv\Scripts\python.exe'
```

The interpreter must be executable and import `luminary_memory.integrations`.
Current source uses the same discovery for memory and inspector:
**explicit `LUMINARY_PYTHON` > schema-1 `~/.luminary/bridge.json` pi record
> embedded interpreter > PATH**. An invalid explicit interpreter fails visibly
without fallback. Native package installation embeds no machine-specific Python
path. Discovery never installs anything; the first session provisions the bridge
once, and ordinary turns reuse it.
Managed tooling lives under `~/.luminary/bin`, versioned bridges under
`~/.luminary/venvs/<version>`, and the existing model cache under
`~/.luminary/models` via `~/.luminary/luminary.env`.

**Do not also load the copied adapter.** Source setup cuts over installer-owned
copies without duplicate registration; modified/unrecognized copies produce a
conflict and are preserved. Manual switching must remove only Luminary's old
owned copy and its explicit settings entry, keeping unrelated extensions.

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

The current registry release is 0.3.4; next-release source instructions are not
proof of publication or catalog indexing.

### Official package catalog

The [pi.dev package catalog](https://pi.dev/packages) discovers npm packages
with the `pi-package` keyword, which this manifest includes. Build preflight
rejects a release if that discovery keyword is removed. Publication and catalog
indexing are separate. Use the
[filtered catalog](https://pi.dev/packages?name=luminary), rather than assuming
there is a package-detail route. A registry install does not prove indexing.

## Use and accuracy

```text
/luminary
/luminary remember Deploy target is staging
/luminary recall deploy target
/luminary activity
/luminary forget 12
```

Use an actual returned memory ID for `forget`. The bare command opens the
inspector: a Zentui-style framed surface with numbered sections, an accent rail
on the selected row, a compact key-help line, and live status. It renders only
that overlay; it never replaces pi's editor, transcript, or footer. `compact`
keeps the inline activity widget, and `close` dismisses the panel. Headless and
RPC sessions receive structured state instead of drawing. The model tool is
`luminary_memory`. Commands emit structured `luminary_activity` messages
without starting a model turn; UI status/dialogs require pi's native UI.

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

For managed source setup, repeat installation repairs/reuses the selected
release; explicit `--upgrade --version X` through the **new installer** migrates
0.3.4 to an available target and updates native pins, not just bridge.json.
`--check`, `--dry-run`, and `setup --list` never provision or modify stores/config.
Selected-agent `--uninstall --agents pi` preserves other hosts and memories;
`--prune` separately removes unreferenced managed environments.
Offline operation requires a healthy cached runtime and the configured embedding
model in cache; an uncached model can still need network access.

For a local package, rebuild in place and restart pi. Remove it with
`pi remove /absolute/path/to/luminary-memory/plugins/pi`, adding `--local` if
installed locally. For manual registry removal use
`pi remove npm:luminary-memory-pi`. Pinned versions require explicit replacement;
keep the Python bridge matched when upgrading manually. Bare `pi update`
updates pi itself, not just extensions. None of these plugin removals deletes
the memory store.

See the [Luminary integration guide](https://github.com/alertxsto/luminary-memory/blob/main/docs/agent-integrations.md),
[pi package contract](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/packages.md),
and [pi package commands](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/cli.md#package-commands).
