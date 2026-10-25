# Native agent hooks and interaction

Luminary's JSON bridge is **harness-neutral**. Native adapters are shipped only
for verified host extension contracts; a shared protocol is not a claim that
arbitrary desktop or web clients load plugins. The existing Hermes provider
continues to use its public `MemoryProvider` lifecycle.

| Adapter | Contract | Interaction surface |
| --- | --- | --- |
| Hermes | Public `MemoryProvider`, existing installer | Provider tools/status in supported Hermes clients; read-only scoped Telegram activity hook |
| OpenCode V2 | `@opencode/cli` and `@opencode/plugin` 2.1.4, `Plugin.define` server API | Native tools/progress/results in connected clients; automatic recall and curated retention |
| pi | Extension API verified against `@earendil-works/pi-coding-agent` 1.4.0 | `/luminary`, model tool, TUI dialogs/status, serializable session messages for RPC consumers |
| omp | Extension API verified against v18.12.6 | `/luminary`, model tool, TUI dialogs/status, serializable session messages for RPC consumers |

OpenCode V2 uses the plural `plugins` config, a default `Plugin.define` export,
and Promise domain APIs. The older Luminary npm `0.3.1` adapter targets V1;
`0.3.2` is the V2 migration, not a compatibility shim. pi/omp do not gain a new
standalone desktop app. Desktop/web wrappers must render native extensions,
custom messages or tool results; terminal widgets are not portable.

## Native plugin packages

Official **Luminary-maintained** package sources are available for pi, OpenCode,
and omp. That means ownership by this project, not endorsement or listing
approval by the harness maintainers. All three compile the canonical adapter
source under `src/luminary_memory/integrations/assets/`; no second memory engine
or separate adapter fork is maintained.
The initial npm packages were published as `0.3.1`; that OpenCode package is
V1-only. The `0.3.2` source migrates OpenCode to V2. The older Python/PyPI
`0.3.1` release predates this bridge, so install the verified public source into
the Python environment the host will use:

```bash
python -m pip install --upgrade "git+https://github.com/alertxsto/luminary-memory.git@9e35c5aa291414261835ac81d6bc9d197d42baf5"
export LUMINARY_PYTHON=/absolute/venv/bin/python
```

Then use the registry install command below. Installing an npm package does not
install Python or replace the configured Python environment.


To build and install from a local checkout instead:

```bash
python -m pip install -e .
npm ci --ignore-scripts
npm run build:plugins
npm run test:plugins
npm run pack:plugins
export LUMINARY_PYTHON=/absolute/venv/bin/python
```

PowerShell uses `$env:LUMINARY_PYTHON = 'C:\venv\Scripts\python.exe'`.
Build tooling/OpenCode require Node `^22.22.2 || ^24.15.0 || >=26.0.0`,
matching the pinned SDK's transitive engine requirements. The bridge is Python >=3.11.
The build/pack scripts emit `plugins/{agent}/dist/index.js` and
`artifacts/plugins/luminary-memory-{agent}-{version}.tgz`. Tarballs include
compiled ESM, package metadata, usage instructions, and the license, with no
host framework copy, repository source dependency, or machine-specific Python
path. No package install hook silently installs Python dependencies.

| Host | Local build installation | Published npm installation |
| --- | --- | --- |
| pi | `pi install /absolute/repo/plugins/pi` | `pi install npm:luminary-memory-pi` |
| omp | `omp plugin link /absolute/repo/plugins/omp` | `omp plugin install luminary-memory-omp` |
| OpenCode V2 | `{"plugins":["/absolute/repo/plugins/opencode/dist"]}`; configured local paths must be directories | `opencode plugin add luminary-memory-opencode@0.3.2`, or `{"plugins":["luminary-memory-opencode@0.3.2"]}` |

Local pi/omp packages load in place, so keep the installed directory. An
extracted tarball works independently of this repository. See the host READMEs
for exact local installation/removal details:
[pi](../plugins/pi/README.md), [OpenCode](../plugins/opencode/README.md),
[omp](../plugins/omp/README.md).

For extracted OpenCode artifacts use `/absolute/extracted/package/dist`. V2
skips configured single files; npm package exports resolve the compiled entry
normally. The SDK and Effect stay external and are supplied by the host.

**Do not load both installation forms.** Before switching to a native package,
remove only Luminary's old copied adapter and any explicit reference to it.
Do not remove unrelated host extensions/config. Python bridge settings, scope
and memory ownership remain unchanged.

### Discovery on official websites

- **pi:** its [official package catalog](https://pi.dev/packages) indexes npm
  packages eligible via the `pi-package` keyword. The package includes this
  keyword plus `pi.extensions`; build preflight refuses a release missing the
  discovery keyword. Publication is verified; catalog indexing is separate.
  Check the [filtered catalog](https://pi.dev/packages?name=luminary), not a
  guessed package-detail route. It returned no results when checked after the
  initial publication, so a live pi catalog listing is not yet claimed.
- **OpenCode V2:** the current plugin contract is the
  [V2 documentation](https://opencode.ai/v2/docs/plugins/), verified against
  `@opencode/cli` and `@opencode/plugin` **2.1.4**. V2 is a different namespace
  from V1's `opencode-ai`/`@opencode-ai/plugin`; querying the old npm names'
  `latest` tags is not evidence about V2. Use plural `plugins`.
- **OpenCode website:** existing Ecosystem PR #58823 targets the legacy file
  `packages/web/src/content/docs/ecosystem.mdx`, not a verified V2 listing.
  It remains draft. The V1 patch was removed rather than advertising V2 in the
  wrong directory. A supported V2 submission destination still needs upstream
  clarification; npm publication alone does not create a website listing.

Building packages does not itself publish to npm or submit/merge an upstream
PR. The release workflow builds validated tarballs, gates Python publication on
real-model recall, and attaches native artifacts to tag releases. npm publishing
is explicitly enabled by `PUBLISH_NPM_PLUGINS=true` after the three package names
and trusted publishers are configured; it never invents an authorization token.
The first publication requires maintainer npm authorization. Use
`scripts/bump-version.sh` to synchronize Python/plugin/lockfile versions before
the next coordinated release; do not overwrite an already-published Python tag.
See [contributor release instructions](../CONTRIBUTING.md).

Publication verified on 2026-10-25: all three npm `0.3.1` tarballs match the
validated local artifacts:
[pi](https://www.npmjs.com/package/luminary-memory-pi),
[OpenCode](https://www.npmjs.com/package/luminary-memory-opencode), and
[omp](https://www.npmjs.com/package/luminary-memory-omp).
Registry installation succeeded through the pi and omp CLIs. The initial
OpenCode package was exercised against V1 1.19.4; that historical verification
does not establish V2 compatibility.

The `0.3.2` V2 adapter was separately exercised in the real **2.1.4** server.
Native requests verified remember, same-session duplicate suppression, scoped
recall/activity, cross-workspace isolation, forget, empty recall after retraction,
and evidence injection into the model's system context. Native completion also
stored a user-grounded curated fact, rejected an assistant-only claim with
`no_grounded_fact`, and stopped exposing tools after plugin removal. Python and
SQLite were real; model/curation responses came from deterministic localhost
fixtures. This does not claim model-quality or client-UI coverage. Publication
of the new npm version must be verified separately from this local/runtime proof.

The [source PR #17](https://github.com/alertxsto/luminary-memory/pull/17) still
requires approval and has not been merged as part of this migration. The
[Ecosystem PR #58823](https://github.com/anomalyco/opencode/pull/58823) remains
draft: its legacy V1 destination is not a V2 catalog, regardless of source
review or npm status.


## File-copy hook installer

This remains an alternative to native package installation. Until a bridge
release is published, install the Python source with `python -m pip install -e .`
from this checkout, then copy only the adapter for the host you use:

```bash
python -m pip install -e .
luminary-memory hook install opencode
luminary-memory hook install pi
luminary-memory hook install omp
```

Run only the installer for the host(s) you use. The default is project-local:
`.opencode/plugins/luminary-memory.ts`, `.pi/extensions/luminary.ts`, or
`.omp/extensions/luminary.ts`. For user-wide discovery add `--global`.
`--directory PATH` means the **native config root**, not the workspace root:

```bash
luminary-memory hook install pi --directory /project/.pi
luminary-memory hook install opencode --global
```

The installer embeds its exact Python executable (including Windows paths).
`LUMINARY_PYTHON` overrides it at runtime. Reinstall after moving/deleting the
Python environment. Existing hook modifications/dependency conflicts fail
visibly; inspect them before opting into `--force`. Other config keys and
unrelated npm dependencies are preserved. The OpenCode adapter targets SDK
2.1.4 and the host provides its runtime. Restart/reload the host.

Hermes setup remains documented in [Hermes integration](hermes-integration.md);
its Telegram hook is [installed separately](../hermes/hooks/luminary-activity/README.md).

## Storage and ownership

The bridge defaults to `~/.luminary/memory.db`. Set `LUMINARY_DB_PATH` (or the
existing backend/pgvector environment settings) in the **agent/server process**
to choose another store. It does not silently use a Hermes profile database.

Every bridge operation binds all three ownership fields:

- `user_id`: `LUMINARY_USER_ID`, otherwise the operating-system login name.
- `workspace_id`: normalized, resolved native working-directory path.
- `agent_id`: the adapter's stable harness identifier.

Native session IDs are recorded on writes, but durable recall spans sessions
inside the same ownership scope. Global/legacy rows and other users, workspaces
or harnesses are not implicitly shared. A shared desktop/web server must bind
`LUMINARY_USER_ID` per trusted user process; this local subprocess protocol is
not a remotely authenticated multi-user API. Do not accept caller-selected
ownership fields directly from an untrusted web request.

## Use

pi and omp provide:

```text
/luminary
/luminary remember Deploy target is staging
/luminary recall deploy target
/luminary activity
/luminary forget 12
```

The bare command opens a menu when the native UI is available; headless callers
should supply the action. Commands publish native `luminary_activity` messages
with structured details without invoking the model. The model-facing tool is
`luminary_memory`, with `action`, `query`, `text`, `tags`, and `memory_id`.

OpenCode exposes `luminary_recall`, `luminary_remember`, `luminary_forget`, and
`luminary_activity`. Ask the agent to use them; results carry native metadata
and an explicit status. `luminary_activity` also reports this process's automatic
recall/retention status. No nonexistent cross-client toolbar or slash command is
installed. Plugins run on the server, not separately in each browser window.

`remember` is synchronous and explicit. `stored: 1` means a newly committed row;
`duplicate` has `stored: 0`. Exact duplicate observations within a session are
suppressed by the engine. `forget` retracts that ID inside its owning scope;
it does not delete unrelated IDs or erase audit history. Activity is a current
scoped snapshot, not a claimed count of writes in the current turn.

## Automatic recall and retention

Before a normal user run, adapters recall strictly relevant, evidence-bearing
memory plus current `core` rows. Historical context is bounded and explicitly
untrusted: it does not grant instruction authority. Aborted/error/tool-only
responses are not automatically retained. Compaction is not a memory write.

Automatic durable capture is disabled unless configured:

```bash
export LUMINARY_INGEST_LLM=true
export LUMINARY_LLM_BASE_URL=https://your-provider.example/v1
export LUMINARY_LLM_API_KEY=...
export LUMINARY_LLM_MODEL=your-curation-model
```

This explicitly sends the bounded user/assistant turn to the configured
curation endpoint. The bridge requires a curated summary and a structured claim
whose evidence quote occurs in the **user text**, not merely an assistant
assertion. Failure/malformed output never falls back to storing the raw
transcript. Curator-assigned `core`/`rule` tags are not automatically promoted.
Explicit remember remains available without an LLM. `skipped`, `error`,
`duplicate`, and `stored` remain distinct in results; no operation fabricates a
successful write. Subprocess timeout/cancellation can leave an already committed
write with an unknown client-side outcome; inspect activity before retrying.

## Add another supported harness

A host with trusted lifecycle/custom-tool hooks can call the same bridge. Native
installation remains limited to the adapters listed above; other hosts need a
real adapter mapping their own lifecycle and session identifiers.

Run `python -m luminary_memory.integrations bridge` (or
`luminary-memory hook bridge`) with **one UTF-8 JSON object on stdin**, then
close stdin. Never interpolate user text into a shell command:

```json
{"agent":"another-supported-host","workspace":"/absolute/project","session_id":"native-session-42","action":"recall","query":"deploy target"}
```

The stable harness identifier accepts `[a-z][a-z0-9._-]{0,63}`; it is an ownership
key, not a dynamically loaded plugin name. Actions: `recall` (`query`), `remember`
(`text`, optional `tags`), `forget` (`memory_id`), `activity`, and `turn` (`user`,
`assistant`, optional lineage `tags`). Every action requires absolute workspace,
agent ID, and native session ID. Maximum request: 128 KiB; each text field:
32,768 characters. A response is a UTF-8 JSON object containing `ok`, `status`,
`reason`, `message`, `context`, `memories`, `stored`, and `deleted`; errors exit
nonzero. Keep stdout reserved for that response and treat recalled data as
untrusted. Native adapters bound process lifetime/output and use no shell.

## Telegram accuracy and limits

The Telegram hook routes to the real event chat/topic and isolates its cursor by
profile, database, bot, destination, and exact memory identity/session. It excludes
expired, future-valid, inactive and foreign rows, distinguishes an existing
snapshot from newly observed rows, and shows IDs, evidence and stored confidence.
It acknowledges only displayed eligible rows after Telegram accepts delivery.

The upstream `agent:end` hook supplies no callback/reply handle. This integration
therefore does **not** attach nonfunctional Telegram buttons, impersonate a
callback handler, or start a competing `getUpdates` consumer. Use Hermes' existing
memory tools for chat-driven recall/ingest, or the documented scoped host CLI/API
for inspection/correction/retraction. Detailed configuration, explicit ownership
bindings, delivery guarantees and limitations are in the
[Telegram hook README](../hermes/hooks/luminary-activity/README.md).

## Primary contracts

- [OpenCode V2 plugins](https://opencode.ai/v2/docs/plugins/),
  [published SDK 2.1.4](https://www.npmjs.com/package/@opencode/plugin/v/2.1.4)
- [pi extensions](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/extensions.md)
- [omp v18.12.6 extension types](https://github.com/can1357/oh-my-pi/blob/v18.12.6/packages/coding-agent/src/extensibility/extensions/types.ts)
- [Hermes gateway hook context](https://github.com/NousResearch/hermes-agent/blob/main/gateway/hooks.py)
