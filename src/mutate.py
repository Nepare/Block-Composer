from pathlib import Path

import naming
from blocks import Block, BlockStore
from config import Settings
from errors import BlockValidationError
from llm.prompts import mutate_prompt
from llm.router import get_client_and_model


def _parse_mutation_reply(reply: str) -> tuple[str, str]:
    if "===BODY===" not in reply or "===LABEL===" not in reply:
        raise BlockValidationError(
            "Mutation reply missing the required ===BODY===/===LABEL=== markers."
        )
    body_part, _, label_part = reply.partition("===LABEL===")
    body = body_part.split("===BODY===", 1)[1].strip()
    label = label_part.strip().strip("[]").strip()
    if not body or not label:
        raise BlockValidationError("Mutation reply had an empty body or label.")
    return body, label


def run_mutate(
    block_id: str,
    criteria: str,
    *,
    settings: Settings,
    model_spec: str | None = None,
    in_place: bool = False,
) -> tuple[Block, Path]:
    store = BlockStore(settings.blocks_path)
    original = store.load(block_id)

    client, model = get_client_and_model(model_spec or settings.models.mutate, settings)
    messages = mutate_prompt(original.body, criteria)
    reply = client.chat(messages, model, temperature=0.5, max_tokens=600)
    try:
        body, label = _parse_mutation_reply(reply)
    except BlockValidationError:
        retry_messages = messages + [
            {"role": "assistant", "content": reply},
            {
                "role": "user",
                "content": "That reply didn't use the required ===BODY===/===LABEL=== "
                "format. Reply again in exactly that format.",
            },
        ]
        reply = client.chat(retry_messages, model, temperature=0.5, max_tokens=600)
        body, label = _parse_mutation_reply(reply)

    mutated = Block(
        id=original.id if in_place else "",
        body=body,
        schema=original.schema,
        source=original.source,
        created_by="manual" if in_place else "mutated",
        generation_criteria=criteria,
        mutated_from=None if in_place else original.id,
    )

    if in_place:
        path = store.save(mutated, filename_stem=original.id)
        return mutated, path

    # The mutate call already produced its own bracket label — no second naming call.
    base_slug = naming.slugify(original.name)
    stem = naming.unique_stem(f"{base_slug} [{naming.slugify(label)}]", store.exists)
    path = store.save(mutated, filename_stem=stem)
    return mutated, path
