from pathlib import Path
from typing import Callable

import constraints as constraints_module
import naming
from blocks import Block, BlockStore
from config import Settings
from errors import BlockValidationError, OperationCancelled
from generate import validate_block_shape
from llm.prompts import mutate_prompt
from llm.router import get_client_and_model
from progress import ProgressEvent, ProgressSink


def _parse_mutation_reply(reply: str) -> tuple[str, str]:
    if "===BODY===" not in reply or "===LABEL===" not in reply:
        raise BlockValidationError(
            "Mutation reply missing the required ===BODY===/===LABEL=== markers."
        )
    body_part, _, label_part = reply.partition("===LABEL===")
    body = body_part.split("===BODY===", 1)[1].strip()
    # bound to the first non-empty line: a verbose model may keep rambling after the
    # label instead of stopping, and the label must never swallow all of that
    label_lines = [line.strip() for line in label_part.strip().splitlines() if line.strip()]
    label = label_lines[0].strip("[]").strip() if label_lines else ""
    if not body or not label:
        raise BlockValidationError("Mutation reply had an empty body or label.")
    # catches e.g. the model echoing the prompt's own unfilled "<...>" placeholder back
    validate_block_shape(body)
    return body, label


def run_mutate(
    block_id: str,
    criteria: str,
    *,
    settings: Settings,
    model_spec: str | None = None,
    in_place: bool = False,
    on_progress: ProgressSink | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> tuple[Block, Path]:
    """`on_progress`/`cancel_check` mirror compose.run_compose's — optional, no-op by
    default, so this stays silent and uncancellable when called directly as before."""
    progress = on_progress or (lambda _event: None)
    store = BlockStore(settings.blocks_path)
    original = store.load(block_id)

    client, model = get_client_and_model(model_spec or settings.models.mutate, settings, on_progress=progress)
    mutate_constraints = constraints_module.load(settings, "mutate")
    messages = mutate_prompt(original.body, criteria, mutate_constraints)
    progress(ProgressEvent(kind="mutate_start", message=f"Mutating {block_id}…", block_id=block_id))
    reply = client.chat(messages, model, temperature=0.2, max_tokens=900)
    try:
        body, label = _parse_mutation_reply(reply)
    except BlockValidationError:
        if cancel_check and cancel_check():
            raise OperationCancelled("Cancelled before the mutate retry.")
        progress(
            ProgressEvent(
                kind="mutate_retry",
                message="Reply didn't match the required format — retrying once…",
                block_id=block_id,
            )
        )
        retry_messages = messages + [
            {"role": "assistant", "content": reply},
            {
                "role": "user",
                "content": "That reply didn't use the required ===BODY===/===LABEL=== "
                "format. Reply again in exactly that format.",
            },
        ]
        reply = client.chat(retry_messages, model, temperature=0.2, max_tokens=900)
        body, label = _parse_mutation_reply(reply)

    mutated = Block(
        id=original.id if in_place else "",
        body=body,
        schema=original.schema,
        tags=list(original.tags),
        source=original.source,
        created_by="manual" if in_place else "mutated",
        generation_criteria=criteria,
        mutated_from=None if in_place else original.id,
    )

    if in_place:
        path = store.save(mutated, filename_stem=original.id)
        progress(ProgressEvent(kind="mutate_done", message=f"Mutated -> {path.stem}", block_id=path.stem))
        return mutated, path

    if naming.slugify(mutated.name) == naming.slugify(original.name):
        # Same subject, just adapted -- the mutate call's own `label` already names the
        # variant, so no second naming call is needed.
        base_slug = naming.slugify(original.name)
        stem = naming.unique_stem(f"{base_slug}_mut_{naming.slugify(label)}", store.exists)
        path = store.save(mutated, filename_stem=stem)
        progress(ProgressEvent(kind="mutate_done", message=f"Mutated -> {path.stem}", block_id=path.stem))
        return mutated, path

    # The mutation turned this into a genuinely different thing (e.g. "Lumber" ->
    # "Stone Quarry") -- it's not a variant of the original, so it gets its own name via
    # the normal dedup flow rather than being forced under the original's stem.
    progress(ProgressEvent(kind="naming", message="Checking for duplicates / naming result…"))
    naming_client, naming_model = get_client_and_model(settings.models.naming, settings, on_progress=progress)
    naming_constraints = constraints_module.load(settings, "naming")
    decision, path = store.save_with_dedup(
        mutated,
        naming_client=naming_client,
        naming_model=naming_model,
        naming_constraints=naming_constraints,
    )
    if path is None:
        # exact duplicate of something already in the library -- reuse it rather than
        # silently discarding the mutation the user asked for
        path = store.path_for(decision.duplicate_of)
    progress(ProgressEvent(kind="mutate_done", message=f"Mutated -> {path.stem}", block_id=path.stem))
    return mutated, path
