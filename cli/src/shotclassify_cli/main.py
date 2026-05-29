"""ShotClassify CLI."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.json import JSON
from rich.table import Table

from shotclassify_common import configure_logging, get_settings
from shotclassify_common.pipeline import process_image
from shotclassify_store import Repository

app = typer.Typer(
    name="shotclassify",
    help="Drop a screenshot, get classification + extracted fields + suggested action.",
    add_completion=False,
    no_args_is_help=True,
)
console = Console()


@app.callback()
def _bootstrap() -> None:
    s = get_settings()
    configure_logging(level=s.app_log_level, fmt="console")


@app.command()
def classify(
    image: Path = typer.Argument(..., exists=True, readable=True, help="Path to a screenshot."),
    note: str | None = typer.Option(None, "--note", "-n", help="Extra hint for the classifier."),
    save: bool = typer.Option(True, "--save/--no-save", help="Persist to history."),
    pretty: bool = typer.Option(False, "--pretty", help="Pretty-print JSON."),
) -> None:
    """Classify a screenshot and print JSON result."""
    result = process_image(image, note=note, save=save)
    payload = result.model_dump(mode="json")
    if pretty:
        console.print(JSON.from_data(payload))
    else:
        sys.stdout.write(json.dumps(payload, default=str) + "\n")


@app.command()
def history(
    limit: int = typer.Option(20, "--limit", "-l"),
    query: str | None = typer.Option(None, "--query", "-q"),
) -> None:
    """Show recent classifications."""
    repo = Repository()
    rows = repo.list(limit=limit, query=query)
    table = Table(title=f"ShotClassify history ({len(rows)})")
    for col in ("id", "created", "category", "conf", "filename"):
        table.add_column(col)
    for r in rows:
        table.add_row(
            r.id,
            r.created_at.strftime("%Y-%m-%d %H:%M"),
            r.primary_category.value,
            f"{r.confidence:.2f}",
            r.filename,
        )
    console.print(table)


@app.command()
def show(item_id: str) -> None:
    """Show one classification record by id."""
    repo = Repository()
    r = repo.get(item_id)
    if r is None:
        console.print(f"[red]Not found:[/red] {item_id}")
        raise typer.Exit(code=1)
    console.print(JSON.from_data(r.model_dump(mode="json")))


@app.command()
def correct(item_id: str, category: str) -> None:
    """Re-label a record (used as future training data)."""
    from shotclassify_common import Category

    repo = Repository()
    try:
        cat = Category(category)
    except ValueError:
        console.print(f"[red]Unknown category[/red] {category}; valid: {Category.all()}")
        raise typer.Exit(code=2)
    r = repo.correct(item_id, cat)
    if r is None:
        console.print(f"[red]Not found:[/red] {item_id}")
        raise typer.Exit(code=1)
    console.print(f"[green]ok[/green] {item_id} -> {cat.value}")


@app.command()
def serve() -> None:
    """Run the API server (uvicorn)."""
    import uvicorn

    s = get_settings()
    uvicorn.run("services.api.app.main:app", host=s.app_host, port=s.app_port, reload=False)


if __name__ == "__main__":  # pragma: no cover
    app()
