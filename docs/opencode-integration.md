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

Use the matching artifact versions from the package release:

```bash
python -m pip install "luminary-memory==0.3.0"
opencode plug opencode-luminary-memory@0.1.0
```

OpenCode installs npm plugins through its plugin command and adds the package
to its configuration. The resulting configuration shape is:

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
  | luminary-memory-opencode
```

An `ok` response with the same request id confirms protocol and database
startup. A missing Python dependency, failed subprocess, malformed response,
or database failure is graceful: automatic recall produces no injected block,
and explicit tools return a structured error without failing the OpenCode
request.

## Scope and writes

The adapter maps OpenCode context to Luminary scope as follows:

| OpenCode context | Luminary field |
| --- | --- |
| configured local user or OS account | `user_id` |
| normalized repository/worktree | `workspace_id` |
| OpenCode agent name | `agent_id` |
| OpenCode session id | `session_id` |

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

Keep `opencode-luminary-memory@0.1.0` paired with
`luminary-memory==0.3.0`; both use protocol version `1`. The OpenCode package
is tested against the `@opencode-ai/plugin` API baseline `^1.18.29`; this is
not a claim that every OpenCode release is compatible. The package does not
replace or alter the Hermes provider.
