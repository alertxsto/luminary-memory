# Luminary Memory for OpenCode V2

The Luminary-maintained development package targets **`@opencode/cli` 2.2.0**
and **`@opencode/plugin` 2.2.0**. This is an official Luminary package,
**not** an OpenCode endorsement.

**Source/release boundary:** managed native setup is UNRELEASED; the next
release is not selected or staged; the proposed 0.3.5 bump is deferred.
Published 0.3.4 includes the inspector. The 0.3.2 adapter was verified on
OpenCode 2.1.4; 0.3.1 targets the separate V1 API. Native Web GUI
contribution discovery remains
blocked upstream. See the [target matrix](https://github.com/alertxsto/luminary-memory/blob/develop/docs/ROADMAP.md#target-support-matrix)
for exact scope, lifecycle and release limitations.

## Recommended installer (unreleased source)

**Registry current: 0.3.4.** The following source contract is not completed
platform acceptance, registry proof, or release readiness. Install OpenCode
first. Public entry points (`main` may differ from this unreleased checkout):

Windows (PowerShell):

```powershell
irm https://raw.githubusercontent.com/alertxsto/luminary-memory/main/install.ps1 | iex
```

Linux / macOS:

```sh
curl -fsSL https://raw.githubusercontent.com/alertxsto/luminary-memory/main/install.sh | sh
```

The **installer**, not native package installation, provisions a uv-managed
Python 3.12 bridge and registers a matching available native package in user
config by default. `--project` uses the project's OpenCode config instead.
No manual interpreter export is needed for managed setup.
See the [full install guide](https://github.com/alertxsto/luminary-memory/blob/main/docs/install.md)
for options and the unreleased/public-artifact boundary.

## Advanced: manual published 0.3.4 installation

Manage the Python bridge yourself:

```sh
python -m pip install "luminary-memory==0.3.4"
export LUMINARY_PYTHON=/absolute/path/to/venv/bin/python
```

Merge the matching package into existing user `opencode.json`/`opencode.jsonc`:

```json
{"plugins": ["luminary-memory-opencode@0.3.4"]}
```

V2 uses plural **`plugins`**, not V1's singular `plugin`. The host provides the
SDK and Effect runtime; the bundle keeps them external. Native packages have
no Python downloader or npm postinstall bootstrap. There is no
`npx luminary-memory-opencode setup` CLI.
For manual installation set `LUMINARY_PYTHON` in the **server's environment**,
including for clients connected to a remote server.
PowerShell: `$env:LUMINARY_PYTHON = 'C:\venv\Scripts\python.exe'`.

Current source memory tools and inspector share discovery:
**explicit `LUMINARY_PYTHON` > selected OpenCode schema-1 bridge.json record
> embedded interpreter > PATH**. A bad explicit override fails visibly without
fallback. `~/.luminary/bridge.json` records per-agent `python`, `version`, `mode`;
tooling lives under `~/.luminary/bin`, bridges under
`~/.luminary/venvs/<version>`, and model cache settings in
`~/.luminary/luminary.env` (default `~/.luminary/models`). Discovery and ordinary
turns never install runtimes or packages.

## Build or install a local artifact

```sh
python -m pip install -e .
npm ci --ignore-scripts
npm run pack:plugins
```

Keep the built directory or extract
`artifacts/plugins/luminary-memory-opencode-<version>.tgz`. Configure the **`dist`
directory**, which contains `index.js`, not the package root or a single file:

```json
{"plugins": ["/absolute/repo/plugins/opencode/dist"]}
```

For an extracted tarball, use `/absolute/extracted/package/dist`. V2 skips
configured single-file paths. Published npm packages instead resolve their
`./dist/index.js` export normally. Neither form needs this repository's source
files at runtime.

Explicit advanced copied-adapter alternative (not the managed default):

```sh
python -m luminary_memory.integrations install opencode --global
```

Run `npm install --ignore-scripts` in the config directory printed by that
command, then restart OpenCode. The installer writes dependency declarations;
it deliberately does not run npm for you.

In an existing native session, `/luminary`, the command palette or
`Ctrl+Alt+M` opens the inspector. `f` switches compact/full presentation;
Tab/Shift+Tab selects inspector tabs, and Enter opens actions. Native review
dialogs scroll with arrows/PageUp/PageDown/Home/End; Cancel is selected by
default. This checkpoint has real browse and confirmed tag-write evidence on
CLI 2.2.0, not a claim that every native workflow is accepted.

## Configuration

The Python bridge loads `~/.luminary/luminary.env` (env-style `LUMINARY_*`
settings) before each operation. Process environment wins; set
`LUMINARY_CONFIG_FILE` to another path or to `none` to disable file loading.
Edits apply to the next tool call because every operation starts a fresh bridge
process. See the
[configuration reference](https://github.com/alertxsto/luminary-memory/blob/main/docs/config-reference.md#config-file-for-native-integrations-and-cli).

## Tools and hooks

The model can use `luminary_recall`, `luminary_remember`, `luminary_forget`, and
`luminary_activity`. Native results/progress report the bridge's actual
`stored`, `duplicate`, `skipped`, `error`, and deletion outcomes.

Remember requires `evidence_quote`, an exact excerpt of the current native user
input (at most 4096 UTF-8 bytes), verified by the adapter. A paraphrase cannot
serve as its own evidence; unverified writes return `user_evidence_required`.
Grounded model paraphrases keep the original quote with unassessed confidence,
not an invented certainty of 1. Core/rule promotion requires the owner-confirmed
inspector, not a tool-supplied boolean.

The V2 context hook recalls relevant historical data for the admitted native user
message. Core tags do not bypass retrieval or turn abstention into success.
Whole JSON records enter request-local, non-system messages before the live
user input; empty recall adds nothing. Successful native execution triggers
optional, user-grounded curation;
failed/interrupted execution does not promote a transcript. Automatic writes
require explicit `LUMINARY_INGEST_LLM` and `LUMINARY_LLM_*` configuration.
Without it, no raw transcript is automatically saved.

Workspace ownership comes from the current native session, never a shared
plugin startup directory. The store defaults to `~/.luminary/memory.db`;
`LUMINARY_DB_PATH` overrides it. Reads/writes enforce user + normalized workspace
+ harness. Session IDs track write lineage, not permission to read another
workspace. Forget retracts the selected ID and keeps audit history. Recalled
content is untrusted reference data, not instructions.

## Agent skill

The repository ships a portable OpenCode skill at
[`opencode/SKILL.md`](https://github.com/alertxsto/luminary-memory/blob/main/opencode/SKILL.md).
It covers when to call each tool, safe durable-fact boundaries, result
semantics, the config file, and bridge troubleshooting.

From the repository root, install it globally:

```sh
mkdir -p ~/.config/opencode/skills/luminary-memory
cp opencode/SKILL.md ~/.config/opencode/skills/luminary-memory/SKILL.md
```

Or keep it project-local at `.opencode/skills/luminary-memory/SKILL.md`.
OpenCode discovers both locations automatically; no `opencode.json` entry is
required. The skill is documentation only and does not change plugin behavior.

Compatible clients consume the server's native tools/results. This package does
not add a universal client toolbar or a standalone desktop app.
Choose native or copied installation, never both. Source setup cuts over owned
copies; modified/unrecognized copies cause a conflict and are preserved, not
silently deleted. Native install failures never fall back to copying.

Repeat managed setup repairs/reuses the selected release; migrating from
0.3.4 uses the **new installer** with explicit `--upgrade --version X` for an
available target, updating native registration as well as bridge.json.
`--check`, `--dry-run`, and `setup --list` never provision or change config/stores.
Selected-agent `--uninstall --agents opencode` preserves other hosts and memories;
separate `--prune` removes unreferenced managed environments.
For manual native removal, remove only Luminary's entry from `plugins`.
Restart the server. Stored memory is not deleted.

Offline use requires a healthy cached runtime and configured embedding model;
an uncached model may still require network access. Hermes remains a separate
provider/catalog integration, not this managed bridge environment.

## Compatibility evidence

Real OpenCode V2 2.1.4 native sessions, the Python bridge, and SQLite verified:
remember, same-session duplicate suppression, scoped recall/activity, cross-
workspace isolation, ID-scoped forget, and empty recall after retraction.
That older adapter placed evidence in system context; the current implementation
uses request-local non-system references instead. The earlier native completion
stored a user-grounded curated fact and rejected an assistant-only claim
with `no_grounded_fact`. Removing the plugin stopped its tools from appearing.

Model and curation responses came from deterministic localhost fixtures; memory
operations were real. This proves API/storage compatibility, not model quality,
visual desktop/web behavior, or compatibility with every future V2 release.

## Website listing is separate

The [Ecosystem PR #58823](https://github.com/anomalyco/opencode/pull/58823)
targets OpenCode's **V1 documentation** and pins npm `0.3.1`, the V1 adapter.
Its latest bot review reports no further concerns and it is ready for maintainer
review. This is not a verified V2 catalog or a live website listing.
The obsolete local listing patch is no longer shipped.

[Source PR #17](https://github.com/alertxsto/luminary-memory/pull/17) has merged.
Python and all three native npm packages are published at `0.3.4`.

[Configuration and ownership](https://github.com/alertxsto/luminary-memory/blob/main/docs/agent-integrations.md)
· [OpenCode V2 plugin contract](https://opencode.ai/v2/docs/plugins/)
