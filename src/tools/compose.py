import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from core import constraints as constraints_module
from tools import generate
from tools import mutate
from models.blocks import Block
from core.config import Settings
from core.errors import BlockValidationError, LLMError, OperationCancelled
from llm.prompts import compose_prompt, result_name_prompt
from llm.router import get_client_and_model
from core.progress import ProgressEvent, ProgressSink
from tools.retrieval import extract_retrieval_signals, extract_target_count, rank_blocks
from storage.base import BlockStorage, Result
from storage.router import get_block_storage, get_result_storage


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
    store: BlockStorage,
    exclude_ids: set[str],
    settings: Settings,
    progress: ProgressSink,
) -> list[Block]:
    """Narrows the block library to the blocks matching keywords extracted from the request."""
    blocks = [b for b in store.all() if b.id not in exclude_ids]

    keywords_client, keywords_model = get_client_and_model(
        settings.llm.models.keywords, settings, on_progress=progress
    )
    keywords_constraints = constraints_module.load(settings, "keywords")
    progress(ProgressEvent(kind="keyword_extraction", message="Extracting search keywords from request…"))
    signals = extract_retrieval_signals(
        request,
        keywords_client,
        keywords_model,
        keywords_constraints,
        min_per_category=settings.behavior.compose.keywords_per_category_min,
        max_per_category=settings.behavior.compose.keywords_per_category_max,
    )
    keywords = signals.keywords
    if keywords.is_empty():
        progress(
            ProgressEvent(
                kind="keyword_extraction", message="No usable keywords extracted — searching the full library"
            )
        )
        return blocks

    progress(
        ProgressEvent(
            kind="keyword_extraction",
            message=(
                f"Keywords — role: {', '.join(keywords.role) or '—'}; "
                f"environment: {', '.join(keywords.environment) or '—'}; "
                f"responsibilities: {', '.join(keywords.responsibilities) or '—'}; "
                f"domain: {', '.join(keywords.domain) or '—'}"
            ),
        )
    )
    top_n = settings.behavior.compose.keyword_search_top_n
    narrowed = rank_blocks(
        blocks, keywords, top_n=top_n, unmatched_reserve=settings.behavior.compose.keyword_search_unmatched_reserve
    )
    progress(
        ProgressEvent(
            kind="narrowing", message=f"Narrowed to {len(narrowed)} of {len(blocks)} block(s) in the library"
        )
    )
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
    store: BlockStorage,
    pinned_ids: set[str],
    settings: Settings,
    model_spec: str | None,
    progress: ProgressSink,
    *,
    required_count: int | None = None,
) -> list[ComposeSlot]:
    client, model = get_client_and_model(model_spec or settings.llm.models.compose, settings, on_progress=progress)
    candidate_blocks = _select_candidate_blocks(request, store, pinned_ids, settings, progress)
    catalog = _catalog(candidate_blocks)
    pinned_note = (
        f"Already pinned/handled by the user, do not repeat these: {', '.join(pinned_ids)}"
        if pinned_ids
        else ""
    )
    compose_constraints = constraints_module.load(settings, "compose")
    messages = compose_prompt(request, catalog, pinned_note, compose_constraints, required_count=required_count)
    progress(ProgressEvent(kind="plan_start", message=f"Planning against {len(catalog)} block(s) in the library…"))
    reply = client.chat(messages, model, temperature=0.3, max_tokens=1200)
    try:
        steps = _parse_plan_reply(reply)
    except LLMError:
        # one retry -- openrouter/free can route to a different, better-behaved model
        progress(ProgressEvent(kind="plan_retry", message="Planner reply wasn't valid — retrying once…"))
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

    if required_count is not None and len(slots) != required_count:
        progress(
            ProgressEvent(
                kind="plan_retry",
                message=f"Plan had {len(slots)} step(s), {required_count} required — retrying once…",
            )
        )
        retry_messages = messages + [
            {"role": "assistant", "content": reply},
            {
                "role": "user",
                "content": f"Your plan had {len(slots)} steps, but exactly {required_count} are "
                "required. Reply again with the corrected JSON object only, no commentary.",
            },
        ]
        retry_reply = client.chat(retry_messages, model, temperature=0.3, max_tokens=1200)
        try:
            retry_steps = _parse_plan_reply(retry_reply)
            slots = [
                ComposeSlot(
                    order=int(step.get("order", i + 1)),
                    action=step["action"],
                    block_id=step.get("block_id"),
                    criteria=step.get("criteria"),
                )
                for i, step in enumerate(retry_steps)
            ]
        except LLMError:
            pass  # keep whatever `slots` already held from the last successfully-parsed attempt

    if required_count is not None and len(slots) != required_count:
        ordered_slots = sorted(slots, key=lambda s: s.order)
        if len(ordered_slots) > required_count:
            slots = ordered_slots[:required_count]
        else:
            next_order = (max((s.order for s in ordered_slots), default=0)) + 1
            padding = [
                ComposeSlot(order=next_order + i, action="generate", block_id=None, criteria=request)
                for i in range(required_count - len(ordered_slots))
            ]
            slots = ordered_slots + padding

    return slots


def run_compose(
    request: str,
    *,
    settings: Settings,
    use_ids: list[str] | None = None,
    generate_criteria: list[str] | None = None,
    count: int | None = None,
    out_path: Path | None = None,
    model_spec: str | None = None,
    max_generate: int = 8,
    dry_run: bool = False,
    on_progress: ProgressSink | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> tuple[list[ComposeSlot], Path | None]:
    """`cancel_check`, if given, is polled between slots — a True stops execution before the
    next slot, keeping any blocks/mutations already produced but skipping the final result."""
    progress = on_progress or (lambda _event: None)
    store = get_block_storage(settings)
    use_ids = use_ids or []
    generate_criteria = generate_criteria or []

    if not request.strip() and not use_ids and not generate_criteria:
        raise BlockValidationError(
            "compose needs a request, --use, or --generate — nothing to do with all three empty."
        )

    if count is not None and count <= 0:
        raise BlockValidationError(f"--count must be a positive integer, got {count}.")

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

    target_count: int | None = None
    if count is not None:
        target_count = count
    elif request.strip():
        naming_client, naming_model = get_client_and_model(settings.llm.models.naming, settings, on_progress=progress)
        target_count = extract_target_count(request, naming_client, naming_model)

    required_planned: int | None = None
    if target_count is not None:
        required_planned = max(target_count - total_pinned, 0)

    planned_slots: list[ComposeSlot] = []
    if target_count is not None:
        if required_planned > 0:
            planned_slots = _plan_with_llm(
                request, store, set(use_ids), settings, model_spec, progress, required_count=required_planned
            )
    elif request.strip():
        planned_slots = _plan_with_llm(request, store, set(use_ids), settings, model_spec, progress)
    if planned_slots:
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
        ProgressEvent(
            kind="plan_done",
            message=(
                f"Plan built: {len(all_slots)} step(s) — {use_calls} use, {mutate_calls} mutate, "
                f"{generate_calls} generate"
            ),
        )
    )

    if dry_run:
        for slot in all_slots:
            if slot.action in ("use", "pinned_use"):
                slot.resolved_id = slot.block_id
        return all_slots, None

    total = len(all_slots)
    for i, slot in enumerate(sorted(all_slots, key=lambda s: s.order), start=1):
        if cancel_check and cancel_check():
            progress(
                ProgressEvent(
                    kind="cancelled",
                    message=f"Cancelled after {i - 1}/{total} step(s) — earlier results kept.",
                    step=i - 1,
                    total=total,
                )
            )
            return sorted(all_slots, key=lambda s: s.order), None

        if slot.action in ("use", "pinned_use"):
            slot.resolved_id = slot.block_id
            progress(ProgressEvent(kind="use", message=f"[{i}/{total}] use -> {slot.block_id}", step=i, total=total))
        elif slot.action == "mutate":
            progress(
                ProgressEvent(
                    kind="mutate_start", message=f"[{i}/{total}] mutating {slot.block_id}…", step=i, total=total
                )
            )
            try:
                _block, stem = mutate.run_mutate(
                    slot.block_id,
                    slot.criteria or "",
                    settings=settings,
                    on_progress=progress,
                    cancel_check=cancel_check,
                )
            except OperationCancelled:
                progress(
                    ProgressEvent(
                        kind="cancelled",
                        message=f"Cancelled during step {i}/{total} — earlier results kept.",
                        step=i - 1,
                        total=total,
                    )
                )
                return sorted(all_slots, key=lambda s: s.order), None
            slot.resolved_id = stem
            progress(
                ProgressEvent(
                    kind="mutate_done", message=f"[{i}/{total}] mutated -> {slot.resolved_id}", step=i, total=total
                )
            )
        elif slot.action in ("generate", "pinned_generate"):
            progress(
                ProgressEvent(kind="generate_start", message=f"[{i}/{total}] generating new block…", step=i, total=total)
            )
            try:
                _block, decision, stem = generate.run_generate(
                    slot.criteria or "",
                    settings=settings,
                    on_progress=progress,
                    cancel_check=cancel_check,
                )
            except OperationCancelled:
                progress(
                    ProgressEvent(
                        kind="cancelled",
                        message=f"Cancelled during step {i}/{total} — earlier results kept.",
                        step=i - 1,
                        total=total,
                    )
                )
                return sorted(all_slots, key=lambda s: s.order), None
            slot.resolved_id = stem or decision.duplicate_of
            progress(
                ProgressEvent(
                    kind="generate_done",
                    message=f"[{i}/{total}] generated -> {slot.resolved_id}",
                    step=i,
                    total=total,
                )
            )

    ordered = sorted(all_slots, key=lambda s: s.order)
    bodies = [store.load(s.resolved_id).body.strip() for s in ordered if s.resolved_id]
    content = "\n\n---\n\n".join(bodies)

    progress(ProgressEvent(kind="naming", message="Naming result…"))
    result_path = _save_result(
        content,
        settings,
        out_path,
        progress,
        request=request,
        use_ids=use_ids,
        generate_criteria=generate_criteria,
        slots=ordered,
    )
    return ordered, result_path


def _generate_result_name(content: str, settings: Settings, progress: ProgressSink) -> str:
    """Names the composed result from its full content, via the compose model tier rather
    than the cheap naming tier — summarizing a multi-block document needs more than the
    naming model's usual short two-block comparison."""
    client, model = get_client_and_model(settings.llm.models.compose, settings, on_progress=progress)
    compose_constraints = constraints_module.load(settings, "compose")
    reply = client.chat(result_name_prompt(content, compose_constraints), model, temperature=0.2, max_tokens=20)
    lines = [line.strip() for line in reply.strip().splitlines() if line.strip()]
    name = lines[0].strip("[]").strip() if lines else ""
    if not name or len(name.split()) > 6:
        return "result"
    return name


def _save_result(
    content: str,
    settings: Settings,
    out_path: Path | None,
    progress: ProgressSink,
    *,
    request: str,
    use_ids: list[str],
    generate_criteria: list[str],
    slots: list[ComposeSlot],
) -> Path:
    """`out_path`, if given, bypasses ResultStorage and writes exactly there instead."""
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8")
        return out_path

    title = _generate_result_name(content, settings, progress)
    result_store = get_result_storage(settings)
    result = Result(
        content=content,
        name=title,
        request=request,
        use_ids=list(use_ids),
        generate_criteria=list(generate_criteria),
        slots=[
            {
                "order": s.order,
                "action": s.action,
                "block_id": s.block_id,
                "criteria": s.criteria,
                "resolved_id": s.resolved_id,
            }
            for s in slots
        ],
    )

    naming_client, naming_model = get_client_and_model(settings.llm.models.naming, settings, on_progress=progress)
    naming_constraints = constraints_module.load(settings, "naming")
    decision, stem = result_store.save_with_dedup(
        result,
        naming_client=naming_client,
        naming_model=naming_model,
        naming_constraints=naming_constraints,
    )
    final_stem = stem or decision.duplicate_of
    return result_store.path_for(final_stem)
