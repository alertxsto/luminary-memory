# Luminary Memory — Hermes memory provider

Self-hosted, owner-scoped long-term memory for Hermes Agent. It runs on your
machine: SQLite by default, optional PostgreSQL/pgvector. No hosted service and
no account.

## What it does

- **Auto-recall** — injects relevant memories before a turn using four
  strategies (semantic, keyword, temporal, graph) fused with RRF.
- **Auto-retain** — curates completed turns into durable memories; chit-chat and
  acknowledgements are dropped instead of stored.
- **Tools** — `luminary_recall`, `luminary_ingest`, `luminary_list`,
  `luminary_core_add`, `luminary_core_remove`, `luminary_core_list`.
- **Lifecycle** — deduplication, consolidation, importance estimation, pruning
  and maintenance.
- **Setup** — `post_setup` selects Luminary for the profile and disables
  Hermes's native memory surfaces, so one store stays authoritative.

## Install

```bash
hermes plugins install luminary
hermes memory setup        # choose Luminary
```

## Configuration

Settings live in `~/.hermes/luminary/config.json` and in the dashboard panel
(typed schema). Secrets are read through Hermes's secret scope:
`LUMINARY_LLM_API_KEY` and `LUMINARY_PG_DSN`.

## Disclosure

- **Storage** — writes `~/.hermes/luminary/luminary.db` (SQLite) and
  `~/.hermes/luminary/config.json`. With `backend: pgvector` it writes to the
  PostgreSQL database in your DSN instead.
- **Network** — none by default. Optional LLM curation (`ingest_llm`,
  `auto_maintain`) sends turn text to the OpenAI-compatible `llm_base_url` you
  configure. Optional pgvector connects to your DSN.
- **Reads outside its own data** — the active Hermes profile home (to resolve
  the store path) and Hermes's secret scope for the two keys above.
- **Shell commands** — none.
- **Background processes** — one maintenance thread inside the Hermes process;
  no separate process or daemon.
- **Credentials** — none stored by the plugin; secrets come from Hermes.
- **Telemetry** — none.

## License

Apache-2.0
