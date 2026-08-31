import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import generate
import mutate
import naming
from blocks import BlockStore
from config import Settings
from errors import BlockValidationError, LLMError
from llm.prompts import compose_prompt
from llm.router import get_client_and_model


@dataclass
class ComposeSlot:
    order: int
    action: str  # "use" | "mutate" | "generate" | "pinned_use" | "pinned_generate"
    block_id: str | None
    criteria: str | None
    resolved_id: str | None = None


def _catalog(store: BlockStore, exclude_ids: set[str]) -> list[dict]:
    return [
        {"id": b.id, "tags": b.tags, "summary": b.summary or b.name}
        for b in store.all()
        if b.id not in exclude_ids
    ]


def _extract_json(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise LLMError(f"No JSON object found in compose planner reply:\n{text}")
    return text[start : end + 1]


def _plan_with_llm(
    request: str,
    store: BlockStore,
    pinned_ids: set[str],
    settings: Settings,
    model_spec: str | None,
) -> list[ComposeSlot]:
    client, model = get_client_and_model(model_spec or settings.models.compose, settings)
    catalog = _catalog(store, pinned_ids)
    pinned_note = (
        f"Already pinned/handled by the user, do not repeat these: {', '.join(pinned_ids)}"
        if pinned_ids
        else ""
    )
    messages = compose_prompt(request, catalog, pinned_note)
    reply = client.chat(messages, model, temperature=0.3, max_tokens=800)
    try:
        data = json.loads(_extract_json(reply))
        steps = data["steps"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise LLMError(f"Compose planner returned an unparsable plan: {exc}\n---\n{reply}") from exc

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
) -> tuple[list[ComposeSlot], Path | None]:
    store = BlockStore(settings.blocks_path)
    use_ids = use_ids or []
    generate_criteria = generate_criteria or []

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
        planned_slots = _plan_with_llm(request, store, set(use_ids), settings, model_spec)
        for i, slot in enumerate(planned_slots):
            slot.order = total_pinned + i + 1

    all_slots = pinned_slots + planned_slots

    generate_calls = sum(1 for s in all_slots if s.action in ("generate", "pinned_generate"))
    if generate_calls > max_generate:
        raise BlockValidationError(
            f"Compose plan needs {generate_calls} new blocks, more than --max-generate={max_generate}."
        )

    if dry_run:
        for slot in all_slots:
            if slot.action in ("use", "pinned_use"):
                slot.resolved_id = slot.block_id
        return all_slots, None

    for slot in all_slots:
        if slot.action in ("use", "pinned_use"):
            slot.resolved_id = slot.block_id
        elif slot.action == "mutate":
            _block, path = mutate.run_mutate(slot.block_id, slot.criteria or "", settings=settings)
            slot.resolved_id = path.stem
        elif slot.action in ("generate", "pinned_generate"):
            _block, decision, path = generate.run_generate(slot.criteria or "", settings=settings)
            slot.resolved_id = path.stem if path else decision.duplicate_of

    ordered = sorted(all_slots, key=lambda s: s.order)
    bodies = [store.load(s.resolved_id).body.strip() for s in ordered if s.resolved_id]
    content = "\n\n---\n\n".join(bodies)

    result_path = _save_result(request, content, settings, out_path)
    manifest = {
        "request": request,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "slots": [
            {
                "order": s.order,
                "action": s.action,
                "block_id": s.block_id,
                "criteria": s.criteria,
                "resolved_id": s.resolved_id,
            }
            for s in ordered
        ],
    }
    manifest_path = result_path.with_name(result_path.stem + "_manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return ordered, result_path


def _save_result(request: str, content: str, settings: Settings, out_path: Path | None) -> Path:
    """Goes through the same naming.decide() flow as blocks: brand-new title -> saved
    plainly; a same-slug result already exists -> exact-match reuse or a bracket variant."""
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8")
        return out_path

    results_dir = settings.results_path
    results_dir.mkdir(parents=True, exist_ok=True)

    title = request.strip() or "result"
    base_slug = naming.slugify(title)[:60].rstrip("_") or "result"
    candidate = naming.Candidate(name=title, full_text=content)

    existing = [
        (p.stem, naming.Candidate(name=title, full_text=p.read_text(encoding="utf-8")))
        for p in results_dir.glob(f"{base_slug}*.md")
        if p.stem == base_slug or p.stem.startswith(f"{base_slug} [")
    ]

    naming_client, naming_model = get_client_and_model(settings.models.naming, settings)
    decision = naming.decide(
        candidate,
        existing,
        exists=lambda stem: (results_dir / f"{stem}.md").exists(),
        naming_client=naming_client,
        naming_model=naming_model,
    )

    if decision.action == "skip_duplicate":
        return results_dir / f"{decision.duplicate_of}.md"

    path = results_dir / f"{decision.stem}.md"
    path.write_text(content, encoding="utf-8")
    return path
