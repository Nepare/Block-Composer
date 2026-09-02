from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table
from rich.tree import Tree

from tools import compose as compose_module
from tools import dissect as dissect_module
from tools import generate as generate_module
from tools import mutate as mutate_module
from auth.router import get_auth_provider
from core.config import load_settings
from core.errors import AuthError, CvdocsError
from core.progress import RichConsoleSink
from storage.router import get_block_storage
from core.text_input import resolve_text_input

app = typer.Typer(add_completion=False, help="cvdocs — a configurable block library and composer.")
auth_app = typer.Typer(help="Google OAuth login/status.")
blocks_app = typer.Typer(help="Inspect the local block library.")
app.add_typer(auth_app, name="auth")
app.add_typer(blocks_app, name="blocks")

console = Console()


def _settings():
    return load_settings()


def _print_error(exc: Exception) -> None:
    # Rich treats [...] as markup, which bracket-variant filenames trigger — escape() first.
    console.print(f"[red]{escape(str(exc))}[/red]")


@auth_app.command("login")
def auth_login():
    provider = get_auth_provider(_settings())
    try:
        provider.login()
    except AttributeError:
        _print_error(AuthError("Local sign-in isn't available for this deployment's connection method."))
        raise typer.Exit(1)
    except CvdocsError as exc:
        _print_error(exc)
        raise typer.Exit(1)
    console.print("[green]Authenticated.[/green]")


@auth_app.command("status")
def auth_status():
    provider = get_auth_provider(_settings())
    try:
        valid, scopes = provider.status()
    except AttributeError:
        console.print(
            "[yellow]Status isn't available for this deployment's connection method.[/yellow]"
        )
        return
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
            doc,
            settings=settings,
            blocks_dir=blocks_dir,
            templates_path=templates_file,
            on_progress=RichConsoleSink(console),
        )
    except CvdocsError as exc:
        _print_error(exc)
        raise typer.Exit(1)

    table = Table(title="Dissect summary")
    table.add_column("Result")
    table.add_column("Block")
    table.add_column("id")
    for block, stem in result.saved:
        table.add_row("saved", escape(block.name), escape(stem))
    for block, stem, label in result.variants:
        table.add_row(escape(f"variant [{label}]"), escape(block.name), escape(stem))
    for name, dup_of in result.skipped_duplicates:
        table.add_row("skipped (duplicate)", escape(name), escape(f"matches {dup_of}"))
    console.print(table)


@app.command()
def generate(
    criteria: Optional[str] = typer.Option(None, "--criteria", help="Generation criteria, inline."),
    criteria_file: Optional[Path] = typer.Option(
        None, "--criteria-file", "-f", help="Read criteria from a UTF-8 .txt/.md file."
    ),
    schema: str = typer.Option("project_entry", "--schema"),
    style_from: list[str] = typer.Option([], "--style-from"),
    model: Optional[str] = typer.Option(None, "--model"),
    count: int = typer.Option(1, "--count"),
):
    settings = _settings()
    try:
        criteria_text = resolve_text_input(
            criteria, criteria_file, flag_inline="--criteria", flag_file="--criteria-file"
        )
    except CvdocsError as exc:
        _print_error(exc)
        raise typer.Exit(1)

    store = get_block_storage(settings)
    try:
        style_blocks = [store.load(bid) for bid in style_from] if style_from else None
    except CvdocsError as exc:
        _print_error(exc)
        raise typer.Exit(1)

    for _ in range(count):
        try:
            _block, decision, stem = generate_module.run_generate(
                criteria_text,
                settings=settings,
                schema=schema,
                style_from=style_blocks,
                model_spec=model,
                on_progress=RichConsoleSink(console),
            )
        except CvdocsError as exc:
            _print_error(exc)
            raise typer.Exit(1)
        if decision.action == "skip_duplicate":
            console.print(f"[yellow]Skipped — duplicate of {escape(decision.duplicate_of or '')}[/yellow]")
        else:
            console.print(f"[green]Saved[/green] {escape(stem)}")


@app.command()
def mutate(
    block_id: str = typer.Argument(...),
    criteria: Optional[str] = typer.Option(None, "--criteria", help="Mutation criteria, inline."),
    criteria_file: Optional[Path] = typer.Option(
        None, "--criteria-file", "-f", help="Read criteria from a UTF-8 .txt/.md file."
    ),
    model: Optional[str] = typer.Option(None, "--model"),
    in_place: bool = typer.Option(False, "--in-place"),
):
    settings = _settings()
    try:
        criteria_text = resolve_text_input(
            criteria, criteria_file, flag_inline="--criteria", flag_file="--criteria-file"
        )
    except CvdocsError as exc:
        _print_error(exc)
        raise typer.Exit(1)

    try:
        _block, stem = mutate_module.run_mutate(
            block_id,
            criteria_text,
            settings=settings,
            model_spec=model,
            in_place=in_place,
            on_progress=RichConsoleSink(console),
        )
    except CvdocsError as exc:
        _print_error(exc)
        raise typer.Exit(1)
    console.print(f"[green]Saved[/green] {escape(stem)}")


@app.command()
def compose(
    request: str = typer.Argument("", help="Natural-language composition request, inline."),
    request_file: Optional[Path] = typer.Option(
        None, "--request-file", "-f", help="Read the composition request from a UTF-8 .txt/.md file."
    ),
    use: list[str] = typer.Option([], "--use"),
    generate_: list[str] = typer.Option([], "--generate"),
    out: Optional[Path] = typer.Option(None, "--out"),
    model: Optional[str] = typer.Option(None, "--model"),
    max_generate: int = typer.Option(8, "--max-generate"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    count: Optional[int] = typer.Option(None, "--count", "-n", help="Exact target number of projects in the output."),
):
    settings = _settings()
    try:
        request_text = resolve_text_input(
            request, request_file, flag_inline="the request argument", flag_file="--request-file", required=False
        )
    except CvdocsError as exc:
        _print_error(exc)
        raise typer.Exit(1)

    try:
        slots, result_path = compose_module.run_compose(
            request_text,
            settings=settings,
            use_ids=use,
            generate_criteria=generate_,
            out_path=out,
            model_spec=model,
            max_generate=max_generate,
            dry_run=dry_run,
            count=count,
            on_progress=RichConsoleSink(console),
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
    elif result_path:
        console.print(f"[green]Written[/green] {escape(str(result_path))}")
    else:
        console.print("[green]Saved.[/green]")


@blocks_app.command("list")
def blocks_list(
    tag: list[str] = typer.Option([], "--tag"),
    query: Optional[str] = typer.Option(None, "--query"),
):
    settings = _settings()
    store = get_block_storage(settings)
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
    store = get_block_storage(settings)
    try:
        block = store.load(block_id)
    except CvdocsError as exc:
        _print_error(exc)
        raise typer.Exit(1)
    console.print(escape(block.body))


if __name__ == "__main__":
    app()
