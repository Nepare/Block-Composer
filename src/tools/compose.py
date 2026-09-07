import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from core import constraints as constraints_module
from core import naming
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


@dataclass
class ComposeOutcome:
    slots: list[ComposeSlot]
    result_path: Path | None
    result_id: str | None
    name: str | None
    content: str | None
    cancelled: bool


def _catalog(blocks: list[Block]) -> list[dict]:
    """Pure formatter — narrowing (if any) already happened in _select_candidate_blocks."""
    return [{"id": b.id, "tags": b.tags, "body": b.body.strip()} for b in blocks]


def _next_unused_candidate(candidates: list[Block], claimed_ids: set[str]) -> str | None:
    for block in candidates:
        if block.id not in claimed_ids:
            return block.id
    return None


def _select_candidate_blocks(
    request: str,
    store: BlockStorage,
    exclude_ids: set[str],
    settings: Settings,
    progress: ProgressSink,
    restrict_generate: bool = False,
    required_count: int | None = None,
    pool_override: list[Block] | None = None,
) -> list[Block]:
    """Narrows the block library to the blocks matching keywords extracted from the request."""
    blocks = [b for b in (pool_override if pool_override is not None else store.all()) if b.id not in exclude_ids]

    top_n = settings.behavior.compose.keyword_search_top_n
    unmatched_reserve = settings.behavior.compose.keyword_search_unmatched_reserve
    effective_threshold = max(top_n, required_count or 0)
    if len(blocks) <= effective_threshold:
        progress(
            ProgressEvent(
                kind="narrowing_skipped",
                message=f"All {len(blocks)} candidate(s) already fit within the window — skipping relevance narrowing",
            )
        )
        return blocks

    keywords_client, keywords_model = get_client_and_model(
        settings.llm.models.keywords, settings, on_progress=progress
    )
    keywords_constraints = constraints_module.load(settings, "keywords")
    progress(ProgressEvent(kind="keyword_extraction_start", message="Extracting search keywords from request…"))
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
                kind="keyword_extraction_done", message="No usable keywords extracted — searching the full library"
            )
        )
        return blocks

    progress(
        ProgressEvent(
            kind="keyword_extraction_done",
            message=(
                f"Keywords — role: {', '.join(keywords.role) or '—'}; "
                f"environment: {', '.join(keywords.environment) or '—'}; "
                f"responsibilities: {', '.join(keywords.responsibilities) or '—'}; "
                f"domain: {', '.join(keywords.domain) or '—'}"
            ),
        )
    )
    if restrict_generate and required_count is not None and top_n < required_count:
        source_desc = "the designated set" if pool_override is not None else "the library"
        progress(
            ProgressEvent(
                kind="warning",
                message=(
                    f"--restrict-generate: narrowing window ({top_n}) is smaller than the "
                    f"{required_count} project(s) still needed from {source_desc} — widening to {required_count}."
                ),
            )
        )
        top_n = required_count
        unmatched_reserve = required_count
    narrowed = rank_blocks(blocks, keywords, top_n=top_n, unmatched_reserve=unmatched_reserve)
    progress(
        ProgressEvent(
            kind="narrowing_done", message=f"Narrowed to {len(narrowed)} of {len(blocks)} block(s) in the library"
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
    restrict_generate: bool = False,
    restrict_mutate: bool = False,
    pool_override: list[Block] | None = None,
) -> list[ComposeSlot]:
    client, model = get_client_and_model(model_spec or settings.llm.models.compose, settings, on_progress=progress)
    candidate_blocks = _select_candidate_blocks(
        request,
        store,
        pinned_ids,
        settings,
        progress,
        restrict_generate=restrict_generate,
        required_count=required_count,
        pool_override=pool_override,
    )
    catalog = _catalog(candidate_blocks)
    pinned_note = (
        f"Already pinned/handled by the user, do not repeat these: {', '.join(pinned_ids)}"
        if pinned_ids
        else ""
    )
    compose_constraints = constraints_module.load(settings, "compose")
    messages = compose_prompt(
        request,
        catalog,
        pinned_note,
        compose_constraints,
        required_count=required_count,
        allow_mutate=not restrict_mutate,
        allow_generate=not restrict_generate,
    )
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

    count_mismatch = required_count is not None and len(slots) != required_count
    illegal_slots = [
        s
        for s in slots
        if (restrict_generate and s.action == "generate") or (restrict_mutate and s.action == "mutate")
    ]

    if count_mismatch or illegal_slots:
        problems = []
        if count_mismatch:
            problems.append(f"had {len(slots)} step(s), but exactly {required_count} are required")
        if illegal_slots:
            bad_actions = sorted({s.action for s in illegal_slots})
            problems.append(f"used a currently-disallowed action ({', '.join(bad_actions)})")
        progress(
            ProgressEvent(
                kind="plan_retry",
                message=f"Plan {' and '.join(problems)} — retrying once…",
            )
        )
        retry_messages = messages + [
            {"role": "assistant", "content": reply},
            {
                "role": "user",
                "content": f"Your plan {' and '.join(problems)}. Reply again with the corrected "
                "JSON object only, no commentary.",
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

    claimed_ids = set()
    corrected_slots = []
    for s in slots:
        if restrict_generate and s.action == "generate":
            new_id = _next_unused_candidate(candidate_blocks, claimed_ids)
            if new_id is not None:
                claimed_ids.add(new_id)
                s = ComposeSlot(order=s.order, action="use", block_id=new_id, criteria=None)
        elif restrict_mutate and s.action == "mutate":
            if s.block_id and s.block_id not in claimed_ids:
                claimed_ids.add(s.block_id)
                s = ComposeSlot(order=s.order, action="use", block_id=s.block_id, criteria=None)
            else:
                new_id = _next_unused_candidate(candidate_blocks, claimed_ids)
                if new_id is not None:
                    claimed_ids.add(new_id)
                    s = ComposeSlot(order=s.order, action="use", block_id=new_id, criteria=None)
        elif s.block_id:
            claimed_ids.add(s.block_id)
        corrected_slots.append(s)
    slots = corrected_slots

    if required_count is not None and len(slots) != required_count:
        ordered_slots = sorted(slots, key=lambda s: s.order)
        if len(ordered_slots) > required_count:
            slots = ordered_slots[:required_count]
        else:
            next_order = (max((s.order for s in ordered_slots), default=0)) + 1
            shortfall = required_count - len(ordered_slots)
            if restrict_generate:
                claimed_ids = {s.block_id for s in ordered_slots if s.block_id}
                padding = []
                for i in range(shortfall):
                    new_id = _next_unused_candidate(candidate_blocks, claimed_ids)
                    if new_id is None:
                        break
                    claimed_ids.add(new_id)
                    padding.append(ComposeSlot(order=next_order + i, action="use", block_id=new_id, criteria=None))
            else:
                padding = [
                    ComposeSlot(order=next_order + i, action="generate", block_id=None, criteria=request)
                    for i in range(shortfall)
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
    name: str | None = None,
    max_generate: int = 8,
    dry_run: bool = False,
    preserve: bool = False,
    on_progress: ProgressSink | None = None,
    cancel_check: Callable[[], bool] | None = None,
    restrict_generate: bool = False,
    restrict_mutate: bool = False,
    from_block_ids: list[str] | None = None,
) -> ComposeOutcome:
    """`cancel_check`, if given, is polled between slots — a True stops execution before the
    next slot, keeping any blocks/mutations already produced but skipping the final result."""
    explicit_base = naming.validate_explicit_name(name) if name is not None else None
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

    if restrict_generate and generate_criteria:
        raise BlockValidationError(
            "--restrict-generate cannot be combined with --generate (a pinned new-block "
            "request) — these directly contradict each other."
        )

    for uid in use_ids:
        store.load(uid)  # raises BlockNotFoundError early if a pinned id doesn't exist

    resolved_pool: list[Block] | None = None
    if from_block_ids is not None:
        if len(from_block_ids) == 0:
            raise BlockValidationError("--from-blocks: at least one block must be designated.")
        deduped_from_block_ids = list(dict.fromkeys(from_block_ids))
        resolved_pool = [store.load(bid) for bid in deduped_from_block_ids]
        missing_from_set = [uid for uid in use_ids if uid not in deduped_from_block_ids]
        if missing_from_set:
            raise BlockValidationError(
                f"--use id(s) not in --from-blocks: {', '.join(missing_from_set)} — every "
                "guaranteed inclusion must be part of the designated set."
            )
    effective_restrict_generate = restrict_generate or (from_block_ids is not None)
    pool_size = len(resolved_pool) if from_block_ids is not None else len(store.all())

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

    if effective_restrict_generate and target_count is not None and target_count > pool_size:
        source_desc = "the designated set" if from_block_ids is not None else "the library"
        raise BlockValidationError(
            f"--restrict-generate: requested {target_count} project(s), but {source_desc} only "
            f"has {pool_size} block(s) available."
        )

    required_planned: int | None = None
    if target_count is not None:
        required_planned = max(target_count - total_pinned, 0)

    planned_slots: list[ComposeSlot] = []
    if target_count is not None:
        if required_planned > 0:
            planned_slots = _plan_with_llm(
                request,
                store,
                set(use_ids),
                settings,
                model_spec,
                progress,
                required_count=required_planned,
                restrict_generate=effective_restrict_generate,
                restrict_mutate=restrict_mutate,
                pool_override=resolved_pool,
            )
    elif request.strip():
        planned_slots = _plan_with_llm(
            request,
            store,
            set(use_ids),
            settings,
            model_spec,
            progress,
            restrict_generate=effective_restrict_generate,
            restrict_mutate=restrict_mutate,
            pool_override=resolved_pool,
        )
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
    progress(
        ProgressEvent(
            kind="plan",
            message="Composition plan finalized.",
            data={
                "steps": [
                    {"order": s.order, "action": s.action, "block_id": s.block_id, "criteria": s.criteria}
                    for s in sorted(all_slots, key=lambda s: s.order)
                ]
            },
        )
    )

    if dry_run:
        for slot in all_slots:
            if slot.action in ("use", "pinned_use"):
                slot.resolved_id = slot.block_id
        return ComposeOutcome(
            slots=all_slots, result_path=None, result_id=None, name=None, content=None, cancelled=False
        )

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
            return ComposeOutcome(
                slots=sorted(all_slots, key=lambda s: s.order),
                result_path=None,
                result_id=None,
                name=None,
                content=None,
                cancelled=True,
            )

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
                return ComposeOutcome(
                    slots=sorted(all_slots, key=lambda s: s.order),
                    result_path=None,
                    result_id=None,
                    name=None,
                    content=None,
                    cancelled=True,
                )
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
                return ComposeOutcome(
                    slots=sorted(all_slots, key=lambda s: s.order),
                    result_path=None,
                    result_id=None,
                    name=None,
                    content=None,
                    cancelled=True,
                )
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
    result_id, name, result_path = _save_result(
        content,
        settings,
        out_path,
        progress,
        request=request,
        use_ids=use_ids,
        generate_criteria=generate_criteria,
        slots=ordered,
        name=name,
        explicit_base=explicit_base,
        preserve=preserve,
    )
    return ComposeOutcome(
        slots=ordered, result_path=result_path, result_id=result_id, name=name, content=content, cancelled=False
    )


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
    name: str | None = None,
    explicit_base: str | None = None,
    preserve: bool = False,
) -> tuple[str | None, str | None, Path | None]:
    """`out_path`, if given, bypasses ResultStorage and writes exactly there instead."""
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8")
        return None, None, out_path

    title = name if explicit_base is not None else _generate_result_name(content, settings, progress)
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
        preserved=preserve,
    )

    if explicit_base is not None:
        decision, stem = result_store.save_with_dedup(result, explicit_base=explicit_base)
    else:
        naming_client, naming_model = get_client_and_model(
            settings.llm.models.naming, settings, on_progress=progress
        )
        naming_constraints = constraints_module.load(settings, "naming")
        decision, stem = result_store.save_with_dedup(
            result,
            naming_client=naming_client,
            naming_model=naming_model,
            naming_constraints=naming_constraints,
        )
    final_stem = stem or decision.duplicate_of
    return final_stem, title, result_store.path_for(final_stem)
