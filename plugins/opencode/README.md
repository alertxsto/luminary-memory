# Luminary Memory for OpenCode V2

The Luminary-maintained server plugin for **`@opencode/cli` 2.1.4** and
**`@opencode/plugin` 2.1.4**. This is an official Luminary package, **not** an
OpenCode endorsement. Luminary `0.3.2` targets V2; the older npm `0.3.1`
package targets the separate V1 API and must not be used for this setup.

## Install

Install the Python bridge from this verified, immutable public source commit.
The older PyPI `0.3.1` release predates the native bridge:

```sh
python -m pip install --upgrade "git+https://github.com/alertxsto/luminary-memory.git@9e35c5aa291414261835ac81d6bc9d197d42baf5"
export LUMINARY_PYTHON=/absolute/path/to/venv/bin/python
```

Install the V2 npm package through OpenCode:

```sh
opencode plugin add luminary-memory-opencode@0.3.2
```

Alternatively, add it to your existing `opencode.json` or `opencode.jsonc`:

```json
{"plugins": ["luminary-memory-opencode@0.3.2"]}
```

V2 uses **`plugins`**, not V1's singular `plugin`. The host provides the SDK and
Effect runtime; the bundle keeps them external. No npm install hook installs
Python, downloads memory models, or changes your Python environment. Set
`LUMINARY_PYTHON` in the **OpenCode server's environment**, including when a
terminal, desktop, or web client connects to a separate server.

PowerShell:

```powershell
$env:LUMINARY_PYTHON = 'C:\venv\Scripts\python.exe'
```

Otherwise the bridge runs `python` from PATH. A missing interpreter or bridge
produces an explicit error, not a successful storage claim. The public Python
source can be installed before source PR #17 merges.

## Build or install a local artifact

```sh
python -m pip install -e .
npm ci --ignore-scripts
npm run pack:plugins
```

Keep the built directory or extract
`artifacts/plugins/luminary-memory-opencode-0.3.2.tgz`. Configure the **`dist`
directory**, which contains `index.js`, not the package root or a single file:

```json
{"plugins": ["/absolute/repo/plugins/opencode/dist"]}
```

For an extracted tarball, use `/absolute/extracted/package/dist`. V2 skips
configured single-file paths. Published npm packages instead resolve their
`./dist/index.js` export normally. Neither form needs this repository's source
files at runtime.

## Tools and hooks

The model can use `luminary_recall`, `luminary_remember`, `luminary_forget`, and
`luminary_activity`. Native results/progress report the bridge's actual
`stored`, `duplicate`, `skipped`, `error`, and deletion outcomes.

The V2 context hook recalls historical data for the admitted native user
message. Successful native execution triggers optional, user-grounded curation;
failed/interrupted execution does not promote a transcript. Automatic writes
require explicit `LUMINARY_INGEST_LLM` and `LUMINARY_LLM_*` configuration.
Without it, no raw transcript is automatically saved.

Workspace ownership comes from the current native session, never a shared
plugin startup directory. The store defaults to `~/.luminary/memory.db`;
`LUMINARY_DB_PATH` overrides it. Reads/writes enforce user + normalized workspace
+ harness. Session IDs track write lineage, not permission to read another
workspace. Forget retracts the selected ID and keeps audit history. Recalled
content is untrusted reference data, not instructions.

Compatible clients consume the server's native tools/results. This package does
not add a universal client toolbar or a standalone desktop app. Before enabling
it, remove only the old copied Luminary adapter and its explicit config entry;
do not run both installation forms. To remove the package, use
`opencode plugin remove luminary-memory-opencode@0.3.2` or remove its config
entry. Reload/restart the server as needed. Stored memory is not deleted.

## Compatibility evidence

Real OpenCode V2 2.1.4 native sessions, the Python bridge, and SQLite verified:
remember, same-session duplicate suppression, scoped recall/activity, cross-
workspace isolation, ID-scoped forget, and empty recall after retraction.
Automatic recall evidence reached the model's system context. Native completion
also stored a user-grounded curated fact and rejected an assistant-only claim
with `no_grounded_fact`. Removing the plugin stopped its tools from appearing.

Model and curation responses came from deterministic localhost fixtures; memory
operations were real. This proves API/storage compatibility, not model quality,
visual desktop/web behavior, or compatibility with every future V2 release.

## Website listing is separate

The existing [Ecosystem PR #58823](https://github.com/anomalyco/opencode/pull/58823)
targets OpenCode's **legacy V1 documentation**, not a verified V2 catalog. It
remains draft; npm publication does not establish V2 website visibility. The
obsolete V1 listing patch is no longer shipped. A V2 submission needs the
maintainers' supported destination, acceptance, and deployment.

[Source PR #17](https://github.com/alertxsto/luminary-memory/pull/17) still requires
review approval; this migration does not merge or bypass protected `main`.

[Configuration and ownership](https://github.com/alertxsto/luminary-memory/blob/feat/luminary-native-packages-20261025/docs/agent-integrations.md)
· [OpenCode V2 plugin contract](https://opencode.ai/v2/docs/plugins/)
