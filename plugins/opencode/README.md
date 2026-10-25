# Luminary Memory for OpenCode

The Luminary-maintained memory plugin for OpenCode's server plugin API.
This is an official package of the Luminary project, **not** an OpenCode
endorsement.

## Verified latest-stable compatibility

Checked on 2026-10-25: GitHub's
[latest stable OpenCode release](https://github.com/anomalyco/opencode/releases/tag/v1.19.4)
and npm's `latest` tags for `opencode-ai` and `@opencode-ai/plugin` all resolve
to **1.19.4**. The plugin's pinned SDK is already that version; describing the
API as "1.x" does not mean that it targets an older stable OpenCode release.

The published `luminary-memory-opencode@0.3.1` was exercised in a real 1.19.4
server with native session/message requests, the Python bridge and SQLite.
Verified: explicit remember, duplicate suppression, scoped recall, read-only
activity, forget, empty recall after retraction, accurate tool metadata, and
automatic recall evidence reaching the model's system context.

Model responses were supplied by a deterministic localhost fixture; memory
operations were real. This is API/storage compatibility evidence, not a model
quality benchmark or a desktop/web client visual test. The separate npm
`beta`, `dev`, `next`, and snapshot channels are not covered by this claim.

## Registry installation

Install the Python bridge from this verified public source commit. The older
PyPI `0.3.1` release predates the native bridge:

```sh
python -m pip install --upgrade "git+https://github.com/alertxsto/luminary-memory.git@9040d9b5154f94c66594ed6096e33aa2fd311bf0"
export LUMINARY_PYTHON=/absolute/path/to/venv/bin/python
```

Then enable the npm package in `opencode.json`:

```json
{"plugin": ["luminary-memory-opencode"]}
```

The pinned Python source is public even before its source PR merges. Use it
until a coordinated Python release contains the bridge. No npm install script
installs Python for you; set the interpreter in the OpenCode server environment.

## Install from this checkout

The Python bridge and npm plugin are separate packages. Until a coordinated
release containing the bridge is published, install the Python source:

```sh
python -m pip install -e .
npm ci --ignore-scripts
npm run build:plugins
npm run pack:plugins
```

Extract `artifacts/plugins/luminary-memory-opencode-<version>.tgz` to a stable
local directory, preserving its `package/` directory. Add that directory's
compiled entry as a file plugin in `opencode.json`; keep your other config:

```json
{
  "plugin": ["file:///absolute/extracted/package/dist/index.js"]
}
```

The packed plugin requires `@opencode-ai/plugin` 1.19.4. Install its declared npm
dependency in that extracted package (`npm install --omit=dev --ignore-scripts`),
or install the tarball into a local npm project and point the file entry at
`node_modules/luminary-memory-opencode/dist/index.js`. This needs no repo source
files at runtime.

After **this package is published to npm**, the normal configuration is:

```json
{
  "plugin": ["luminary-memory-opencode"]
}
```

OpenCode installs the npm package and its SDK dependency at startup. Pin a
published version with `luminary-memory-opencode@<version>` when desired. A
source checkout/tarball existing does not mean the npm name is already live.

Set the interpreter used by the **OpenCode server**, then restart it:

```sh
export LUMINARY_PYTHON=/absolute/venv/bin/python
```

PowerShell:

```powershell
$env:LUMINARY_PYTHON = 'C:\venv\Scripts\python.exe'
```

Otherwise the plugin runs `python` from PATH. No install script silently installs
Python packages or downloads a memory model. A missing bridge produces an
explicit error rather than a successful storage claim.

## Use

Ask the agent to use `luminary_recall`, `luminary_remember`, `luminary_forget`, or
`luminary_activity`. Results report actual `stored`/`duplicate`/`skipped`/`error`
outcomes and native metadata. Hooks automatically recall scoped historical data;
automatic curation requires explicit `LUMINARY_INGEST_LLM` and `LUMINARY_LLM_*`
configuration. Without it, no raw transcript is automatically saved.

The store defaults to `~/.luminary/memory.db`; `LUMINARY_DB_PATH` overrides it.
Ownership is user + normalized workspace + harness; current session IDs are write
lineage, not permission to read other users/workspaces. `forget` retracts only the
selected ID and retains audit history. Recalled content is untrusted reference
data, not instructions.

Plugins execute on the server. Compatible terminal/desktop/web clients consume
native tools/results; this package does not add a standalone desktop app or a
universal client toolbar. Remove the old copied `luminary-memory.ts` adapter from
`.opencode/plugins/` or the global plugin directory before enabling this package:
two installation forms can otherwise run both hook sets.

To remove it, remove its entry from `opencode.json` and restart OpenCode. Upgrade
by selecting a published version in that config. Existing memory is not deleted.

[Full configuration and ownership guide](https://github.com/alertxsto/luminary-memory/blob/main/docs/agent-integrations.md)
· [OpenCode plugin contract](https://opencode.ai/docs/plugins/)

## Official Ecosystem listing

OpenCode's [official Ecosystem list](https://opencode.ai/docs/ecosystem/) is
maintained in `anomalyco/opencode`, branch `dev`,
`packages/web/src/content/docs/ecosystem.mdx`. Upstream explicitly requests a PR
for additions; npm keywords do not automatically create that listing.

After publishing the installable package and public documentation, apply
`plugins/opencode/ecosystem.patch` from this repository to an upstream checkout
and submit `docs(ecosystem): add Luminary memory`. The patch adds one accurate
1.x plugin entry and does not claim v2 compatibility. A prepared patch does not
itself submit or obtain acceptance of an upstream PR. Track the actual PR URL
and verify the site after maintainers merge/deploy it; a patch or open PR is not
a live website listing.

Initial submission (2026-10-25):
[OpenCode Ecosystem PR #58823](https://github.com/anomalyco/opencode/pull/58823)
is submitted, with [source PR #17](https://github.com/alertxsto/luminary-memory/pull/17)
as its source-distribution dependency. Both were open, not merged, at submission
verification; follow those links for current status.
