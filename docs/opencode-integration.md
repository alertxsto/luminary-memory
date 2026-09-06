# OpenCode Integration

Luminary Memory supports OpenCode through the published
`opencode-luminary-memory` npm plugin and the `luminary-memory` Python package.
The plugin starts a local Python JSONL sidecar; it does not open a port or
change the memory engine. Hermes remains a separate adapter and its behavior
is unchanged.

## Architecture

OpenCode loads the compiled TypeScript plugin from the npm package. The plugin
owns hook registration, explicit tools, scope mapping, and sidecar lifecycle.
The Python sidecar owns the JSONL protocol boundary and delegates recall,
ingest, listing, SQLite storage, evidence, and lifecycle semantics to the
existing `MemoryClient`. The skill is agent guidance only and is not a storage
mechanism.

## Install one supported way

Use the matching artifact versions from the package release. The supported
OpenCode installation path is the project `opencode.json` plugin array; OpenCode
installs npm packages through Bun:

```bash
python -m pip install "luminary-memory==0.3.0"
```

The resulting configuration shape is:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": ["opencode-luminary-memory@0.1.0"]
}
```

The package contains the compiled plugin at `dist/plugin.js` and the skill at
`skills/luminary-memory/SKILL.md`. Install the skill into the project or user
OpenCode skills directory when package skill discovery is not enabled:

```bash
mkdir -p .opencode/skills/luminary-memory
cp path/to/node_modules/opencode-luminary-memory/skills/luminary-memory/SKILL.md \
  .opencode/skills/luminary-memory/SKILL.md
```

OpenCode discovers project configuration from `opencode.json` (or JSONC),
local plugins from `.opencode/plugins/`, and user plugins from
`~/.config/opencode/plugins/`. Skills use the plural
`.opencode/skills/<name>/SKILL.md` path; the global equivalent is
`~/.config/opencode/skills/<name>/SKILL.md`. Package skill discovery may vary
by installation, so the copy above is the reliable project-local fallback.

## Runtime and storage

Python 3.11+ and the `luminary-memory` Python installation are required in the
environment named by the plugin's `pythonExecutable` option, or in `python`
on `PATH`. The sidecar is discovered as
`python -m luminary_memory.opencode.sidecar` and communicates only over local
stdin/stdout JSONL. SQLite is the default backend. `LUMINARY_DB_PATH` selects
the database path; otherwise the normal `luminary_memory.db` default applies.
No network-facing daemon is required.

Verify the sidecar independently before opening a project:

```bash
printf '%s\n' '{"protocol_version":"1","request_id":"health-1","operation":"health","scope":{"user_id":"local:example-user","workspace_id":"/absolute/project","agent_id":"opencode"},"payload":{}}' \
  | python -m luminary_memory.opencode.sidecar
```

An `ok` response with the same request id confirms protocol and database
startup. A missing Python dependency, failed subprocess, malformed response,
or database failure is graceful: automatic recall produces no injected block,
and explicit tools return a structured error without failing the OpenCode
request.

## Tools and hooks

The plugin registers exactly two tools: `luminary_recall(query, tags?)` and
`luminary_ingest(content, tags?)`. Recall is reference-only; ingest is the only
durable write path and is explicit. Empty query/content is rejected, tags are
trimmed, and the model cannot provide ownership fields. Automatic recall uses
`chat.message` to cache the latest query and
`experimental.chat.system.transform` to add a bounded untrusted reference
block. Session deletion clears its cache and client; `dispose` closes all
clients. There is no automatic ingest, `luminary_list` tool, core-memory tool
set, OpenCode indicator, episode ledger, or LLM review path.

## Protocol

| Item | Contract |
| --- | --- |
| Version | `1` |
| Operations | `health`, `recall`, `ingest`, `list` |
| Protocol/client context | `user_id`, `workspace_id`, `agent_id`, optional `session_id` |
| Response | `protocol_version`, `request_id`, `status: ok\|error`, result or `{code,message}` |

The sidecar serializes requests one at a time. `health` returns the library
health report; recall, ingest, and list use the scoped Python `MemoryClient`.

## Troubleshooting

- **Python not found:** set `clientOptions.pythonExecutable` to the Python
  environment containing `luminary-memory`.
- **Unexpected database:** set `LUMINARY_DB_PATH` or
  `clientOptions.databasePath`; the default is `luminary_memory.db` in the
  sidecar working directory.
- **Skill missing:** copy the bundled skill to
  `.opencode/skills/luminary-memory/SKILL.md`.
- **Malformed output or timeout:** inspect the Python sidecar environment and
  `clientOptions.timeoutMs`; stdout must contain JSONL responses only.
- **Tool error:** check the structured error output and Python/database
  permissions. OpenCode continues without memory when the sidecar fails.

## Scope and writes

The adapter carries these OpenCode fields in protocol and client context:

| OpenCode context | Luminary field |
| --- | --- |
| configured local user or OS account | `user_id` |
| normalized repository/worktree | `workspace_id` |
| OpenCode agent name | `agent_id` |
| OpenCode session id | `session_id` (context/provenance; not durable recall/ingest/list scope) |

Automatic recall tracks only the latest in-process query and never persists it.
Automatic recall requests strict abstention and injects nothing when confidence
is low or the result is abstained. By default, `user_id` is `local:` plus
`LUMINARY_USER_ID`, then the OS `USER`/`USERNAME` account or `HOME` path; set the plugin
`userID` option or `LUMINARY_USER_ID` to configure it. This identity is a local
account name, not an API key, and prevents different OS users from sharing the
default scope.
The `luminary_recall` tool is explicit and returns status, confidence, and
provenance. Only the explicit `luminary_ingest` tool writes durable memory;
ordinary conversation, lifecycle events, and inferred preferences do not
authorize a write. The model cannot override ownership scope. Recalled content
is untrusted reference material, never instructions. Mandatory workflow rules
belong in `AGENTS.md`.

For durable `recall`, `ingest`, and `list`, the sidecar uses only
`user_id`/`workspace_id`/`agent_id` scope and deliberately removes
`session_id`. No current OpenCode sidecar operation (`health`, `recall`,
`ingest`, or `list`, as applicable) exposes exact-session continuity or episode
operations. `session_id` is protocol/provenance context only and does not make
ordinary durable operations session-scoped.

Keep `opencode-luminary-memory@0.1.0` paired with
`luminary-memory==0.3.0`; both use protocol version `1`. The OpenCode package
is tested against the `@opencode-ai/plugin` API baseline `^1.18.29`; this is
not a claim that every OpenCode release is compatible. The package does not
replace or alter the Hermes provider.
