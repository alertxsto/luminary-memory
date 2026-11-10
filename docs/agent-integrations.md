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
| omp | Extension API verified against v18.12.6; installed **18.18.5** acceptance re-verified | `/luminary`, model tool, TUI dialogs/status, serializable session messages for RPC consumers |

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
Python and all three native npm packages are published at `0.3.2`, with npm
`latest` pointing to that version. The OpenCode adapter targets V2; the older
npm `0.3.1` adapter is V1-only. Install the Python bridge into the environment
the host will use:

```bash
python -m pip install --upgrade "luminary-memory==0.3.2"
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
- **OpenCode website:** Ecosystem PR #58823 targets the V1 documentation file
  `packages/web/src/content/docs/ecosystem.mdx` and explicitly pins npm `0.3.1`.
  The bot confirmed no further concerns and the PR is ready for maintainer
  review. V2 npm publication does not establish V2 website visibility; no
  upstream merge or deployment is claimed.

Building packages does not itself publish to npm or submit/merge an upstream
PR. The release workflow builds validated tarballs, gates Python publication on
real-model recall, and attaches native artifacts to tag releases. npm publishing
is explicitly enabled by `PUBLISH_NPM_PLUGINS=true` after the three package names
and trusted publishers are configured; it never invents an authorization token.
The first publication requires maintainer npm authorization. Use
`scripts/bump-version.sh` to synchronize Python/plugin/lockfile versions before
the next coordinated release; do not overwrite an already-published Python tag.
See [contributor release instructions](../CONTRIBUTING.md).

Publication verified on 2026-10-25: Python and all three npm packages are
available at `0.3.2`:
[pi](https://www.npmjs.com/package/luminary-memory-pi),
[OpenCode](https://www.npmjs.com/package/luminary-memory-opencode), and
[omp](https://www.npmjs.com/package/luminary-memory-omp).
All npm `latest` tags and SHA-512 checksums match the validated release assets.
Installing all three from npm succeeded. The real V2 CLI also installed the
OpenCode package and an actual native session stored a fact through the
published PyPI wheel. That wheel's CLI installer and remember/recall/forget
operations passed; wheel and sdist SHA-256 checksums match PyPI.

The `0.3.2` V2 adapter was separately exercised in the real **2.1.4** server.
Native requests verified remember, same-session duplicate suppression, scoped
recall/activity, cross-workspace isolation, forget, empty recall after retraction,
and, in that older adapter, evidence injection into system context. The current
adapter instead uses request-local non-system references. Native completion also
stored a user-grounded curated fact, rejected an assistant-only claim with
`no_grounded_fact`, and stopped exposing tools after plugin removal. Python and
SQLite were real; model/curation responses came from deterministic localhost
fixtures. This does not claim model-quality or client-UI coverage.

The [source PR #17](https://github.com/alertxsto/luminary-memory/pull/17) has
merged into `main`. The
[Ecosystem PR #58823](https://github.com/anomalyco/opencode/pull/58823) is ready
for maintainer review with its V1 adapter pinned; it is not a V2 catalog or
proof of a live website listing.


## Interactive inspectors

The `0.3.3` source includes the inspector in the Python and native npm
packages. The published `0.3.2` packages do not include it. Installing the
inspector does not enable saving, start a server on import, or call an AI model.
Exact tested native hosts and the two remaining blocked surfaces are recorded
in the [roadmap matrix](ROADMAP.md#target-support-matrix).

Build the complete resources before installing this checkout or building its
wheel:

```bash
npm ci
npm run build
python -m pip install -e .
```

The development file installer writes complete directories:
`.opencode/plugins/luminary-memory/`, `.pi/extensions/luminary-memory/` or
`.omp/extensions/luminary-memory/`. It preserves unrelated config/dependencies
and user-added package files, refuses unapproved modifications to owned files,
and performs a staged module-tree cutover. An identifiable old single-file
Luminary hook requires explicit `--force` cutover; do not load it alongside the
new package. OpenCode's config-root dependencies must be available to its
loader, just as for the released copy installer.

OpenCode development sources target SDK `2.2.0`: server, typed RPC, TUI and the
separate `./gui-experimental` Desktop entry. The GUI uses the official preset,
not the terminal JSX transform. Actual CLI/Desktop 2.2.0 development acceptance
includes distinct remote stores, confirmed changes, native file dialogs,
read-only shared resources, revocation and reload. The full view is a native
dialog, not a fullscreen route. Actual Web 2.2.0 loads the server plugin but not
its GUI contributions; a released Web loader remains a separate dependency.

The native Sharing view lists only the current actor's incoming/outgoing
project grants, with bounded pagination. Receiving `read` does not grant
`contribute`, `edit` or `retract`, and an incoming grant still requires explicit
project selection before shared facts appear. Browsing this view never changes
memory ownership, access counters or saving configuration.

Headers display the verified server's native agent, profile, store identifier
and host. These are display fields, not browser-controlled identity selectors;
the native bearer stays server-side.

After updating a compiled pi package, restart pi. In the inspected bundled
pi1.4.0 runtime, `/reload` reset resources but retained the previous JavaScript
module; a full restart loaded the updated package. Long pi/omp TUI proposals use
a scrollable native review followed by a separate Cancel-first decision.
Review-editor changes are discarded; only the cached server proposal can commit.

For nonvisual pi inspector output, use its JSON print format:

```bash
pi --offline --mode json --print "/luminary full"
```

The inspected pi1.4.0 plain-text print mode does not display custom inspector
messages; JSON print returns the actual scoped state. RPC forwards supported
owner dialogs without constructing terminal components.

omp18.12.6 also returns scoped structured state with `--mode json --print` and
`--mode rpc --no-ui`. Headless RPC emits no dialog requests; UI-enabled RPC uses
supported dialogs, never a terminal overlay. This was re-verified on installed
omp **18.18.5** with a copy-installed extension. Host startup can require a
selected model even for these owner commands; inspecting memory does not invoke
it.

Install the matching unified Hermes UI/backend resources without changing the
selected provider or retention configuration:

```bash
luminary-memory hook install-hermes-ui --home /absolute/hermes-profile
```

Backend and local Desktop/dashboard enablement remain separate; see
[Hermes integration](hermes-integration.md). Hermes 0.22.5 terminal widget
discovery/rendering exists, but its SDK still needs authenticated native
session/profile/connection context and lifecycle before inspector completion.

The optional companion starts **only** through an explicit command:

```bash
luminary-memory hook companion --agent pi --workspace /absolute/project \
  --session-id NATIVE_SESSION_ID --profile default
```

Use the exact native agent, workspace, session and profile that own the
configured store. This never selects a database from browser JSON. The command
prints a private one-use owner sign-in link valid for 60 seconds; `--open`
explicitly opens it. Binding is loopback-only, sessions expire, and writes need
separate previews/confirmations. Ctrl+C stops the companion. Do not share its
link or mistake it for Hermes dashboard/OpenCode Web. Transfer covers memory
records and included lineage, not a full store backup.

See the [roadmap evidence and remaining native gates](ROADMAP.md).


## File-copy hook installer

This remains an alternative to native package installation. Install the
published Python bridge, then copy only the adapter for the host you use:

```bash
python -m pip install --upgrade "luminary-memory==0.3.2"
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

Embedded inspector callers that supply an environment mapping resolve settings
and the config file from that mapping without changing the process environment.
Inspector authority and one-shot control channels must come from the launcher,
not the config file. A supplied home directory that differs from the process
home is denied rather than resolving a default or `~` path against another
environment; launch a child with the intended home instead.

An explicitly selected missing config, or an unreadable or oversized config,
returns `unavailable` instead of opening a fallback store. SQLite paths beginning
with `~` are resolved against the process home before opening.

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

## Config file

Native adapters and the CLI load `~/.luminary/luminary.env` before each
operation. Use it for durable settings such as the LLM curation endpoint:

```ini
LUMINARY_INGEST_LLM=true
LUMINARY_LLM_BASE_URL=https://api.openai.com/v1
LUMINARY_LLM_API_KEY=sk-...
LUMINARY_LLM_MODEL=gpt-4o-mini
```

Process environment wins over the file. Set `LUMINARY_CONFIG_FILE` to another
path, or to `none` to disable file loading. Bridge processes are spawned per
operation, so edits apply on the next call without restarting the host. The file
may contain an API key; restrict its permissions to the account that runs the
agent. See the
[configuration reference](config-reference.md#config-file-for-native-integrations-and-cli).

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

Model-initiated remember also requires `evidence_quote`: an exact excerpt of
the current native user input, at most 4096 UTF-8 bytes. The adapter verifies
the source; a model cannot certify its own paraphrase, metadata, confidence,
or `confirmed` flag. The bridge refuses missing/unverifiable provenance with
`skipped` / `user_evidence_required`; a host may reject malformed tool arguments
before dispatch. Model-grounded paraphrases retain the original quote with
confidence `0` (unassessed, not a calibrated probability); an owner-typed
`/luminary remember TEXT` is an explicit assertion.
Tags `core`, `rule`, and the configured core tag require the owner-confirmed
inspector; the model tool returns `owner_confirmation_required` instead.
These checks govern new writes. Existing records are not automatically
re-certified or rewritten.

## Agent skill

The repository ships a portable OpenCode skill at
[`opencode/SKILL.md`](../opencode/SKILL.md). It documents tool selection, safe
durable-fact boundaries, result semantics, the config file, and bridge
troubleshooting.

Copy it to `~/.config/opencode/skills/luminary-memory/SKILL.md` for global use,
or to a project's `.opencode/skills/luminary-memory/SKILL.md`. OpenCode
discovers both locations automatically; no `opencode.json` entry is required.
The skill is documentation only and does not change plugin behavior.

## Automatic recall and retention

Before a normal user run, adapters recall strictly relevant, evidence-bearing
memory. Core-tagged rows must pass the same retrieval gate; unrelated core
rows do not override abstention. This differs from Hermes's separate pinned-core
surface. Historical data is a request-local, non-system reference before the
live user message, not a persistent transcript entry. Empty recall injects
nothing. Whole JSON records are serialized once within the bridge's 8000-character
budget; adapters do not slice or double-encode that reference. Aborted/error/
tool-only responses are not automatically retained. Compaction is not a write.

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
(`text`, `evidence_quote`, optional `tags`), `forget` (`memory_id`), `activity`, and `turn` (`user`,
`assistant`, optional lineage `tags`). Every action requires absolute workspace,
agent ID, and native session ID. Maximum request: 128 KiB; each text field:
32,768 characters. A response is a UTF-8 JSON object containing `ok`, `status`,
`reason`, `message`, `context`, `memories`, `stored`, and `deleted`; errors exit
nonzero. Keep stdout reserved for that response and treat recalled data as
untrusted. Native adapters bound process lifetime/output and use no shell.

For remember, the **trusted adapter**, never model arguments, supplies a fresh
`LUMINARY_BRIDGE_SOURCE` environment value to that one child process:
`{"agent":"…","workspace":"/absolute/project","session_id":"…","kind":"native_user","quote":"exact user excerpt"}`.
Validate that excerpt against actual current native user input before launching;
it must match the request's `evidence_quote`. Actual owner-typed commands may use
`kind:"operator"` instead, with their command text as the evidence. Agent,
workspace, and session must match the request. Clear inherited source values
on every launch; an absent source must not become a previous turn's authority.
This is an internal provenance channel, not a setting to put in `luminary.env`.
Settings-file loading ignores this process-only key, including explicit overrides.
The backend ignores model-provided source/confirmation/metadata fields.
Automatic curation also strips all protected core/rule tags from supplied and
extracted tags. Structural artifact filtering is shared by API, CLI, and bridge;
recall has no destructive-verb or language-specific suppression table.

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
