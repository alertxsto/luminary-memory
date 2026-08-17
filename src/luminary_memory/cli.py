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
    limit: int = typer.Option(10, "--limit", "-l", help="Max results"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON"),
    db_path: str | None = typer.Option(None, "--db-path", help="Override SQLite path"),
    backend: str | None = typer.Option(None, "--backend", help="sqlite | pgvector"),
) -> None:
    """Recall memories using the full four-strategy pipeline."""
    client = _client(db_path, backend)
    try:
        result = client.recall(query, limit=limit)
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


@app.command()
def search(
    query: str = typer.Argument(..., help="Keyword to search"),
    limit: int = typer.Option(10, "--limit", "-l", help="Max results"),
    db_path: str | None = typer.Option(None, "--db-path", help="Override SQLite path"),
    backend: str | None = typer.Option(None, "--backend", help="sqlite | pgvector"),
) -> None:
    """Keyword (FTS) search only."""
    client = _client(db_path, backend)
    try:
        for m, score in client.search(query, limit=limit):
            console.print(f"[dim]{m.id}[/dim] ({score:.4f}) {m.content}")
    finally:
        client.close()


@app.command()
def list(
    limit: int = typer.Option(100, "--limit", "-l", help="Max rows"),
    offset: int = typer.Option(0, "--offset", help="Skip N rows"),
    db_path: str | None = typer.Option(None, "--db-path", help="Override SQLite path"),
    backend: str | None = typer.Option(None, "--backend", help="sqlite | pgvector"),
) -> None:
    """List memories, most recent first."""
    client = _client(db_path, backend)
    try:
        for m in client.list(limit=limit, offset=offset):
            tags = ",".join(m.tags or [])
            console.print(f"[dim]{m.id}[/dim] {m.content}" + (f" [cyan]#{tags}[/cyan]" if tags else ""))
    finally:
        client.close()


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
