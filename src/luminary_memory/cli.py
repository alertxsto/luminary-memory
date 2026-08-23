"""Command-line interface for luminary-memory."""

from __future__ import annotations

import json
import os

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
    # CLI is an accuracy-facing surface: unrelated queries must abstain and
    # destructive rule replacement stays opt-in. Scope can be supplied by the
    # runner without putting identity values into command history.
    settings = Settings(strict_recall=True, evidence_required=True, rule_auto_replace=False)
    if db_path is not None:
        settings.db_path = db_path
    if backend is not None:
        settings.backend = backend
    scope = {
        key: os.environ.get(env_name)
        for key, env_name in (
            ("user_id", "LUMINARY_USER_ID"),
            ("workspace_id", "LUMINARY_WORKSPACE_ID"),
            ("agent_id", "LUMINARY_AGENT_ID"),
            ("session_id", "LUMINARY_SESSION_ID"),
        )
        if os.environ.get(env_name)
    }
    return MemoryClient(settings=settings, scope=scope)


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
                    "status": result.status,
                    "reason": result.reason,
                    "confidence": result.confidence,
                    "count": len(result.memories),
                    "memories": [
                        {
                            "id": m.id,
                            "content": m.content,
                            "tags": m.tags,
                            "source": m.source,
                            "created_at": m.created_at,
                            "importance": m.importance,
                            "observed_at": m.observed_at,
                            "valid_from": m.valid_from,
                            "valid_to": m.valid_to,
                            "confidence": m.confidence,
                            "evidence_quote": m.evidence_quote,
                            "source_id": m.source_id,
                        }
                        for m in result.memories
                    ],
                    "scores": result.scores,
                    "strategies_hit": result.strategies_hit,
                    "provenance": result.provenance,
                }
                typer.echo(json.dumps(payload, indent=2))
                return
            if not result.memories:
                reason = f" ({result.reason})" if result.reason else ""
                console.print(f"🌙 Luminary — no relevant memories found{reason}", markup=False)
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
def activity(
    limit: int = typer.Option(3, "--limit", "-l", help="Recent stored memories to show (0 = unlimited)"),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
    db_path: str | None = typer.Option(None, "--db-path", help="Override SQLite path"),
    backend: str | None = typer.Option(None, "--backend", help="sqlite | pgvector"),
) -> None:
    """Show recent persisted memory activity for CLI and hook verification."""
    def run():
        lim = _clamp_limit(limit)
        if lim is None:
            lim = 0
        client = _client(db_path, backend)
        try:
            rows = client.list(limit=lim, offset=0)
            items = [
                {
                    "id": m.id,
                    "content": m.content,
                    "tags": m.tags or [],
                    "source": m.source,
                    "importance": float(m.importance),
                    "created_at": m.created_at,
                }
                for m in rows
            ]
            payload = {
                "status": "active" if items else "idle",
                "event": "memory_activity",
                "count": len(items),
                "memories": items,
            }
            if json_out:
                typer.echo(json.dumps(payload, indent=2))
                return
            if not rows:
                console.print("🌙 Luminary — no stored memory activity", markup=False)
                return
            noun = "memory" if len(rows) == 1 else "memories"
            console.print(f"🌙 Luminary — {len(rows)} recent {noun} stored", markup=False)
            for m in rows:
                content = str(m.content or "").replace("\n", " ").strip()
                if len(content) > 140:
                    content = content[:140].rsplit(" ", 1)[0] + "…"
                tags = ", ".join(m.tags or [])
                is_rule = float(m.importance or 0.0) >= 0.85 or any(
                    t in {"core", "rule"} for t in (m.tags or [])
                )
                icon = "📌" if is_rule else "•"
                console.print(f"  {icon} #{m.id} {content}", markup=False)
                details = []
                if tags:
                    details.append(f"tags: {tags}")
                if m.source:
                    details.append(f"source: {m.source}")
                if details:
                    console.print(f"    {' · '.join(details)}", markup=False)
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
                typer.echo(json.dumps(payload, indent=2))
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
                typer.echo(json.dumps(payload, indent=2))
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
            typer.echo(json.dumps(result, indent=2))
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
            typer.echo(json.dumps(result, indent=2))
        finally:
            client.close()
    _safe_run(run)


@app.command()
def lifecycle(
    semantic: bool = typer.Option(True, "--semantic/--no-semantic",
                                  help="Use embedding-cosine consolidation (default: on)"),
    db_path: str | None = typer.Option(None, "--db-path", help="Override SQLite path"),
    backend: str | None = typer.Option(None, "--backend", help="sqlite | pgvector"),
) -> None:
    """Run cleanup + consolidate + prune."""
    client = _client(db_path, backend)
    try:
        result = client.run_lifecycle(semantic=semantic)
        typer.echo(json.dumps(result, indent=2))
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
        typer.echo(json.dumps(client.stats(), indent=2))
    finally:
        client.close()


@app.command()
def health(
    json_output: bool = typer.Option(False, "--json", help="Emit raw JSON"),
    db_path: str | None = typer.Option(None, "--db-path", help="Override SQLite path"),
    backend: str | None = typer.Option(None, "--backend", help="sqlite | pgvector"),
) -> None:
    """Show store health score (0-100) with per-dimension breakdown."""
    client = _client(db_path, backend)
    try:
        report = client.health_score()
        if json_output:
            typer.echo(json.dumps(report, indent=2))
            return
        score = report["score"]
        bar = "█" * int(score / 10) + "░" * (10 - int(score / 10))
        console.print(f"[bold]📊 Memory Health: {score}/100[/bold] {bar}")
        for name, dim in report.get("dimensions", {}).items():
            health = dim["health"]
            mark = "✅" if health >= 80 else ("⚠️" if health >= 60 else "❌")
            console.print(f"  {mark} {name}: {health:.0f}%")
        for rec in report.get("recommendations", []):
            console.print(f"  [yellow]→ {rec}[/yellow]")
    finally:
        client.close()


@app.command()
def version() -> None:
    """Show the installed version and runtime."""
    import platform

    from luminary_memory import __version__

    console.print(f"luminary-memory {__version__} (Python {platform.python_version()})")


@app.command()
def graph(
    limit: int = typer.Option(20, "--limit", "-n", help="Max entities/relations"),
    relations: bool = typer.Option(False, "--relations", help="Also print edges"),
    json_output: bool = typer.Option(False, "--json", help="Emit raw JSON"),
    db_path: str | None = typer.Option(None, "--db-path", help="Override SQLite path"),
    backend: str | None = typer.Option(None, "--backend", help="sqlite | pgvector"),
) -> None:
    """Show the knowledge graph (entities + co-occurrence relations)."""
    client = _client(db_path, backend)
    try:
        data = client.graph(limit=limit)
        if json_output:
            typer.echo(json.dumps(data, indent=2))
            return
        table = Table(title="Knowledge Graph")
        table.add_column("Entity", style="cyan")
        table.add_column("Degree", justify="right")
        table.add_column("Memories", justify="right")
        for e in data["entities"]:
            table.add_row(e["name"], str(e["degree"]), str(e["memories"]))
        console.print(table)
        if relations and data["relations"]:
            rtable = Table(title="Relations")
            rtable.add_column("Source")
            rtable.add_column("Target")
            rtable.add_column("Weight", justify="right")
            for r in data["relations"]:
                rtable.add_row(r["source"], r["target"], f"{r['weight']:.1f}")
            console.print(rtable)
    finally:
        client.close()


if __name__ == "__main__":
    app()
