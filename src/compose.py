import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import constraints as constraints_module
import generate
import mutate
import naming
from blocks import Block, BlockStore
from config import Settings
from errors import BlockValidationError, LLMError
from llm.prompts import compose_prompt, result_name_prompt
from llm.router import get_client_and_model
from retrieval import extract_retrieval_signals, rank_blocks


@dataclass
class ComposeSlot:
    order: int
    action: str  # "use" | "mutate" | "generate" | "pinned_use" | "pinned_generate"
    block_id: str | None
    criteria: str | None
    resolved_id: str | None = None


def _catalog(blocks: list[Block]) -> list[dict]:
    """Pure formatter — narrowing (if any) already happened in _select_candidate_blocks."""
    return [{"id": b.id, "tags": b.tags, "body": b.body.strip()} for b in blocks]


def _select_candidate_blocks(
    request: str,
    store: BlockStore,
    exclude_ids: set[str],
    settings: Settings,
    progress: Callable[[str], None],
) -> list[Block]:
    """Below settings.compose.keyword_search_min_blocks, every block goes to the planner
    (today's behavior, zero extra calls). At or above it, extract categorized keywords
    from the request and narrow to the blocks that actually look relevant, instead of
    pasting the whole library into the planning prompt."""
    blocks = [b for b in store.all() if b.id not in exclude_ids]
    if len(blocks) < settings.compose.keyword_search_min_blocks:
        return blocks

    naming_client, naming_model = get_client_and_model(settings.models.naming, settings)
    compose_constraints = constraints_module.load(settings, "compose")
    progress("Extracting search keywords from request…")
    signals = extract_retrieval_signals(
        request,
        naming_client,
        naming_model,
        compose_constraints,
        min_per_category=settings.compose.keywords_per_category_min,
        max_per_category=settings.compose.keywords_per_category_max,
    )
    keywords = signals.keywords
    if keywords.is_empty():
        progress("No usable keywords extracted — searching the full library")
        return blocks

    progress(
        f"Keywords — role: {', '.join(keywords.role) or '—'}; "
        f"environment: {', '.join(keywords.environment) or '—'}; "
        f"responsibilities: {', '.join(keywords.responsibilities) or '—'}; "
        f"domain: {', '.join(keywords.domain) or '—'}"
    )
    top_n = signals.requested_count or settings.compose.keyword_search_top_n
    if signals.requested_count:
        progress(f"Request specifies {signals.requested_count} project(s) — narrowing to top {top_n}")
    narrowed = rank_blocks(blocks, keywords, top_n=top_n)
    progress(f"Narrowed to {len(narrowed)} of {len(blocks)} block(s) in the library")
    return narrowed


def _parse_plan_reply(reply: str) -> list[dict]:
    start = reply.find("{")
    end = reply.rfind("}")
    if start == -1 or end == -1:
        raise LLMError(f"No JSON object found in compose planner reply:\n{reply}")
    try:
        data = json.loads(reply[start : end + 1])
        return data["steps"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise LLMError(f"Compose planner returned an unparsable plan: {exc}\n---\n{reply}") from exc


def _plan_with_llm(
    request: str,
    store: BlockStore,
    pinned_ids: set[str],
    settings: Settings,
    model_spec: str | None,
    progress: Callable[[str], None],
) -> list[ComposeSlot]:
    client, model = get_client_and_model(model_spec or settings.models.compose, settings)
    candidate_blocks = _select_candidate_blocks(request, store, pinned_ids, settings, progress)
    catalog = _catalog(candidate_blocks)
    pinned_note = (
        f"Already pinned/handled by the user, do not repeat these: {', '.join(pinned_ids)}"
        if pinned_ids
        else ""
    )
    compose_constraints = constraints_module.load(settings, "compose")
    messages = compose_prompt(request, catalog, pinned_note, compose_constraints)
    progress(f"Planning against {len(catalog)} block(s) in the library…")
    reply = client.chat(messages, model, temperature=0.3, max_tokens=1200)
    try:
        steps = _parse_plan_reply(reply)
    except LLMError:
        # one retry -- openrouter/free can route to a different, better-behaved model
        progress("Planner reply wasn't valid — retrying once…")
        retry_messages = messages + [
            {"role": "assistant", "content": reply},
            {
                "role": "user",
                "content": "That reply wasn't a JSON object in the required shape. Reply "
                "again with ONLY the JSON object, no commentary, no code fences.",
            },
        ]
        reply = client.chat(retry_messages, model, temperature=0.3, max_tokens=1200)
        steps = _parse_plan_reply(reply)

    slots = []
    for i, step in enumerate(steps):
        slots.append(
            ComposeSlot(
                order=int(step.get("order", i + 1)),
                action=step["action"],
                block_id=step.get("block_id"),
                criteria=step.get("criteria"),
            )
        )
    return slots


def run_compose(
    request: str,
    *,
    settings: Settings,
    use_ids: list[str] | None = None,
    generate_criteria: list[str] | None = None,
    out_path: Path | None = None,
    model_spec: str | None = None,
    max_generate: int = 8,
    dry_run: bool = False,
    on_progress: Callable[[str], None] | None = None,
) -> tuple[list[ComposeSlot], Path | None]:
    """`on_progress`, if given, is called with a short status line at each meaningful step
    (plan built, before/after each mutate or generate) — compose can otherwise run for
    minutes with zero output, since it's a chain of several sequential LLM calls. Kept as
    a plain callback rather than importing Rich here, so this stays usable as a library and
    testable without a console."""
    progress = on_progress or (lambda _msg: None)
    store = BlockStore(settings.blocks_path)
    use_ids = use_ids or []
    generate_criteria = generate_criteria or []

    if not request.strip() and not use_ids and not generate_criteria:
        raise BlockValidationError(
            "compose needs a request, --use, or --generate — nothing to do with all three empty."
        )

    for uid in use_ids:
        store.load(uid)  # raises BlockNotFoundError early if a pinned id doesn't exist

    pinned_use_slots = [
        ComposeSlot(order=i + 1, action="pinned_use", block_id=uid, criteria=None, resolved_id=uid)
        for i, uid in enumerate(use_ids)
    ]
    pinned_generate_slots = [
        ComposeSlot(order=len(use_ids) + i + 1, action="pinned_generate", block_id=None, criteria=c)
        for i, c in enumerate(generate_criteria)
    ]
    pinned_slots = pinned_use_slots + pinned_generate_slots
    total_pinned = len(pinned_slots)

    planned_slots: list[ComposeSlot] = []
    if request.strip():
        planned_slots = _plan_with_llm(request, store, set(use_ids), settings, model_spec, progress)
        for i, slot in enumerate(planned_slots):
            slot.order = total_pinned + i + 1

    all_slots = pinned_slots + planned_slots

    generate_calls = sum(1 for s in all_slots if s.action in ("generate", "pinned_generate"))
    if generate_calls > max_generate:
        raise BlockValidationError(
            f"Compose plan needs {generate_calls} new blocks, more than --max-generate={max_generate}."
        )

    mutate_calls = sum(1 for s in all_slots if s.action == "mutate")
    use_calls = len(all_slots) - generate_calls - mutate_calls
    progress(
        f"Plan built: {len(all_slots)} step(s) — {use_calls} use, {mutate_calls} mutate, "
        f"{generate_calls} generate"
    )

    if dry_run:
        for slot in all_slots:
            if slot.action in ("use", "pinned_use"):
                slot.resolved_id = slot.block_id
        return all_slots, None

    total = len(all_slots)
    for i, slot in enumerate(sorted(all_slots, key=lambda s: s.order), start=1):
        if slot.action in ("use", "pinned_use"):
            slot.resolved_id = slot.block_id
            progress(f"[{i}/{total}] use -> {slot.block_id}")
        elif slot.action == "mutate":
            progress(f"[{i}/{total}] mutating {slot.block_id}…")
            _block, path = mutate.run_mutate(slot.block_id, slot.criteria or "", settings=settings)
            slot.resolved_id = path.stem
            progress(f"[{i}/{total}] mutated -> {slot.resolved_id}")
        elif slot.action in ("generate", "pinned_generate"):
            progress(f"[{i}/{total}] generating new block…")
            _block, decision, path = generate.run_generate(slot.criteria or "", settings=settings)
            slot.resolved_id = path.stem if path else decision.duplicate_of
            progress(f"[{i}/{total}] generated -> {slot.resolved_id}")

    ordered = sorted(all_slots, key=lambda s: s.order)
    bodies = [store.load(s.resolved_id).body.strip() for s in ordered if s.resolved_id]
    content = "\n\n---\n\n".join(bodies)

    progress("Naming result…")
    result_path = _save_result(content, settings, out_path)
    return ordered, result_path


def _generate_result_name(content: str, settings: Settings) -> str:
    """A short, descriptive name for the composed result, synthesized from the *whole*
    composed content — not derived from the raw request text (long, conversational, a
    poor filename) and not routed to the cheap naming model: unlike naming's usual job
    (spot the difference between two short blocks), this has to actually read and
    summarize a multi-block document, which a small local model tends to do lazily (e.g.
    just echoing one source block's own heading back). Uses the same tier as compose's
    planning call. E.g. "mining_town", "vulkan_plugin_specialist", not a slug of the NL
    request or a copy of one ingredient block's name."""
    client, model = get_client_and_model(settings.models.compose, settings)
    compose_constraints = constraints_module.load(settings, "compose")
    reply = client.chat(result_name_prompt(content, compose_constraints), model, temperature=0.2, max_tokens=20)
    lines = [line.strip() for line in reply.strip().splitlines() if line.strip()]
    name = lines[0].strip("[]").strip() if lines else ""
    if not name or len(name.split()) > 6:
        return "result"
    return name


def _save_result(content: str, settings: Settings, out_path: Path | None) -> Path:
    """Goes through the same naming.decide() flow as blocks: brand-new name -> saved
    plainly; a same-slug result already exists -> exact-match reuse or a _mut_ variant."""
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8")
        return out_path

    results_dir = settings.results_path
    results_dir.mkdir(parents=True, exist_ok=True)

    title = _generate_result_name(content, settings)
    base_slug = naming.slugify(title)[:60].rstrip("_") or "result"
    candidate = naming.Candidate(name=title, full_text=content)

    existing = [
        (p.stem, naming.Candidate(name=title, full_text=p.read_text(encoding="utf-8")))
        for p in results_dir.glob(f"{base_slug}*.md")
        if p.stem == base_slug or p.stem.startswith(f"{base_slug}_mut_")
    ]

    naming_client, naming_model = get_client_and_model(settings.models.naming, settings)
    naming_constraints = constraints_module.load(settings, "naming")
    decision = naming.decide(
        candidate,
        existing,
        exists=lambda stem: (results_dir / f"{stem}.md").exists(),
        naming_client=naming_client,
        naming_model=naming_model,
        constraints=naming_constraints,
    )

    if decision.action == "skip_duplicate":
        return results_dir / f"{decision.duplicate_of}.md"

    path = results_dir / f"{decision.stem}.md"
    path.write_text(content, encoding="utf-8")
    return path
