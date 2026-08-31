from pathlib import Path

import frontmatter

from blocks import Block, BlockStore
from config import Settings
from errors import BlockValidationError
from llm.prompts import generate_prompt
from llm.router import get_client_and_model
from naming import NamingDecision


def _validate_generated_body(body: str) -> None:
    stripped = body.strip()
    if not stripped:
        raise BlockValidationError("Generated block is empty.")
    if not stripped.startswith("#"):
        raise BlockValidationError("Generated block must start with a Markdown heading (the name).")
    if "**" not in stripped:
        raise BlockValidationError(
            "Generated block has no labeled fields (expected at least one **Label:** line)."
        )


def _pick_style_examples(schema: str, explicit: list[Block] | None, store: BlockStore) -> list[str]:
    if explicit:
        return [b.body for b in explicit]
    pool = [b for b in store.all() if b.schema == schema] or store.all()
    if pool:
        return [b.body for b in pool[:2]]
    # nothing dissected/generated yet — fall back to the shipped sample blocks so
    # `generate` still works out of the box, with a correctly-shaped example to learn from
    samples_dir = Path(__file__).resolve().parent.parent / "examples" / "sample_blocks"
    return [frontmatter.load(str(p)).content for p in sorted(samples_dir.glob("*.md"))[:2]]


def run_generate(
    criteria: str,
    *,
    settings: Settings,
    schema: str = "project_entry",
    style_from: list[Block] | None = None,
    model_spec: str | None = None,
) -> tuple[Block, NamingDecision, Path | None]:
    store = BlockStore(settings.blocks_path)
    client, model = get_client_and_model(model_spec or settings.models.generate, settings)
    examples = _pick_style_examples(schema, style_from, store)
    messages = generate_prompt(criteria, examples)

    body = client.chat(messages, model, temperature=0.5, max_tokens=600)
    try:
        _validate_generated_body(body)
    except BlockValidationError:
        # one automatic re-prompt, telling the model what was wrong
        retry_messages = messages + [
            {"role": "assistant", "content": body},
            {
                "role": "user",
                "content": "That reply didn't match the required shape. Reply again with "
                "ONLY a correctly-shaped entry.",
            },
        ]
        body = client.chat(retry_messages, model, temperature=0.5, max_tokens=600)
        _validate_generated_body(body)

    block = Block(
        id="",
        body=body.strip(),
        schema=schema,
        source="generated",
        created_by="generated",
        generation_criteria=criteria,
    )
    naming_client, naming_model = get_client_and_model(settings.models.naming, settings)
    decision, path = store.save_with_dedup(block, naming_client=naming_client, naming_model=naming_model)
    return block, decision, path
