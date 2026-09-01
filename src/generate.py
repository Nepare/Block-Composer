from pathlib import Path
from typing import Callable

import frontmatter

import constraints as constraints_module
from blocks import Block, BlockStore
from config import Settings
from errors import BlockValidationError, OperationCancelled
from llm.prompts import generate_prompt
from llm.router import get_client_and_model
from naming import NamingDecision
from progress import ProgressEvent, ProgressSink


def validate_block_shape(body: str) -> None:
    """Shared by generate and mutate — both must produce a body that's plausibly a real
    entry: a heading and at least one labeled field. (Placeholder text the model might
    echo back unfilled, e.g. "<the full updated entry...>", fails the heading check below
    since it doesn't start with "#".)"""
    stripped = body.strip()
    if not stripped:
        raise BlockValidationError("Block body is empty.")
    if not stripped.startswith("#"):
        raise BlockValidationError("Block body must start with a Markdown heading (the name).")
    if "**" not in stripped:
        raise BlockValidationError(
            "Block body has no labeled fields (expected at least one **Label:** line)."
        )


def _pick_style_examples(
    schema: str, explicit: list[Block] | None, store: BlockStore, settings: Settings
) -> list[str]:
    if explicit:
        return [b.body for b in explicit]
    pool = [b for b in store.all() if b.schema == schema] or store.all()
    if pool:
        return [b.body for b in pool[:2]]
    # nothing dissected/generated yet — fall back to the shipped sample blocks so
    # `generate` still works out of the box, with a correctly-shaped example to learn from
    samples_dir = settings.sample_blocks_path
    return [frontmatter.load(str(p)).content for p in sorted(samples_dir.glob("*.md"))[:2]]


def run_generate(
    criteria: str,
    *,
    settings: Settings,
    schema: str = "project_entry",
    style_from: list[Block] | None = None,
    model_spec: str | None = None,
    on_progress: ProgressSink | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> tuple[Block, NamingDecision, Path | None]:
    """`on_progress`/`cancel_check` mirror compose.run_compose's — optional, no-op by
    default, so this stays silent and uncancellable when called directly as before."""
    progress = on_progress or (lambda _event: None)
    store = BlockStore(settings.blocks_path)
    client, model = get_client_and_model(model_spec or settings.models.generate, settings, on_progress=progress)
    examples = _pick_style_examples(schema, style_from, store, settings)
    generate_constraints = constraints_module.load(settings, "generate")
    messages = generate_prompt(criteria, examples, generate_constraints)

    progress(ProgressEvent(kind="generate_start", message=f"Generating a {schema} block…"))
    body = client.chat(messages, model, temperature=0.5, max_tokens=900)
    try:
        validate_block_shape(body)
    except BlockValidationError:
        if cancel_check and cancel_check():
            raise OperationCancelled("Cancelled before the generate retry.")
        # one automatic re-prompt, telling the model what was wrong
        progress(
            ProgressEvent(kind="generate_retry", message="Reply didn't match required shape — retrying once…")
        )
        retry_messages = messages + [
            {"role": "assistant", "content": body},
            {
                "role": "user",
                "content": "That reply didn't match the required shape. Reply again with "
                "ONLY a correctly-shaped entry.",
            },
        ]
        body = client.chat(retry_messages, model, temperature=0.5, max_tokens=900)
        validate_block_shape(body)

    block = Block(
        id="",
        body=body.strip(),
        schema=schema,
        source="generated",
        created_by="generated",
        generation_criteria=criteria,
    )
    progress(ProgressEvent(kind="naming", message="Checking for duplicates / naming result…"))
    naming_client, naming_model = get_client_and_model(settings.models.naming, settings, on_progress=progress)
    naming_constraints = constraints_module.load(settings, "naming")
    decision, path = store.save_with_dedup(
        block,
        naming_client=naming_client,
        naming_model=naming_model,
        naming_constraints=naming_constraints,
    )
    progress(ProgressEvent(kind="generate_done", message=f"Generated -> {path.stem if path else decision.duplicate_of}"))
    return block, decision, path
