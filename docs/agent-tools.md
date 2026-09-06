# Agent tools

This page separates the two shipped adapter surfaces. OpenCode has exactly two
explicit tools and strict automatic recall. The Hermes provider has a separate,
larger tool/configuration surface.

## OpenCode tools

### `luminary_recall(query, tags?)`

Searches scoped durable reference material. `query` is required and `tags` is
optional. Empty queries return a structured error. Results include status,
confidence, memories, scores, and provenance; recalled text is untrusted
reference material. The plugin supplies OpenCode-derived scope.

### `luminary_ingest(content, tags?)`

The only OpenCode durable write path. `content` is required, tags are optional
and cleaned, and empty content returns a structured error. Ordinary chat, hooks,
and inferred preferences never authorize a write. The plugin supplies
ownership scope; the model cannot override it or provide ownership fields. The
sidecar returns `{status, accepted, id}` or a structured error.

OpenCode automatic recall is hook-based and strict. It tracks only the latest
query, caps injected reference context at five memories and 5000 characters,
and requires confidence `0.34` or higher. It injects no block on abstention,
empty results, or sidecar failure.

## Hermes provider tools

The following tools are Hermes-only and are not registered by OpenCode.

### `luminary_recall`

Runs the scoped four-strategy fused recall. The JSON result contains `status`,
`reason`, `confidence`, `memories`, `scores`, and `provenance`.

### `luminary_ingest`

Stores a new durable memory through the Hermes provider. The provider supplies
source and ownership scope; exact duplicates are suppressed.

### `luminary_list`

Lists recent memories for inspection. It is not a recall query and not an
episode-ledger reader.

### `luminary_core_add`, `luminary_core_remove`, `luminary_core_list`

Manage DB-backed `core` memories that Hermes auto-loads into its system prompt.
These core tools are not present in OpenCode.

## Hermes tool availability by mode

| Mode | Auto-recall | Auto-retain | Tools registered |
|------|-------------|-------------|------------------|
| `context` | Yes | Yes | None |
| `tools` | No | Yes | All six |
| `hybrid` | Yes | Yes | All six |

## OpenCode/Hermes capability matrix

| Capability | OpenCode | Hermes provider |
| --- | --- | --- |
| Automatic recall | Yes, strict latest-query hook | Configurable |
| Explicit recall | `luminary_recall` | `luminary_recall` |
| Explicit ingest | `luminary_ingest` | `luminary_ingest` |
| List | Sidecar operation only, no tool | `luminary_list` |
| Core tools | No | Yes |
| Auto-retain | No | Yes/configurable |
| Episode fallback | No | Yes |
| LLM maintenance | No | Optional |

## Error and scope behavior

OpenCode tool calls carry normalized `worktree` or `directory`, agent name,
session id, and a local identity (`userID`, then `LUMINARY_USER_ID`, then
`USER`/`USERNAME`/`HOME`) in client/protocol context. Durable recall and ingest
use only `user_id`/`workspace_id`/`agent_id`; the sidecar removes `session_id`
from current durable recall/ingest/list scope. No current OpenCode sidecar
operation exposes exact-session continuity or episode operations. The model
cannot supply ownership fields. Sidecar failures return structured errors; they
do not fail the OpenCode request.
