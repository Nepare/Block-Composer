"""Prompt templates. Every builder takes an optional `constraints` string (constraints.py),
appended to the system prompt when non-empty."""


def _with_constraints(system: str, constraints: str) -> str:
    if not constraints:
        return system
    return f"{system}\n\n## User constraints — follow these strictly\n{constraints}"


def _excerpts_block(relevant_excerpts: list[str] | None) -> str:
    if not relevant_excerpts:
        return ""
    bullets = "\n".join(f"- {e}" for e in relevant_excerpts)
    return (
        "\n\nGrounding — verbatim wording from the original request; apply only what concerns "
        f"this entry:\n{bullets}"
    )


GENERATE_SYSTEM = (
    "You write one new entry for a small personal block library. Match the exact field "
    "shape (same style of heading/name, description, and labeled or bulleted fields) shown "
    "in the reference example(s) you're given — same structure, new content matching the "
    "request. Reply with ONLY the Markdown entry, nothing else: no commentary, no code fences."
)


def generate_prompt(
    criteria: str,
    style_examples: list[str],
    constraints: str = "",
    relevant_excerpts: list[str] | None = None,
) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": _with_constraints(GENERATE_SYSTEM, constraints)}]
    for example in style_examples:
        messages.append(
            {"role": "user", "content": f"Example entry for style/shape reference:\n{example}"}
        )
    content = f"Write a new entry matching this: {criteria}" + _excerpts_block(relevant_excerpts)
    messages.append({"role": "user", "content": content})
    return messages


MUTATE_SYSTEM = (
    "You adapt one entry from a small personal block library into a variant, per a change "
    "request. Keep the same field shape (same headings/labels present) — but apply the "
    "change request across the WHOLE entry, not just its description. Go field by field: "
    "for each one, decide whether the change request affects it, and if it does, rewrite "
    "that field's content to fit — for AFFECTED fields, don't leave a field holding the original's "
    "stale details just because the change request didn't mention that field by name. A reply "
    "that only edits the description while every other field still describes the old, unchanged "
    "subject is only correct if the new description stays consistent with the unchanged fields.\n\n"
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


def mutate_prompt(
    original_body: str,
    criteria: str,
    constraints: str = "",
    relevant_excerpts: list[str] | None = None,
) -> list[dict[str, str]]:
    content = (
        f"Original entry:\n{original_body}\n\nChange request: {criteria}"
        + _excerpts_block(relevant_excerpts)
    )
    return [
        {"role": "system", "content": _with_constraints(MUTATE_SYSTEM, constraints)},
        {"role": "user", "content": content},
    ]


def _compose_system(allow_mutate: bool, allow_generate: bool) -> str:
    system = (
        "You plan a composed document from a small personal block library, given a "
        "natural-language request and a catalog of available blocks (id, tags, full content). For "
        "every part of the request, choose one of:\n"
        "  - use <block_id> — an existing block is a close match, reuse it as-is\n"
    )
    example_steps = ['{"order": 1, "action": "use", "block_id": "...", "criteria": null}']
    if allow_mutate:
        # the comparison to generate only makes sense when generate is itself an option
        if allow_generate:
            system += (
                "  - mutate <block_id> :: <criteria> — the closest available block is only a partial "
                "match; PREFER THIS over generate whenever any reasonable partial match exists, and "
                "give a specific one-line change request\n"
            )
        else:
            system += (
                "  - mutate <block_id> :: <criteria> — the closest available block is only a partial "
                "match; give a specific one-line change request\n"
            )
        example_steps.append(
            f'{{"order": {len(example_steps) + 1}, "action": "mutate", "block_id": "...", '
            '"criteria": "...", "relevant_excerpts": ["..."]}'
        )
    if allow_generate:
        system += "  - generate :: <criteria> — nothing in the catalog is even a partial fit\n"
        example_steps.append(
            f'{{"order": {len(example_steps) + 1}, "action": "generate", "block_id": null, '
            '"criteria": "...", "relevant_excerpts": ["..."]}'
        )
    steps_block = ",\n".join(f"    {step}" for step in example_steps)
    system += (
        "\nBlocks in the catalog that share the exact same `tags` list are the same underlying "
        "project — either literally the same catalog entry, or a project and an already-mutated "
        "variant of it. Treat any such group as one project: across the whole plan, claim at most "
        "one block from that group (via use or mutate), never two. If multiple parts of the "
        "request would otherwise need the same project, either mutate a different, still-unclaimed "
        "project instead, or generate, rather than claiming a project already used by an earlier "
        "step.\n\n"
    )
    if allow_mutate or allow_generate:
        system += (
            "For every mutate or generate step, first identify which specific part(s) of the request "
            "concretely apply to that particular piece — don't let unrelated parts of the request bleed "
            "into this step's criteria. When the relevant part of the request names a specific "
            "technology, quantity, emphasis, or tone, your criteria for that step MUST carry that "
            "specific detail forward explicitly, not fold it into a generic restatement. Never "
            "reference or pull in another piece's content into this step's criteria — describe only "
            "what this one step covers.\n\n"
            "Example — request: \"a project showcasing backend work, ideally involving Kafka, plus two "
            "more pieces.\" Too generic (WRONG) for that piece's criteria: \"a backend project\". "
            "Correctly detailed (RIGHT): \"a backend project that uses Kafka\".\n\n"
            "For mutate/generate steps, also include \"relevant_excerpts\": a list of zero or more "
            "verbatim quotes copied exactly from the original request that support this step's "
            "criteria — copy the exact wording, don't paraphrase. If the relevant detail is scattered "
            "across more than one place in the request, include more than one excerpt. If nothing in "
            "the request needs verbatim preservation for this piece, leave it as an empty list. Never "
            "include text about a different piece.\n\n"
        )
    system += (
        "Also decide the final order the pieces should appear in, per the request's own "
        "ordering logic if it states one.\n\n"
        "Reply with ONLY a JSON object of this shape, nothing else:\n"
        "{\n"
        '  "steps": [\n'
        f"{steps_block}\n"
        "  ]\n"
        "}"
    )
    return system


def compose_prompt(
    request: str,
    catalog: list[dict],
    constraints: str = "",
    required_count: int | None = None,
    allow_mutate: bool = True,
    allow_generate: bool = True,
) -> list[dict[str, str]]:
    catalog_text = "\n\n".join(
        f"### {b['id']} (tags: {', '.join(b['tags'])})\n{b['body']}" for b in catalog
    )
    user = f"Request: {request}\n\nAvailable blocks:\n{catalog_text or '(none)'}"
    if required_count is not None:
        user += f"\n\nYour plan's \"steps\" list MUST contain exactly {required_count} entries — no more, no fewer."
    return [
        {"role": "system", "content": _with_constraints(_compose_system(allow_mutate, allow_generate), constraints)},
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
        "library, so it can be narrowed down before planning. Reply with ONLY these four "
        "lines, nothing else — no commentary, no code fences. Any line can be left blank "
        "(just the label, nothing after the colon) if that category doesn't apply to the "
        "request:\n\n"
        f"ROLE: <{count_phrase} job title(s) or function(s) implied by the request, comma-separated>\n"
        f"ENVIRONMENT: <{count_phrase} CONCISE tools, technologies, programming languages, libraries, "
        "frameworks, IDEs, standards, protocols or resources implied by the request, comma-separated>\n"
        f"RESPONSIBILITIES: <{count_phrase} actions or achievements implied by the request, comma-separated>\n"
        f"DOMAIN: <{count_phrase} industry or subject-area words implied by the request, comma-separated>\n\n"
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


TARGET_COUNT_SYSTEM = (
    "<task>Determine whether the request explicitly states a specific number of "
    "projects/entries the composed document should contain.</task>\n"
    "<input_example_1>\"3 projects\"</input_example_1>\n"
    "<input_example_2>\"five examples\"</input_example_2>\n"
    "<input_example_3>something else completely</input_example_3>\n"
    "<output>A bare digit if it does, or the single word NONE if it does not. Nothing "
    "else -- no tags, no explanation.</output>\n"
    "<output_example_1>3</output_example_1>\n"
    "<output_example_2>5</output_example_2>\n"
    "<output_example_3>NONE</output_example_3>"
)


def target_count_prompt(request: str) -> list[dict[str, str]]:
    """Deliberately bare and constraints-free -- a mechanical classifier gains nothing from prose."""
    return [
        {"role": "system", "content": TARGET_COUNT_SYSTEM},
        {"role": "user", "content": f"<request>{request}</request>"},
    ]
