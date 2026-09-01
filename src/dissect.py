from dataclasses import dataclass
from pathlib import Path

import constraints as constraints_module
import docs_api
import templates as templates_module
from blocks import Block, BlockStore
from config import Settings
from llm.router import get_client_and_model
from parsing.structural_walk import find_blocks_table
from parsing.table_to_block import extract_block, named_style_bold_defaults
from progress import ProgressEvent, ProgressSink


@dataclass
class DissectResult:
    saved: list[tuple[Block, Path]]
    skipped_duplicates: list[tuple[str, str]]  # (candidate_name, duplicate_of_stem)
    variants: list[tuple[Block, Path, str]]  # (block, path, bracket_label)


def run_dissect(
    doc_id_or_url: str,
    *,
    settings: Settings,
    blocks_dir: Path | None = None,
    templates_path: Path | None = None,
    on_progress: ProgressSink | None = None,
) -> DissectResult:
    """`on_progress`, if given, fires once per extracted row — optional, no-op by default,
    so this stays silent when called directly as before."""
    progress = on_progress or (lambda _event: None)
    doc_id = docs_api.resolve_doc_id(doc_id_or_url)
    document = docs_api.get_document(doc_id)

    schema = templates_module.load_block_schema(templates_path or settings.templates_file)
    blocks_table = find_blocks_table(document, schema.section_marker, schema.table_columns)
    style_defaults = named_style_bold_defaults(document)

    store = BlockStore(blocks_dir or settings.blocks_path)
    # Only used lazily, per-conflict — extraction itself makes zero LLM calls.
    naming_client, naming_model = get_client_and_model(settings.models.naming, settings, on_progress=progress)
    naming_constraints = constraints_module.load(settings, "naming")

    saved: list[tuple[Block, Path]] = []
    skipped: list[tuple[str, str]] = []
    variants: list[tuple[Block, Path, str]] = []

    rows = blocks_table.rows
    for i, row in enumerate(rows, start=1):
        block = extract_block(row, schema, style_defaults)
        block.source = doc_id
        decision, path = store.save_with_dedup(
            block,
            naming_client=naming_client,
            naming_model=naming_model,
            naming_constraints=naming_constraints,
        )
        if decision.action == "skip_duplicate":
            skipped.append((block.name, decision.duplicate_of or ""))
        elif decision.action == "save_variant":
            variants.append((block, path, decision.label or ""))
        else:
            saved.append((block, path))
        progress(
            ProgressEvent(
                kind="dissect_row",
                message=f"[{i}/{len(rows)}] {block.name} -> {decision.action}",
                step=i,
                total=len(rows),
                block_id=path.stem if path else decision.duplicate_of,
            )
        )

    return DissectResult(saved=saved, skipped_duplicates=skipped, variants=variants)
