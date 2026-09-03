import sys

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
from core.errors import AuthError, CvdocsError
import os
from storage.router import get_block_storage
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


class MutateStartRequest(BaseModel):
    block_id: str
    criteria: str
    model: str | None = None
    in_place: bool = False


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


@app.post("/generate/start")
def generate_start(payload: GenerateStartRequest, key: str):
    settings = load_settings()
    if not _authorized(settings, key):
        return PlainTextResponse("Unauthorized", status_code=401)

    if not payload.criteria.strip():
        return PlainTextResponse("criteria must not be empty.", status_code=400)

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
            on_progress=on_progress,
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
            on_progress=on_progress,
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

    def work(on_progress, cancel_event):
        outcome = compose_module.run_compose(
            merged_request,
            settings=settings,
            use_ids=payload.use_ids,
            generate_criteria=payload.generate_criteria,
            count=payload.count,
            model_spec=payload.model,
            max_generate=payload.max_generate if payload.max_generate is not None else 8,
            on_progress=on_progress,
            cancel_check=cancel_event.is_set,
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
