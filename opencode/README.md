# opencode-luminary-memory

This package provides the Luminary Memory OpenCode plugin and its agent skill.
It is a thin adapter: durable memory remains owned by the Python
`luminary-memory` package and is reached through a local JSONL sidecar.

## Supported install

Requirements:

- OpenCode with plugin support.
- Python 3.11 or newer.
- `luminary-memory` installed in the Python environment that OpenCode uses.

Bun is only needed to develop or test this package. OpenCode manages the npm
plugin runtime installation.

Install the two artifacts:

```bash
python -m pip install "luminary-memory==0.3.0"
```

The plugin entry is added to the current OpenCode configuration. The equivalent
valid configuration is:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": ["opencode-luminary-memory@0.1.0"]
}
```

The bundled skill is at
`node_modules/opencode-luminary-memory/skills/luminary-memory/SKILL.md`.
Copy it to the OpenCode skills directory used by your installation, for
example `.opencode/skills/luminary-memory/SKILL.md`, if your OpenCode setup
does not discover package skills automatically.

## Sidecar and verification

The plugin starts `python -m luminary_memory.opencode.sidecar` on demand. Set
`LUMINARY_DB_PATH` or pass a database path through plugin options to select the
store. SQLite is the default backend, and the default database path is
`luminary_memory.db` in the sidecar working directory. No network daemon is
required.

After restarting OpenCode, verify the local sidecar with a health request:

```bash
printf '%s\n' '{"protocol_version":"1","request_id":"health-1","operation":"health","scope":{"user_id":"local:example-user","workspace_id":"/absolute/project","agent_id":"opencode"},"payload":{}}' \
  | python -m luminary_memory.opencode.sidecar
```

The response must be JSON with `"request_id":"health-1"` and
`"status":"ok"`. OpenCode automatically recalls relevant, confident memory
as reference context. `luminary_recall` and `luminary_ingest` are the only
explicit tools; ordinary chat never writes durable memory. The skill is
guidance only, and recalled text is untrusted reference material. Mandatory
project rules remain in `AGENTS.md`.

If Python, the sidecar, or the database is unavailable, automatic recall is
skipped and explicit tools return an error result; the OpenCode request
continues. Scope context includes a configured local identity, normalized
repository/worktree `workspace_id`, OpenCode `agent_id`, and protocol/client
`session_id`. Durable recall and ingest use only user/workspace/agent scope;
the sidecar removes `session_id` from current durable recall/ingest/list scope.
No current OpenCode sidecar operation (`health`, `recall`, `ingest`, or `list`, as
applicable) exposes exact-session continuity or episode operations. The default identity is `local:` plus `LUMINARY_USER_ID`, then
`USER`/`USERNAME` or `HOME`; configure `userID` when needed. It uses no API key and does
not merge different OS users. Automatic recall uses strict abstention for
low-confidence results.

## Compatibility

`opencode-luminary-memory@0.1.0` is tested with `luminary-memory==0.3.0` and
the `@opencode-ai/plugin` API baseline `^1.18.29`. This documents the tested
plugin API baseline, not a claim that every OpenCode release is compatible.
The artifacts require JSONL protocol version `1`; keep their versions paired
and do not infer compatibility from unrelated OpenCode or Python versions. The
Python package requires Python 3.11+.
