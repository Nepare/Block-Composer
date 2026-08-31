from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table
from rich.tree import Tree

import auth as auth_module
import compose as compose_module
import dissect as dissect_module
import generate as generate_module
import mutate as mutate_module
from blocks import BlockStore
from config import load_settings
from errors import CvdocsError

app = typer.Typer(add_completion=False, help="cvdocs — a configurable block library and composer.")
auth_app = typer.Typer(help="Google OAuth login/status.")
blocks_app = typer.Typer(help="Inspect the local block library.")
app.add_typer(auth_app, name="auth")
app.add_typer(blocks_app, name="blocks")

console = Console()


def _settings():
    return load_settings()


def _print_error(exc: Exception) -> None:
    # Rich treats [...] as markup, and our own bracket-variant filenames
    # (e.g. "police_station [jail].md") show up in error text constantly — escape() is
    # what stops that from being silently swallowed instead of printed.
    console.print(f"[red]{escape(str(exc))}[/red]")


@auth_app.command("login")
def auth_login():
    try:
        auth_module.login(_settings())
    except CvdocsError as exc:
        _print_error(exc)
        raise typer.Exit(1)
    console.print("[green]Authenticated.[/green]")


@auth_app.command("status")
def auth_status():
    valid, scopes = auth_module.status(_settings())
    if valid:
        console.print(f"[green]Token valid.[/green] Scopes: {escape(', '.join(scopes)) or '(none recorded)'}")
    else:
        console.print("[yellow]Not authenticated — run `cvdocs auth login`.[/yellow]")


@app.command()
def dissect(
    doc: str = typer.Argument(..., help="Google Doc URL or ID"),
    blocks_dir: Optional[Path] = typer.Option(None, "--blocks-dir"),
    templates_file: Optional[Path] = typer.Option(None, "--templates-file"),
):
    settings = _settings()
    try:
        result = dissect_module.run_dissect(
            doc, settings=settings, blocks_dir=blocks_dir, templates_path=templates_file
        )
    except CvdocsError as exc:
        _print_error(exc)
        raise typer.Exit(1)

    table = Table(title="Dissect summary")
    table.add_column("Result")
    table.add_column("Block")
    table.add_column("Path / note")
    for block, path in result.saved:
        table.add_row("saved", escape(block.name), escape(str(path)))
    for block, path, label in result.variants:
        table.add_row(escape(f"variant [{label}]"), escape(block.name), escape(str(path)))
    for name, dup_of in result.skipped_duplicates:
        table.add_row("skipped (duplicate)", escape(name), escape(f"matches {dup_of}"))
    console.print(table)


@app.command()
def generate(
    criteria: str = typer.Option(..., "--criteria"),
    schema: str = typer.Option("project_entry", "--schema"),
    style_from: list[str] = typer.Option([], "--style-from"),
    model: Optional[str] = typer.Option(None, "--model"),
    count: int = typer.Option(1, "--count"),
):
    settings = _settings()
    store = BlockStore(settings.blocks_path)
    try:
        style_blocks = [store.load(bid) for bid in style_from] if style_from else None
    except CvdocsError as exc:
        _print_error(exc)
        raise typer.Exit(1)

    for _ in range(count):
        try:
            _block, decision, path = generate_module.run_generate(
                criteria, settings=settings, schema=schema, style_from=style_blocks, model_spec=model
            )
        except CvdocsError as exc:
            _print_error(exc)
            raise typer.Exit(1)
        if decision.action == "skip_duplicate":
            console.print(f"[yellow]Skipped — duplicate of {escape(decision.duplicate_of or '')}[/yellow]")
        else:
            console.print(f"[green]Saved[/green] {escape(str(path))}")


@app.command()
def mutate(
    block_id: str = typer.Argument(...),
    criteria: str = typer.Option(..., "--criteria"),
    model: Optional[str] = typer.Option(None, "--model"),
    in_place: bool = typer.Option(False, "--in-place"),
):
    settings = _settings()
    try:
        _block, path = mutate_module.run_mutate(
            block_id, criteria, settings=settings, model_spec=model, in_place=in_place
        )
    except CvdocsError as exc:
        _print_error(exc)
        raise typer.Exit(1)
    console.print(f"[green]Saved[/green] {escape(str(path))}")


@app.command()
def compose(
    request: str = typer.Argument("", help="Natural-language composition request"),
    use: list[str] = typer.Option([], "--use"),
    generate_: list[str] = typer.Option([], "--generate"),
    out: Optional[Path] = typer.Option(None, "--out"),
    model: Optional[str] = typer.Option(None, "--model"),
    max_generate: int = typer.Option(8, "--max-generate"),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    settings = _settings()
    try:
        slots, result_path = compose_module.run_compose(
            request,
            settings=settings,
            use_ids=use,
            generate_criteria=generate_,
            out_path=out,
            model_spec=model,
            max_generate=max_generate,
            dry_run=dry_run,
        )
    except CvdocsError as exc:
        _print_error(exc)
        raise typer.Exit(1)

    tree = Tree("Compose plan")
    for slot in sorted(slots, key=lambda s: s.order):
        label = slot.resolved_id or slot.block_id or "(pending)"
        line = f"[{slot.order}] {slot.action} -> {label}"
        if slot.criteria:
            line += f"  ({slot.criteria})"
        tree.add(escape(line))
    console.print(tree)

    if dry_run:
        console.print("[yellow]Dry run — nothing written.[/yellow]")
    else:
        console.print(f"[green]Written[/green] {escape(str(result_path))}")


@blocks_app.command("list")
def blocks_list(
    tag: list[str] = typer.Option([], "--tag"),
    query: Optional[str] = typer.Option(None, "--query"),
):
    settings = _settings()
    store = BlockStore(settings.blocks_path)
    results = store.search(query=query, tags=tag or None)
    table = Table(title="Blocks")
    table.add_column("id")
    table.add_column("name")
    table.add_column("tags")
    table.add_column("schema")
    for b in results:
        table.add_row(escape(b.id), escape(b.name), escape(", ".join(b.tags)), escape(b.schema or ""))
    console.print(table)


@blocks_app.command("show")
def blocks_show(block_id: str = typer.Argument(...)):
    settings = _settings()
    store = BlockStore(settings.blocks_path)
    try:
        block = store.load(block_id)
    except CvdocsError as exc:
        _print_error(exc)
        raise typer.Exit(1)
    console.print(escape(block.body))


if __name__ == "__main__":
    app()
