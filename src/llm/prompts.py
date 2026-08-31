"""Prompt templates. Every LLM interaction in cvdocs works on flat Markdown or plain text
in and out — never nested JSON for content — the one exception being compose's own plan,
which legitimately needs structured multi-field output to describe *which* action to take
per slot, distinct from the document content itself.

Every builder here takes an optional `constraints` string (see constraints.py) — the
content of a user-editable CLAUDE.md/AGENTS.md-style file for that tool, appended to the
system prompt when non-empty. This is where a user says what a tool should NOT do."""


def _with_constraints(system: str, constraints: str) -> str:
    if not constraints:
        return system
    return f"{system}\n\n## User constraints — follow these strictly\n{constraints}"


GENERATE_SYSTEM = (
    "You write one new entry for a small personal block library. Match the exact field "
    "shape (same style of heading/name, description, and labeled or bulleted fields) shown "
    "in the reference example(s) you're given — same structure, new content matching the "
    "request. Reply with ONLY the Markdown entry, nothing else: no commentary, no code fences."
)


def generate_prompt(criteria: str, style_examples: list[str], constraints: str = "") -> list[dict[str, str]]:
    messages = [{"role": "system", "content": _with_constraints(GENERATE_SYSTEM, constraints)}]
    for example in style_examples:
        messages.append(
            {"role": "user", "content": f"Example entry for style/shape reference:\n{example}"}
        )
    messages.append({"role": "user", "content": f"Write a new entry matching this: {criteria}"})
    return messages


MUTATE_SYSTEM = (
    "You adapt one entry from a small personal block library into a variant, per a change "
    "request. Keep the same field shape (same headings/labels present) — but apply the "
    "change request across the WHOLE entry, not just its description. Go field by field: "
    "for each one, decide whether the change request affects it, and if it does, rewrite "
    "that field's content to fit — don't leave a field holding the original's stale "
    "details just because the change request didn't mention that field by name. A reply "
    "that only edits the description while every other field still describes the old, "
    "unchanged subject is wrong and incomplete.\n\n"
    "Keep the entry's name in the heading unchanged unless the change request turns it "
    "into a genuinely different subject rather than a variant of the original — in that "
    "case give it a real new name instead of keeping the old one. If you do rename it, "
    "make sure the rest of the entry was actually rewritten to match the new subject too, "
    "not left describing the old one under a new title.\n\n"
    "Reply with ONLY this format, nothing else:\n\n"
    "===BODY===\n"
    "<the full updated Markdown entry, same shape as the original>\n"
    "===LABEL===\n"
    "<if the name stayed the same: a short 1-3 word label summarizing the change, "
    "lowercase. If you gave it a new name instead, just repeat that new name here.>"
)


def mutate_prompt(original_body: str, criteria: str, constraints: str = "") -> list[dict[str, str]]:
    return [
        {"role": "system", "content": _with_constraints(MUTATE_SYSTEM, constraints)},
        {"role": "user", "content": f"Original entry:\n{original_body}\n\nChange request: {criteria}"},
    ]


COMPOSE_SYSTEM = (
    "You plan a composed document from a small personal block library, given a "
    "natural-language request and a catalog of available blocks (id, tags, full content). For "
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


def compose_prompt(
    request: str, catalog: list[dict], pinned_note: str, constraints: str = ""
) -> list[dict[str, str]]:
    catalog_text = "\n\n".join(
        f"### {b['id']} (tags: {', '.join(b['tags'])})\n{b['body']}" for b in catalog
    )
    user = f"Request: {request}\n\nAvailable blocks:\n{catalog_text or '(none)'}"
    if pinned_note:
        user += f"\n\n{pinned_note}"
    return [
        {"role": "system", "content": _with_constraints(COMPOSE_SYSTEM, constraints)},
        {"role": "user", "content": user},
    ]


RESULT_NAME_SYSTEM = (
    "You name a file for a composed document, based on its actual content. Reply with "
    "ONLY a short, descriptive name, 2-5 words, lowercase, words separated by underscores "
    "(e.g. 'mining_town', 'vulkan_plugin_specialist', "
    "'vibecoding_course_table_of_contents'). Do not explain yourself, do not add a file "
    "extension."
)


def result_name_prompt(content: str, constraints: str = "") -> list[dict[str, str]]:
    return [
        {"role": "system", "content": _with_constraints(RESULT_NAME_SYSTEM, constraints)},
        {"role": "user", "content": f"Composed document:\n{content}\n\nName for this file:"},
    ]


def _keyword_extraction_system(min_per_category: int, max_per_category: int) -> str:
    count_phrase = (
        f"{min_per_category}-{max_per_category}" if min_per_category > 0 else f"up to {max_per_category}"
    )
    return (
        "You turn a natural-language request into search keywords for a personal block "
        "library, so it can be narrowed down before planning. Reply with ONLY these five "
        "lines, nothing else — no commentary, no code fences. Any line can be left blank "
        "(just the label, nothing after the colon) if that category doesn't apply to the "
        "request:\n\n"
        f"ROLE: <{count_phrase} job title(s) or function(s) implied by the request, "
        "comma-separated>\n"
        f"ENVIRONMENT: <{count_phrase} tools, technologies, or resources implied by the "
        "request, comma-separated>\n"
        f"RESPONSIBILITIES: <{count_phrase} actions or achievements implied by the "
        "request, comma-separated>\n"
        f"DOMAIN: <{count_phrase} industry or subject-area words implied by the request, "
        "comma-separated>\n"
        "PROJECT_COUNT: <if the request explicitly asks for a specific number of "
        "projects/entries, e.g. \"3 projects\" or \"five examples\", that number; otherwise "
        "leave blank>\n\n"
        "Keywords should be plain words or short phrases actually implied by the request, "
        "not invented specifics. Do not explain your choices."
    )


def keyword_extraction_prompt(
    request: str,
    constraints: str = "",
    *,
    min_per_category: int = 0,
    max_per_category: int = 4,
) -> list[dict[str, str]]:
    system = _keyword_extraction_system(min_per_category, max_per_category)
    return [
        {"role": "system", "content": _with_constraints(system, constraints)},
        {"role": "user", "content": f"Request: {request}"},
    ]
