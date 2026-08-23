# Quickstart

## Install

```bash
pip install luminary-memory
```

For development:

```bash
git clone <repo> && cd luminary-memory
pip install -e ".[dev]"
```

## First use (Python)

```python
from luminary_memory import MemoryClient

client = MemoryClient(db_path="memory.db")

# 1. store a fact
memory_id = client.ingest(
    "The deploy target is the staging cluster",
    tags=["deploy"],
    source="quickstart",
    evidence_quote="The deploy target is the staging cluster",
)

# 2. recall context
result = client.recall("where do we deploy?", limit=5)
print(result.status, result.confidence)
for memory, score in zip(result.memories, result.scores):
    print(f"{score:.3f}  {memory.content}")

# 3. maintain the store
client.run_lifecycle()

# bulk ingest (faster than individual calls)
client.ingest_batch([
    "staging database password is test",
    "production database is read-only for agents"
], tags=[["infra"], ["infra", "prod"]])


# 4. check store health (0-100 score + recommendations)
print(client.health_score())

client.close()
```

## First use (CLI)

```bash
luminary-memory add "The deploy target is the staging cluster" --tags deploy
luminary-memory recall "where do we deploy?" --json
luminary-memory activity --limit 5
luminary-memory stats
luminary-memory health
```

## Backup & restore

```bash
luminary-memory export --path backup.json
luminary-memory import --path backup.json
```

`export` writes all memories to a JSON file (migration/backup); `import`
restores them (recomputing embeddings when absent).


## Hermes Agent Integration

Set the memory provider in your Hermes `config.yaml`:

```yaml
memory:
  provider: luminary
  memory_enabled: false
  user_profile_enabled: false
```

The two existing Hermes switches disable the native `MEMORY.md` and `USER.md`
surfaces. Keep them disabled while Luminary is selected so Hermes does not
present two persistent memory authorities to the agent. `hermes/install.sh`
applies this edit automatically.

If Hermes runs from a dedicated virtual environment, point the installer at
that interpreter so package installation and capability activation use the
same runtime:

```bash
HERMES_PYTHON="$HOME/.hermes/venv/bin/python" bash hermes/install.sh
```

The installer edits the public Hermes config boundary only. It does not patch
Hermes source, pin a Hermes release, or create profile configs that do not
already exist.

At runtime, keep these surfaces distinct: `core` rows are loaded every
session, durable recall is query-driven and evidence-aware, and a bounded
untrusted exact-session episode block is used only when durable recall has no
usable result. The episode block preserves a short follow-up's active task;
it is not a durable memory and never broadens scope to another session.

## Optional: LLM memory curation

Direct `MemoryClient.ingest()` calls are stored without an LLM by default. For
automatic Hermes turn batches, the provider requires curation before a batch
enters durable memory; otherwise the raw transcript is skipped. To have an
LLM evaluate turns, drop non-durable content, and store concise factual
summaries, enable `ingest_llm` and optionally `auto_maintain`:

```bash
pip install "luminary-memory[hermes]"
```

```json
// ~/.hermes/luminary/config.json (Hermes provider)
{
  "ingest_llm": true,
  "auto_maintain": true,
  "llm_base_url": "https://api.commandcode.ai/provider/v1",
  "llm_model": "deepseek/deepseek-v4-flash",
  "llm_api_key": "your-key"
}
```

Any OpenAI-compatible endpoint works. With `ingest_llm`, the provider first
curates each completed turn and then runs a serialized evidence-backed review
against exact-scope candidates, so explicit corrections can supersede claims
without a second memory authority. `auto_maintain` additionally reviews the
store at session end, keeping current facts and updating/deleting stale or
duplicate memories. If a provider curation call fails or produces no durable
summary, the turn is not promoted into semantic memory instead of saving a raw
transcript. When automatic retain is enabled, the accepted turn still remains
in the exact-session continuity ledger, so a curation rejection and a missing
durable memory are not the same thing.

## Accuracy-first provider defaults

Hermes and the CLI enable strict recall, require evidence/provenance, and
disable destructive rule replacement. An unrelated query therefore returns an
explicit abstention instead of a plausible-looking top result:

```json
{
  "status": "abstain",
  "reason": "no_supported_candidate",
  "memories": [],
  "provenance": []
}
```

For a store created before the single-authority provider path, inspect the
read-only repair report before enabling more writes:

```bash
python scripts/repair_memory_authority.py \
  --db-path ~/.hermes/luminary/memory.db
```

## Configuration

All settings accept a `LUMINARY_*` env var:

| Setting | Env var | Default |
|---------|---------|---------|
| `backend` | `LUMINARY_BACKEND` | `sqlite` |
| `db_path` | `LUMINARY_DB_PATH` | `luminary_memory.db` |
| `pg_dsn` | `LUMINARY_PG_DSN` | `postgresql://localhost/luminary_memory` |
| `embedding_model` | `LUMINARY_EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` |
| `token_budget` | `LUMINARY_TOKEN_BUDGET` | `4096` |
| `importance_recall_boost` | `LUMINARY_IMPORTANCE_RECALL_BOOST` | `1.0` |
| `rule_auto_replace` | `LUMINARY_RULE_AUTO_REPLACE` | `true` |
| `rule_auto_replace_threshold` | `LUMINARY_RULE_AUTO_REPLACE_THRESHOLD` | `0.85` |
| `rule_importance` | `LUMINARY_RULE_IMPORTANCE` | `0.9` |

Scope can be supplied without putting identity values in shell history:

```bash
export LUMINARY_USER_ID=u1
export LUMINARY_WORKSPACE_ID=luminary
export LUMINARY_AGENT_ID=coding-agent
export LUMINARY_SESSION_ID=session-42
```

See the [README](../README.md) for the full table.
