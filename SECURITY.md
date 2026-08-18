# Security Policy

## Data privacy guarantee

luminary-memory is **local by design**. All memories are stored on the machine where the library runs — SQLite files or your own PostgreSQL instance. No data is sent to any third-party service, and no network calls are made for storage or retrieval (the only optional network activity is an LLM enrichment step, which you configure explicitly and remains disabled by default).

## Reporting a vulnerability

If you discover a security issue, please report it privately rather than opening a public issue:

1. Email the maintainer with a clear description and reproduction steps.
2. Do not disclose the vulnerability publicly until a fix is released.

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.2.x   | ✅ |
| 0.1.x   | ⚠️ (legacy — security fixes only) |

## Security considerations

- The default SQLite backend stores embeddings and content in plaintext on disk. Protect the file with filesystem permissions (`0600` recommended — the Hermes provider writes `config.json` with `0600`).
- The pgvector backend requires a PostgreSQL instance — secure it with a strong password and network access control.
- Never commit a live database file or credentials to version control. `REPORT-*.md`, `.commandcode/`, and generated `docs/api/` are gitignored.
- PyPI publishing uses **Trusted Publisher (OIDC)** — no API tokens in the repo. A leaked token in `~/.pypirc` should be deleted from PyPI account settings.
- The optional LLM enrichment step sends turn content to the configured endpoint. It is **disabled by default**; only enable `ingest_llm`/`auto_maintain` with a trusted provider.
