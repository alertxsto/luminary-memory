# Hermes integration

Use luminary-memory as the memory layer for a [Hermes Agent](https://github.com/NousResearch/hermes-agent).

## Install the skill

Copy `hermes/SKILL.md` into the agent's skills directory:

```bash
mkdir -p ~/.hermes/skills/luminary-memory
cp hermes/SKILL.md ~/.hermes/skills/luminary-memory/SKILL.md
```

## How the agent uses it

1. **Ingest on tool call** — after learning a durable fact (preference, environment detail), call `client.ingest(...)`.
2. **Recall into the system prompt** — before answering, call `client.recall(query)` and inject the top memories as context.
3. **Lifecycle via cron** — schedule `luminary-memory lifecycle` to keep the store clean.

## Example

```python
from luminary_memory import MemoryClient

client = MemoryClient(db_path="~/.luminary/memory.db")

# durable fact learned this session
client.ingest("user prefers concise responses", tags=["preference"], source="hermes")

# recall relevant context for the current turn
result = client.recall("response style preference", limit=3)
context = "\n".join(m.content for m in result.memories)

client.close()
```

Inject `context` into the agent's system prompt for the current turn.
