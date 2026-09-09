from typing import Callable

from core import constraints as constraints_module
from core import naming
from models.blocks import Block
from core.config import Settings
from core.errors import BlockValidationError, InputError, OperationCancelled
from tools.generate import validate_block_shape
from llm.prompts import mutate_prompt
from llm.router import get_client_and_model
from core.progress import ProgressEvent, ProgressSink
from storage.router import get_block_storage


def _parse_mutation_reply(reply: str) -> tuple[str, str]:
    if "===BODY===" not in reply or "===LABEL===" not in reply:
        raise BlockValidationError(
            "Mutation reply missing the required ===BODY===/===LABEL=== markers."
        )
    body_part, _, label_part = reply.partition("===LABEL===")
    body = body_part.split("===BODY===", 1)[1].strip()
    # bound to the first non-empty line so a rambling reply can't swallow the whole label
    label_lines = [line.strip() for line in label_part.strip().splitlines() if line.strip()]
    label = label_lines[0].strip("[]").strip() if label_lines else ""
    if not body or not label:
        raise BlockValidationError("Mutation reply had an empty body or label.")
    validate_block_shape(body)
    return body, label


def run_mutate(
    block_id: str,
    criteria: str,
    *,
    settings: Settings,
    model_spec: str | None = None,
    in_place: bool = False,
    preserve: bool = False,
    name: str | None = None,
    on_progress: ProgressSink | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> tuple[Block, str]:
    """`on_progress`/`cancel_check` are optional and no-op by default, like compose.run_compose's."""
    progress = on_progress or (lambda _event: None)
    if name is not None and in_place:
        raise InputError("--name cannot be combined with --in-place.")
    explicit_base = naming.validate_explicit_name(name) if name is not None else None
    store = get_block_storage(settings)
    original = store.load(block_id)

    client, model = get_client_and_model(model_spec or settings.llm.models.mutate, settings, on_progress=progress)
    mutate_constraints = constraints_module.load(settings, "mutate")
    messages = mutate_prompt(original.body, criteria, mutate_constraints)
    progress(ProgressEvent(kind="mutate_start", message=f"Mutating {block_id}…", block_id=block_id))
    reply = client.chat(messages, model, temperature=0.2, max_tokens=900, reasoning_effort="low")
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
        reply = client.chat(retry_messages, model, temperature=0.2, max_tokens=900, reasoning_effort="low")
        body, label = _parse_mutation_reply(reply)

    if explicit_base is not None:
        body = naming.apply_explicit_title(body, name)

    mutated = Block(
        id=original.id if in_place else "",
        body=body,
        schema=original.schema,
        tags=list(original.tags),
        source=original.source,
        created_by="manual" if in_place else "mutated",
        generation_criteria=criteria,
        mutated_from=None if in_place else original.id,
        preserved=preserve,
    )

    if in_place:
        stem = store.save(mutated, filename_stem=original.id)
        progress(ProgressEvent(kind="mutate_done", message=f"Mutated -> {stem}", block_id=stem))
        return mutated, stem

    if explicit_base is not None:
        _decision, stem = store.save_with_dedup(mutated, explicit_base=explicit_base)
        progress(ProgressEvent(kind="mutate_done", message=f"Mutated -> {stem}", block_id=stem))
        return mutated, stem

    if naming.slugify(mutated.name) == naming.slugify(original.name):
        # same subject, just adapted -- the mutate call's own label already names the variant
        base_slug = naming.slugify(original.name)
        same_subject_base = f"{base_slug}_mut_{naming.slugify(label)}"
        _decision, stem = store.save_with_dedup(mutated, explicit_base=same_subject_base)
        progress(ProgressEvent(kind="mutate_done", message=f"Mutated -> {stem}", block_id=stem))
        return mutated, stem

    # a genuinely different subject now -- gets its own name via the normal dedup flow
    progress(ProgressEvent(kind="naming", message="Checking for duplicates / naming result…"))
    naming_client, naming_model = get_client_and_model(settings.llm.models.naming, settings, on_progress=progress)
    naming_constraints = constraints_module.load(settings, "naming")
    decision, stem = store.save_with_dedup(
        mutated,
        naming_client=naming_client,
        naming_model=naming_model,
        naming_constraints=naming_constraints,
    )
    if stem is None:
        # exact duplicate -- reuse the existing entry rather than discard the mutation
        stem = decision.duplicate_of
    progress(ProgressEvent(kind="mutate_done", message=f"Mutated -> {stem}", block_id=stem))
    return mutated, stem
