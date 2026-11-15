# Security Policy

## Data privacy

By default, memories and embeddings are stored in a local SQLite database. The database is not encrypted by Luminary.

Network access can occur when the configured embedding model is downloaded, when PostgreSQL is hosted on another machine, or when an explicitly configured LLM enrichment, maintenance, or explanation request is sent to its endpoint. An uncached model is not guaranteed to work offline.

Scope checks separate records within the application. They do not protect a store from another process running with the same operating-system owner's permissions. Use separate stores and trusted identities when different users must be isolated.

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

- Protect the SQLite database, its `-wal` and `-shm` files, and any backups or exports with filesystem permissions. Luminary stores memory content and embeddings in plaintext; `0600` is recommended for private files.
- Retracting or forgetting a memory removes it from ordinary active recall but retains history and source material. Backups, exports, host transcripts, and data already sent to an external provider are outside that operation.
- Secure PostgreSQL with a least-privileged role, strong credentials, and network access controls. Application scope is not a replacement for database authorization.
- Never commit a live database file or credentials to version control. `REPORT-*.md`, `.commandcode/`, and generated `docs/api/` are gitignored.
- PyPI publishing uses **Trusted Publisher (OIDC)** — no API tokens in the repo. A leaked token in `~/.pypirc` should be deleted from PyPI account settings.
- LLM enrichment sends turn content to the configured endpoint. It is disabled by default; only enable `ingest_llm`/`auto_maintain` with a trusted provider. Inspector explanations are separately requested and disclose their destination before confirmation.
