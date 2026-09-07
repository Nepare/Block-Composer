import sys
from dataclasses import replace
from datetime import datetime

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
import uvicorn

from tools import compose as compose_module
from tools import dissect as dissect_module
from tools import generate as generate_module
from tools import mutate as mutate_module
from web import web_jobs
from auth.router import get_auth_provider
from auth.web import WebAuthProvider
from core.config import Settings, load_settings
from core.errors import AuthError, BlockNotFoundError, CvdocsError
from core.naming import validate_explicit_name
from models.blocks import Block
from storage.base import Result
import os
from storage.router import get_block_storage, get_result_storage
from storage.sqlite import SqlitePendingSignInStore

app = FastAPI()


def _authorized(settings: Settings, key: str) -> bool:
    expected = os.environ.get(settings.auth.web_service.api_key_env, "")
    return bool(expected) and key == expected


@app.get("/auth/google/login")
def auth_google_login(key: str):
    settings = load_settings()
    if not _authorized(settings, key):
        return PlainTextResponse("Unauthorized", status_code=401)

    provider = get_auth_provider(settings)
    if not isinstance(provider, WebAuthProvider):
        return PlainTextResponse(
            "This deployment is not configured for hosted-mode connections.", status_code=400
        )

    state, code_verifier = SqlitePendingSignInStore(settings.storage_db_path).start()
    url = provider.build_authorization_url(state, code_verifier)
    return RedirectResponse(url, status_code=302)


@app.get("/auth/google/callback")
def auth_google_callback(code: str | None = None, state: str | None = None, error: str | None = None):
    if error or not code or not state:
        print(f"auth_google_callback rejected: error={error!r} code={bool(code)} state={bool(state)}", file=sys.stderr)
        return HTMLResponse("<p>Sign-in was not completed.</p>", status_code=400)

    settings = load_settings()
    code_verifier = SqlitePendingSignInStore(settings.storage_db_path).verify_and_consume(state)
    if code_verifier is None:
        return HTMLResponse(
            "<p>This sign-in link has expired or was already used.</p>", status_code=400
        )

    provider = get_auth_provider(settings)
    if not isinstance(provider, WebAuthProvider):
        return PlainTextResponse(
            "This deployment is not configured for hosted-mode connections.", status_code=400
        )

    try:
        creds = provider.exchange_code(code, code_verifier)
    except AuthError as exc:
        print(f"auth_google_callback exchange_code failed: {exc}", file=sys.stderr)
        return HTMLResponse("<p>Sign-in was not completed.</p>", status_code=400)

    provider.storage.save(creds)
    return HTMLResponse("<p>Connected successfully. You can close this window.</p>")


class GenerateStartRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    criteria: str
    block_schema: str = Field(default="project_entry", alias="schema")
    style_from: list[str] = []
    model: str | None = None
    name: str | None = None
    preserve: bool = False


class MutateStartRequest(BaseModel):
    block_id: str
    criteria: str
    model: str | None = None
    in_place: bool = False
    name: str | None = None
    preserve: bool = False


class DissectStartRequest(BaseModel):
    doc: str


class ComposeStartRequest(BaseModel):
    request: str = ""
    specifiers: str = ""
    use_ids: list[str] = []
    generate_criteria: list[str] = []
    count: int | None = None
    model: str | None = None
    max_generate: int | None = None
    name: str | None = None
    preserve: bool = False
    restrict_generate: bool = False
    restrict_mutate: bool = False
    from_block_ids: list[str] | None = None


class BlockUpdateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    body: str
    tags: list[str] | None = None
    block_schema: str | None = Field(default=None, alias="schema")


class BlockSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    tags: list[str]
    block_schema: str | None = Field(alias="schema")
    source: str
    created_at: datetime | None
    preserved: bool

    @classmethod
    def from_block(cls, block: Block) -> "BlockSummary":
        return cls(
            id=block.id,
            name=block.name,
            tags=block.tags,
            schema=block.schema,
            source=block.source,
            created_at=block.created_at,
            preserved=block.preserved,
        )


class BlockDetail(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    tags: list[str]
    block_schema: str | None = Field(alias="schema")
    source: str
    created_at: datetime | None
    body: str
    created_by: str
    generation_criteria: str | None
    mutated_from: str | None
    preserved: bool

    @classmethod
    def from_block(cls, block: Block) -> "BlockDetail":
        return cls(
            id=block.id,
            name=block.name,
            tags=block.tags,
            schema=block.schema,
            source=block.source,
            created_at=block.created_at,
            body=block.body,
            created_by=block.created_by,
            generation_criteria=block.generation_criteria,
            mutated_from=block.mutated_from,
            preserved=block.preserved,
        )


class ResultSummary(BaseModel):
    id: str
    name: str
    request: str
    created_at: datetime | None
    preserved: bool

    @classmethod
    def from_result(cls, result: Result) -> "ResultSummary":
        return cls(
            id=result.id,
            name=result.name,
            request=result.request,
            created_at=result.created_at,
            preserved=result.preserved,
        )


class ResultDetail(BaseModel):
    id: str
    name: str
    request: str
    created_at: datetime | None
    content: str
    use_ids: list[str]
    generate_criteria: list[str]
    slots: list[dict]
    preserved: bool

    @classmethod
    def from_result(cls, result: Result) -> "ResultDetail":
        return cls(
            id=result.id,
            name=result.name,
            request=result.request,
            created_at=result.created_at,
            content=result.content,
            use_ids=result.use_ids,
            generate_criteria=result.generate_criteria,
            slots=result.slots,
            preserved=result.preserved,
        )


@app.post("/generate/start")
def generate_start(payload: GenerateStartRequest, key: str):
    settings = load_settings()
    if not _authorized(settings, key):
        return PlainTextResponse("Unauthorized", status_code=401)

    if not payload.criteria.strip():
        return PlainTextResponse("criteria must not be empty.", status_code=400)

    if payload.name is not None:
        try:
            validate_explicit_name(payload.name)
        except CvdocsError as exc:
            return PlainTextResponse(str(exc), status_code=400)

    store = get_block_storage(settings)
    try:
        style_blocks = [store.load(bid) for bid in payload.style_from] if payload.style_from else None
    except CvdocsError as exc:
        return PlainTextResponse(str(exc), status_code=400)

    def work(on_progress, _cancel_event):
        block, decision, stem = generate_module.run_generate(
            payload.criteria,
            settings=settings,
            schema=payload.block_schema,
            style_from=style_blocks,
            model_spec=payload.model,
            name=payload.name,
            on_progress=on_progress,
            preserve=payload.preserve,
        )
        if decision.action == "skip_duplicate":
            return {"block_id": None, "duplicate": True, "duplicate_of": decision.duplicate_of}
        return {"block_id": stem, "duplicate": False, "duplicate_of": None}

    job = web_jobs.start_job(work)
    return {"job_id": job.id}


@app.post("/mutate/start")
def mutate_start(payload: MutateStartRequest, key: str):
    settings = load_settings()
    if not _authorized(settings, key):
        return PlainTextResponse("Unauthorized", status_code=401)

    if payload.name is not None and payload.in_place:
        return PlainTextResponse("name cannot be combined with in_place.", status_code=400)

    if payload.name is not None:
        try:
            validate_explicit_name(payload.name)
        except CvdocsError as exc:
            return PlainTextResponse(str(exc), status_code=400)

    store = get_block_storage(settings)
    try:
        store.load(payload.block_id)
    except CvdocsError as exc:
        return PlainTextResponse(str(exc), status_code=400)

    if not payload.criteria.strip():
        return PlainTextResponse("criteria must not be empty.", status_code=400)

    def work(on_progress, _cancel_event):
        _block, stem = mutate_module.run_mutate(
            payload.block_id,
            payload.criteria,
            settings=settings,
            model_spec=payload.model,
            in_place=payload.in_place,
            name=payload.name,
            on_progress=on_progress,
            preserve=payload.preserve,
        )
        return {"block_id": stem}

    job = web_jobs.start_job(work)
    return {"job_id": job.id}


@app.post("/dissect/start")
def dissect_start(payload: DissectStartRequest, key: str):
    settings = load_settings()
    if not _authorized(settings, key):
        return PlainTextResponse("Unauthorized", status_code=401)

    if not payload.doc.strip():
        return PlainTextResponse("doc must not be empty.", status_code=400)

    provider = get_auth_provider(settings)
    if not isinstance(provider, WebAuthProvider):
        return PlainTextResponse(
            "This deployment is not configured for hosted-mode connections.", status_code=400
        )
    try:
        provider.get_credentials()
    except AuthError as exc:
        return PlainTextResponse(str(exc), status_code=400)

    def work(on_progress, _cancel_event):
        result = dissect_module.run_dissect(payload.doc, settings=settings, on_progress=on_progress)
        return {
            "saved": [{"block_id": stem, "name": block.name} for block, stem in result.saved],
            "skipped_duplicates": [
                {"name": name, "duplicate_of": dup} for name, dup in result.skipped_duplicates
            ],
            "variants": [
                {"block_id": stem, "name": block.name, "label": label}
                for block, stem, label in result.variants
            ],
        }

    job = web_jobs.start_job(work)
    return {"job_id": job.id}


@app.post("/compose/start")
def compose_start(payload: ComposeStartRequest, key: str):
    settings = load_settings()
    if not _authorized(settings, key):
        return PlainTextResponse("Unauthorized", status_code=401)

    request = payload.request.strip()
    specifiers = payload.specifiers.strip()
    if specifiers and request:
        merged_request = f"{request}\n\nAdditional notes from the user: {specifiers}"
    elif specifiers:
        merged_request = specifiers
    else:
        merged_request = request

    store = get_block_storage(settings)
    try:
        for uid in payload.use_ids:
            store.load(uid)
    except CvdocsError as exc:
        return PlainTextResponse(str(exc), status_code=400)

    if not merged_request and not payload.use_ids and not payload.generate_criteria:
        return PlainTextResponse(
            "compose needs a request, specifiers, use_ids, or generate_criteria — nothing to do with all empty.",
            status_code=400,
        )

    if payload.count is not None and payload.count <= 0:
        return PlainTextResponse(f"count must be a positive integer, got {payload.count}.", status_code=400)

    if payload.restrict_generate and payload.generate_criteria:
        return PlainTextResponse(
            "restrict_generate cannot be combined with generate_criteria (a pinned new-block "
            "request) — these directly contradict each other.",
            status_code=400,
        )

    if payload.name is not None:
        try:
            validate_explicit_name(payload.name)
        except CvdocsError as exc:
            return PlainTextResponse(str(exc), status_code=400)

    def work(on_progress, cancel_event):
        outcome = compose_module.run_compose(
            merged_request,
            settings=settings,
            use_ids=payload.use_ids,
            generate_criteria=payload.generate_criteria,
            count=payload.count,
            model_spec=payload.model,
            max_generate=payload.max_generate if payload.max_generate is not None else 8,
            name=payload.name,
            on_progress=on_progress,
            cancel_check=cancel_event.is_set,
            preserve=payload.preserve,
            restrict_generate=payload.restrict_generate,
            restrict_mutate=payload.restrict_mutate,
            from_block_ids=payload.from_block_ids,
        )
        return {
            "result_id": outcome.result_id,
            "name": outcome.name,
            "content": outcome.content,
            "cancelled": outcome.cancelled,
            "slots": [
                {"order": s.order, "action": s.action, "block_id": s.block_id, "criteria": s.criteria, "resolved_id": s.resolved_id}
                for s in outcome.slots
            ],
        }

    job = web_jobs.start_job(work, cancellable=True)
    return {"job_id": job.id}


@app.get("/blocks")
def blocks_list(key: str, query: str | None = None, tag: list[str] = []):
    settings = load_settings()
    if not _authorized(settings, key):
        return PlainTextResponse("Unauthorized", status_code=401)

    store = get_block_storage(settings)
    blocks = store.search(query=query, tags=tag or None)
    return [BlockSummary.from_block(b) for b in blocks]


@app.get("/blocks/{block_id}")
def blocks_get(block_id: str, key: str):
    settings = load_settings()
    if not _authorized(settings, key):
        return PlainTextResponse("Unauthorized", status_code=401)

    store = get_block_storage(settings)
    try:
        block = store.load(block_id)
    except BlockNotFoundError as exc:
        return PlainTextResponse(str(exc), status_code=404)
    return BlockDetail.from_block(block)


@app.put("/blocks/{block_id}")
def blocks_update(block_id: str, payload: BlockUpdateRequest, key: str):
    settings = load_settings()
    if not _authorized(settings, key):
        return PlainTextResponse("Unauthorized", status_code=401)

    store = get_block_storage(settings)
    try:
        existing = store.load(block_id)
    except BlockNotFoundError as exc:
        return PlainTextResponse(str(exc), status_code=404)

    if not payload.body.strip():
        return PlainTextResponse("body must not be empty.", status_code=400)

    updated = replace(
        existing,
        body=payload.body,
        tags=payload.tags if payload.tags is not None else existing.tags,
        schema=payload.block_schema if payload.block_schema is not None else existing.schema,
    )
    store.save(updated, filename_stem=block_id)
    return BlockDetail.from_block(updated)


@app.delete("/blocks/{block_id}")
def blocks_delete(block_id: str, key: str):
    settings = load_settings()
    if not _authorized(settings, key):
        return PlainTextResponse("Unauthorized", status_code=401)

    store = get_block_storage(settings)
    try:
        store.delete(block_id)
    except BlockNotFoundError as exc:
        return PlainTextResponse(str(exc), status_code=404)
    return {"deleted": block_id}


@app.post("/blocks/{block_id}/preserve")
def blocks_preserve(block_id: str, key: str):
    settings = load_settings()
    if not _authorized(settings, key):
        return PlainTextResponse("Unauthorized", status_code=401)

    store = get_block_storage(settings)
    try:
        store.set_preserved(block_id, True)
    except BlockNotFoundError as exc:
        return PlainTextResponse(str(exc), status_code=404)
    return {"preserved": block_id}


@app.post("/blocks/{block_id}/unpreserve")
def blocks_unpreserve(block_id: str, key: str):
    settings = load_settings()
    if not _authorized(settings, key):
        return PlainTextResponse("Unauthorized", status_code=401)

    store = get_block_storage(settings)
    try:
        store.set_preserved(block_id, False)
    except BlockNotFoundError as exc:
        return PlainTextResponse(str(exc), status_code=404)
    return {"preserved": False}


@app.post("/blocks/clear")
def blocks_clear(key: str):
    settings = load_settings()
    if not _authorized(settings, key):
        return PlainTextResponse("Unauthorized", status_code=401)

    store = get_block_storage(settings)
    result = store.clear()
    return {"deleted": result.deleted, "skipped_preserved": result.skipped_preserved}


@app.get("/results")
def results_list(key: str, query: str | None = None):
    settings = load_settings()
    if not _authorized(settings, key):
        return PlainTextResponse("Unauthorized", status_code=401)

    store = get_result_storage(settings)
    results = store.search(query=query)
    return [ResultSummary.from_result(r) for r in results]


@app.get("/results/{result_id}")
def results_get(result_id: str, key: str):
    settings = load_settings()
    if not _authorized(settings, key):
        return PlainTextResponse("Unauthorized", status_code=401)

    store = get_result_storage(settings)
    try:
        result = store.load(result_id)
    except BlockNotFoundError as exc:
        return PlainTextResponse(str(exc), status_code=404)
    return ResultDetail.from_result(result)


@app.delete("/results/{result_id}")
def results_delete(result_id: str, key: str):
    settings = load_settings()
    if not _authorized(settings, key):
        return PlainTextResponse("Unauthorized", status_code=401)

    store = get_result_storage(settings)
    try:
        store.delete(result_id)
    except BlockNotFoundError as exc:
        return PlainTextResponse(str(exc), status_code=404)
    return {"deleted": result_id}


@app.post("/results/{result_id}/preserve")
def results_preserve(result_id: str, key: str):
    settings = load_settings()
    if not _authorized(settings, key):
        return PlainTextResponse("Unauthorized", status_code=401)

    store = get_result_storage(settings)
    try:
        store.set_preserved(result_id, True)
    except BlockNotFoundError as exc:
        return PlainTextResponse(str(exc), status_code=404)
    return {"preserved": result_id}


@app.post("/results/{result_id}/unpreserve")
def results_unpreserve(result_id: str, key: str):
    settings = load_settings()
    if not _authorized(settings, key):
        return PlainTextResponse("Unauthorized", status_code=401)

    store = get_result_storage(settings)
    try:
        store.set_preserved(result_id, False)
    except BlockNotFoundError as exc:
        return PlainTextResponse(str(exc), status_code=404)
    return {"preserved": False}


@app.post("/results/clear")
def results_clear(key: str):
    settings = load_settings()
    if not _authorized(settings, key):
        return PlainTextResponse("Unauthorized", status_code=401)

    store = get_result_storage(settings)
    result = store.clear()
    return {"deleted": result.deleted, "skipped_preserved": result.skipped_preserved}


@app.get("/stream/{job_id}")
async def stream(job_id: str, key: str):
    settings = load_settings()
    if not _authorized(settings, key):
        return PlainTextResponse("Unauthorized", status_code=401)

    job = web_jobs.get_job(job_id)
    if job is None:
        return PlainTextResponse("Unknown job id", status_code=404)

    return StreamingResponse(web_jobs.sse_events(job), media_type="text/event-stream")


@app.post("/cancel/{job_id}")
def cancel(job_id: str, key: str):
    settings = load_settings()
    if not _authorized(settings, key):
        return PlainTextResponse("Unauthorized", status_code=401)

    job = web_jobs.get_job(job_id)
    if job is None:
        return PlainTextResponse("Unknown job id", status_code=404)

    if job.cancel_event is None:
        return PlainTextResponse("This operation does not support cancellation.", status_code=400)

    if job.status != "running":
        return PlainTextResponse("This operation is no longer running.", status_code=400)

    job.cancel_event.set()
    return {"status": "cancelling"}


def _check_required_env(settings) -> None:
    required_env_vars = [
        settings.auth.google.web_client_id_env,
        settings.auth.google.web_client_secret_env,
        settings.auth.web_service.api_key_env,
    ]
    missing = [name for name in required_env_vars if not os.environ.get(name)]
    if missing:
        for name in missing:
            print(f"Missing required environment variable: {name}", file=sys.stderr)
        raise SystemExit(1)


def main() -> None:
    _check_required_env(load_settings())
    uvicorn.run("web.webapp:app", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
