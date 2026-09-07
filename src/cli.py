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
from storage.router import get_block_storage, get_result_storage
from core.text_input import resolve_text_input

app = typer.Typer(add_completion=False, help="cvdocs — a configurable block library and composer.")
auth_app = typer.Typer(help="Google OAuth login/status.")
blocks_app = typer.Typer(help="Inspect the local block library.")
results_app = typer.Typer(help="Inspect saved compose results.")
app.add_typer(auth_app, name="auth")
app.add_typer(blocks_app, name="blocks")
app.add_typer(results_app, name="results")

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
    name: Optional[str] = typer.Option(None, "--name"),
    count: int = typer.Option(1, "--count"),
    preserve: bool = typer.Option(False, "--preserve"),
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
                name=name,
                preserve=preserve,
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
    name: Optional[str] = typer.Option(None, "--name"),
    preserve: bool = typer.Option(False, "--preserve"),
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
            name=name,
            preserve=preserve,
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
    from_blocks: Optional[list[str]] = typer.Option(None, "--from-blocks"),
    generate_: list[str] = typer.Option([], "--generate"),
    out: Optional[Path] = typer.Option(None, "--out"),
    model: Optional[str] = typer.Option(None, "--model"),
    name: Optional[str] = typer.Option(None, "--name"),
    max_generate: int = typer.Option(8, "--max-generate"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    count: Optional[int] = typer.Option(None, "--count", "-n", help="Exact target number of projects in the output."),
    preserve: bool = typer.Option(False, "--preserve"),
    restrict_generate: bool = typer.Option(False, "--restrict-generate"),
    restrict_mutate: bool = typer.Option(False, "--restrict-mutate"),
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
        outcome = compose_module.run_compose(
            request_text,
            settings=settings,
            use_ids=use,
            from_block_ids=from_blocks,
            generate_criteria=generate_,
            out_path=out,
            model_spec=model,
            name=name,
            max_generate=max_generate,
            dry_run=dry_run,
            count=count,
            preserve=preserve,
            restrict_generate=restrict_generate,
            restrict_mutate=restrict_mutate,
            on_progress=RichConsoleSink(console),
        )
    except CvdocsError as exc:
        _print_error(exc)
        raise typer.Exit(1)

    tree = Tree("Compose plan")
    for slot in sorted(outcome.slots, key=lambda s: s.order):
        label = slot.resolved_id or slot.block_id or "(pending)"
        line = f"[{slot.order}] {slot.action} -> {label}"
        if slot.criteria:
            line += f"  ({slot.criteria})"
        tree.add(escape(line))
    console.print(tree)

    if dry_run:
        console.print("[yellow]Dry run — nothing written.[/yellow]")
    elif outcome.result_path:
        console.print(f"[green]Written[/green] {escape(str(outcome.result_path))}")
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
    console.print(f"[bold]Preserved:[/bold] {block.preserved}")


@blocks_app.command("delete")
def blocks_delete(block_id: str = typer.Argument(...)):
    settings = _settings()
    store = get_block_storage(settings)
    try:
        store.delete(block_id)
    except CvdocsError as exc:
        _print_error(exc)
        raise typer.Exit(1)
    console.print(f"[green]Deleted[/green] {escape(block_id)}")


@blocks_app.command("preserve")
def blocks_preserve(block_id: str = typer.Argument(...)):
    settings = _settings()
    store = get_block_storage(settings)
    try:
        store.set_preserved(block_id, True)
    except CvdocsError as exc:
        _print_error(exc)
        raise typer.Exit(1)
    console.print(f"[green]Preserved[/green] {escape(block_id)}")


@blocks_app.command("unpreserve")
def blocks_unpreserve(block_id: str = typer.Argument(...)):
    settings = _settings()
    store = get_block_storage(settings)
    try:
        store.set_preserved(block_id, False)
    except CvdocsError as exc:
        _print_error(exc)
        raise typer.Exit(1)
    console.print(f"[green]Unpreserved[/green] {escape(block_id)}")


@blocks_app.command("clear")
def blocks_clear():
    settings = _settings()
    store = get_block_storage(settings)
    result = store.clear()
    console.print(
        f"[green]Cleared[/green] deleted={result.deleted} skipped_preserved={result.skipped_preserved}"
    )


@results_app.command("list")
def results_list(query: Optional[str] = typer.Option(None, "--query")):
    settings = _settings()
    store = get_result_storage(settings)
    results = store.search(query=query)
    table = Table(title="Results")
    table.add_column("id")
    table.add_column("name")
    table.add_column("request")
    for r in results:
        table.add_row(escape(r.id), escape(r.name), escape(r.request))
    console.print(table)


@results_app.command("show")
def results_show(result_id: str = typer.Argument(...)):
    settings = _settings()
    store = get_result_storage(settings)
    try:
        result = store.load(result_id)
    except CvdocsError as exc:
        _print_error(exc)
        raise typer.Exit(1)
    console.print(escape(result.content))
    console.print(f"\n[bold]Request:[/bold] {escape(result.request or '(none)')}")
    console.print(f"[bold]Use ids:[/bold] {escape(', '.join(result.use_ids) or '(none)')}")
    console.print(f"[bold]Generate criteria:[/bold] {escape(', '.join(result.generate_criteria) or '(none)')}")
    console.print(f"[bold]Slots:[/bold] {escape(str(result.slots)) if result.slots else '(none)'}")
    console.print(f"[bold]Preserved:[/bold] {result.preserved}")


@results_app.command("delete")
def results_delete(result_id: str = typer.Argument(...)):
    settings = _settings()
    store = get_result_storage(settings)
    try:
        store.delete(result_id)
    except CvdocsError as exc:
        _print_error(exc)
        raise typer.Exit(1)
    console.print(f"[green]Deleted[/green] {escape(result_id)}")


@results_app.command("preserve")
def results_preserve(result_id: str = typer.Argument(...)):
    settings = _settings()
    store = get_result_storage(settings)
    try:
        store.set_preserved(result_id, True)
    except CvdocsError as exc:
        _print_error(exc)
        raise typer.Exit(1)
    console.print(f"[green]Preserved[/green] {escape(result_id)}")


@results_app.command("unpreserve")
def results_unpreserve(result_id: str = typer.Argument(...)):
    settings = _settings()
    store = get_result_storage(settings)
    try:
        store.set_preserved(result_id, False)
    except CvdocsError as exc:
        _print_error(exc)
        raise typer.Exit(1)
    console.print(f"[green]Unpreserved[/green] {escape(result_id)}")


@results_app.command("clear")
def results_clear():
    settings = _settings()
    store = get_result_storage(settings)
    result = store.clear()
    console.print(
        f"[green]Cleared[/green] deleted={result.deleted} skipped_preserved={result.skipped_preserved}"
    )


if __name__ == "__main__":
    app()
