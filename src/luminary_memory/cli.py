"""Command-line interface for luminary-memory."""

from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.table import Table

from luminary_memory.api import MemoryClient
from luminary_memory.config import Settings

app = typer.Typer(
    name="luminary-memory",
    help="Self-hosted memory layer for AI agents.",
    no_args_is_help=True,
)
console = Console()


def _client(db_path: str | None, backend: str | None) -> MemoryClient:
    settings = Settings()
    if db_path is not None:
        settings.db_path = db_path
    if backend is not None:
        settings.backend = backend
    return MemoryClient(settings=settings)


@app.callback()
def _main(
    ctx: typer.Context,
) -> None:
    """Global entry point with clean error handling."""
    # Typer calls the callback before the command; exceptions raised by
    # commands bubble up to the console as tracebacks. We catch them here
    # by wrapping execution — typer doesn't offer a hook, so commands rely
    # on _safe_run per command. (Kept as the documented entry point.)


def _safe_run(fn):
    """Run a command body, converting unexpected exceptions to clean errors."""
    try:
        return fn()
    except typer.Exit:
        raise
    except Exception as exc:  # noqa: BLE001 — CLI boundary: show clean message
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(1)


def _clamp_limit(limit: int) -> int | None:
    n = int(limit)
    if n == 0:
        return None
    if n < 0:
        raise ValueError("--limit must be >= 0 (0 means unlimited)")
    return n


@app.command()
def add(
    text: str = typer.Argument(..., help="Memory content to store"),
    tags: str | None = typer.Option(None, "--tags", "-t", help="Comma-separated tags"),
    source: str | None = typer.Option(None, "--source", "-s", help="Source label"),
    db_path: str | None = typer.Option(None, "--db-path", help="Override SQLite path"),
    backend: str | None = typer.Option(None, "--backend", help="sqlite | pgvector"),
) -> None:
    """Store a new memory."""
    client = _client(db_path, backend)
    try:
        tag_list = [t.strip() for t in tags.split(",")] if tags else None
        mid = client.ingest(text, tags=tag_list, source=source)
        if mid is None:
            console.print("[yellow]rejected by whitelist[/yellow]")
            raise typer.Exit(1)
        console.print(f"[green]added[/green] id={mid}")
    finally:
        client.close()


@app.command()
def recall(
    query: str = typer.Argument(..., help="Query to recall memories for"),
    limit: int = typer.Option(10, "--limit", "-l", help="Max results (0 = unlimited)"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON"),
    db_path: str | None = typer.Option(None, "--db-path", help="Override SQLite path"),
    backend: str | None = typer.Option(None, "--backend", help="sqlite | pgvector"),
) -> None:
    """Recall memories using the full four-strategy pipeline."""
    def run():
        lim = _clamp_limit(limit)
        if lim is None:
            lim = 0
        client = _client(db_path, backend)
        try:
            result = client.recall(query, limit=lim)
            if json_out:
                payload = {
                    "memories": [
                        {"id": m.id, "content": m.content, "tags": m.tags} for m in result.memories
                    ],
                    "scores": result.scores,
                    "strategies_hit": result.strategies_hit,
                }
                console.print(json.dumps(payload, indent=2))
                return
            table = Table(title=f"Recall: {query}")
            table.add_column("id", style="dim")
            table.add_column("score", justify="right")
            table.add_column("content")
            for m, s in zip(result.memories, result.scores):
                table.add_row(str(m.id), f"{s:.4f}", m.content)
            console.print(table)
        finally:
            client.close()

    _safe_run(run)


@app.command()
def search(
    query: str = typer.Argument(..., help="Keyword to search"),
    limit: int = typer.Option(10, "--limit", "-l", help="Max results (0 = unlimited)"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON"),
    db_path: str | None = typer.Option(None, "--db-path", help="Override SQLite path"),
    backend: str | None = typer.Option(None, "--backend", help="sqlite | pgvector"),
) -> None:
    """Keyword (FTS) search only."""
    def run():
        lim = _clamp_limit(limit)
        if lim is None:
            lim = 0
        client = _client(db_path, backend)
        try:
            rows = client.search(query, limit=lim)
            if json_out:
                payload = [
                    {
                        "id": m.id,
                        "content": m.content,
                        "tags": m.tags,
                        "metadata": m.metadata,
                        "source": m.source,
                        "score": float(s),
                    }
                    for m, s in rows
                ]
                console.print(json.dumps(payload, indent=2))
                return
            for m, score in rows:
                console.print(f"[dim]{m.id}[/dim] ({score:.4f}) {m.content}")
        finally:
            client.close()

    _safe_run(run)


@app.command()
def list(
    limit: int = typer.Option(100, "--limit", "-l", help="Max rows (0 = unlimited)"),
    offset: int = typer.Option(0, "--offset", help="Skip N rows"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON"),
    db_path: str | None = typer.Option(None, "--db-path", help="Override SQLite path"),
    backend: str | None = typer.Option(None, "--backend", help="sqlite | pgvector"),
) -> None:
    """List memories, most recent first."""
    def run():
        lim = _clamp_limit(limit)
        if lim is None:
            lim = 0
        client = _client(db_path, backend)
        try:
            rows = client.list(limit=lim, offset=max(0, offset))
            if json_out:
                payload = [
                    {
                        "id": m.id,
                        "content": m.content,
                        "tags": m.tags,
                        "metadata": m.metadata,
                        "source": m.source,
                        "importance": m.importance,
                        "created_at": m.created_at,
                    }
                    for m in rows
                ]
                console.print(json.dumps(payload, indent=2))
                return
            for m in rows:
                tags = ",".join(m.tags or [])
                console.print(f"[dim]{m.id}[/dim] {m.content}" + (f" [cyan]#{tags}[/cyan]" if tags else ""))
        finally:
            client.close()

    _safe_run(run)


@app.command("export")
def export_cmd(
    path: str = typer.Option(..., "--path", "-p", help="Output JSON file"),
    include_embeddings: bool = typer.Option(True, "--include-embeddings/--no-embeddings",
                                            help="Include embeddings in export"),
    db_path: str | None = typer.Option(None, "--db-path", help="Override SQLite path"),
    backend: str | None = typer.Option(None, "--backend", help="sqlite | pgvector"),
) -> None:
    """Export all memories to a versioned JSON file."""
    def run():
        client = _client(db_path, backend)
        try:
            result = client.export(path, include_embeddings=include_embeddings)
            console.print(json.dumps(result, indent=2))
        finally:
            client.close()
    _safe_run(run)


@app.command("import")
def import_cmd(
    path: str = typer.Option(..., "--path", "-p", help="Input JSON file"),
    db_path: str | None = typer.Option(None, "--db-path", help="Override SQLite path"),
    backend: str | None = typer.Option(None, "--backend", help="sqlite | pgvector"),
) -> None:
    """Import memories from a JSON file (uses batch ingest)."""
    def run():
        client = _client(db_path, backend)
        try:
            result = client.import_memories(path)
            console.print(json.dumps(result, indent=2))
        finally:
            client.close()
    _safe_run(run)


@app.command()
def lifecycle(
    db_path: str | None = typer.Option(None, "--db-path", help="Override SQLite path"),
    backend: str | None = typer.Option(None, "--backend", help="sqlite | pgvector"),
) -> None:
    """Run cleanup + consolidate + prune."""
    client = _client(db_path, backend)
    try:
        result = client.run_lifecycle()
        console.print(json.dumps(result, indent=2))
    finally:
        client.close()


@app.command()
def stats(
    db_path: str | None = typer.Option(None, "--db-path", help="Override SQLite path"),
    backend: str | None = typer.Option(None, "--backend", help="sqlite | pgvector"),
) -> None:
    """Show store statistics."""
    client = _client(db_path, backend)
    try:
        console.print(json.dumps(client.stats(), indent=2))
    finally:
        client.close()


if __name__ == "__main__":
    app()
