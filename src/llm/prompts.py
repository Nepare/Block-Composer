"""Prompt templates. Every LLM interaction in cvdocs works on flat Markdown or plain text
in and out — never nested JSON for content — the one exception being compose's own plan,
which legitimately needs structured multi-field output to describe *which* action to take
per slot, distinct from the document content itself."""


GENERATE_SYSTEM = (
    "You write one new entry for a small personal block library. Match the exact field "
    "shape (same style of heading/name, description, and labeled or bulleted fields) shown "
    "in the reference example(s) you're given — same structure, new content matching the "
    "request. Reply with ONLY the Markdown entry, nothing else: no commentary, no code fences."
)


def generate_prompt(criteria: str, style_examples: list[str]) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": GENERATE_SYSTEM}]
    for example in style_examples:
        messages.append(
            {"role": "user", "content": f"Example entry for style/shape reference:\n{example}"}
        )
    messages.append({"role": "user", "content": f"Write a new entry matching this: {criteria}"})
    return messages


MUTATE_SYSTEM = (
    "You adapt one entry from a small personal block library into a variant, per a change "
    "request, keeping the exact same field shape (same headings/labels present, just "
    "updated content). Reply with ONLY this format, nothing else:\n\n"
    "===BODY===\n"
    "<the full updated Markdown entry, same shape as the original>\n"
    "===LABEL===\n"
    "<a short 1-3 word bracket label summarizing the change, lowercase, e.g. \"sheriff\">"
)


def mutate_prompt(original_body: str, criteria: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": MUTATE_SYSTEM},
        {"role": "user", "content": f"Original entry:\n{original_body}\n\nChange request: {criteria}"},
    ]


COMPOSE_SYSTEM = (
    "You plan a composed document from a small personal block library, given a "
    "natural-language request and a catalog of available blocks (id, tags, summary). For "
    "every part of the request, choose one of:\n"
    "  - use <block_id> — an existing block is a close match, reuse it as-is\n"
    "  - mutate <block_id> :: <criteria> — the closest available block is only a partial "
    "match; PREFER THIS over generate whenever any reasonable partial match exists, and "
    "give a specific one-line change request\n"
    "  - generate :: <criteria> — nothing in the catalog is even a partial fit\n\n"
    "Also decide the final order the pieces should appear in, per the request's own "
    "ordering logic if it states one.\n\n"
    "Reply with ONLY a JSON object of this shape, nothing else:\n"
    "{\n"
    '  "steps": [\n'
    '    {"order": 1, "action": "use", "block_id": "...", "criteria": null},\n'
    '    {"order": 2, "action": "mutate", "block_id": "...", "criteria": "..."},\n'
    '    {"order": 3, "action": "generate", "block_id": null, "criteria": "..."}\n'
    "  ]\n"
    "}"
)


def compose_prompt(request: str, catalog: list[dict], pinned_note: str) -> list[dict[str, str]]:
    catalog_text = "\n".join(
        f"- {b['id']} (tags: {', '.join(b['tags'])}): {b['summary']}" for b in catalog
    )
    user = f"Request: {request}\n\nAvailable blocks:\n{catalog_text or '(none)'}"
    if pinned_note:
        user += f"\n\n{pinned_note}"
    return [
        {"role": "system", "content": COMPOSE_SYSTEM},
        {"role": "user", "content": user},
    ]
