import json
import time
from pathlib import Path

from fastapi.testclient import TestClient
from google.oauth2.credentials import Credentials

from tools import dissect as dissect_module
from tools import docs_api
from tools import generate as generate_module
from tools import mutate as mutate_module
from web import web_jobs
from web import webapp
from auth.web import WebAuthProvider
from models.blocks import Block
from fakes import FakeLLMClient
from storage.filesystem import FilesystemBlockStorage

DISSECT_FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "greentown_doc_response.json"


def _load_dissect_fixture():
    return json.loads(DISSECT_FIXTURE.read_text(encoding="utf-8"))


def _client(settings, monkeypatch):
    monkeypatch.setattr(webapp, "load_settings", lambda: settings)
    monkeypatch.setenv(settings.auth.web_service.api_key_env, "test-key")
    return TestClient(webapp.app)


def _wait_for_job(job_id: str, timeout: float = 2.0) -> web_jobs.Job:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = web_jobs.get_job(job_id)
        if job is not None and job.status != "running":
            return job
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not finish within {timeout}s")


def _stream(client, url):
    with client.stream("GET", url) as response:
        text = "".join(response.iter_text())
    parsed = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        kind = "complete" if block.startswith("event: complete") else "data"
        payload = json.loads(block.split("data: ", 1)[1])
        parsed.append((kind, payload))
    return parsed


class FakeCredentialsStorage:
    def __init__(self, creds=None):
        self._creds = creds

    def save(self, creds):
        self._creds = creds

    def load(self):
        return self._creds


def _connected_provider(settings):
    creds = Credentials(
        token="valid-token",
        refresh_token="r",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="x",
        client_secret="y",
        scopes=settings.auth.google.scopes,
    )
    return WebAuthProvider(settings, FakeCredentialsStorage(creds))


def test_generate_start_runs_in_background_and_saves(settings, monkeypatch, fake_router):
    client = _client(settings, monkeypatch)
    llm = FakeLLMClient(replies=["## Sheriff Outpost\n\nA frontier outpost.\n\n**Role:** nobody\n"])
    fake_router(generate_module, llm)

    response = client.post(
        "/generate/start", params={"key": "test-key"}, json={"criteria": "a sheriff outpost"}
    )

    assert response.status_code == 200
    job_id = response.json()["job_id"]
    job = _wait_for_job(job_id)
    assert job.status == "done"
    assert job.outcome == {"block_id": "sheriff_outpost", "duplicate": False, "duplicate_of": None}


def test_generate_start_reports_skip_duplicate(settings, monkeypatch, fake_router):
    body = "## Sheriff Outpost\n\nA frontier outpost.\n\n**Role:** nobody\n"
    FilesystemBlockStorage(settings.blocks_path).save(Block(id="", body=body), filename_stem="sheriff_outpost")
    client = _client(settings, monkeypatch)
    llm = FakeLLMClient(replies=[body])
    fake_router(generate_module, llm)

    response = client.post(
        "/generate/start", params={"key": "test-key"}, json={"criteria": "a sheriff outpost"}
    )

    job = _wait_for_job(response.json()["job_id"])
    assert job.status == "done"
    assert job.outcome == {"block_id": None, "duplicate": True, "duplicate_of": "sheriff_outpost"}


def test_mutate_start_runs_in_background_and_saves(settings, monkeypatch, fake_router):
    FilesystemBlockStorage(settings.blocks_path).save(
        Block(id="", body="## Police Station\n\nRegular station.\n\n**Rooms:**\n- Office\n"),
        filename_stem="police_station",
    )
    client = _client(settings, monkeypatch)
    llm = FakeLLMClient(
        replies=[
            "===BODY===\n## Police Station\n\nRenovated station.\n\n**Rooms:**\n- Office\n"
            "- Armory\n===LABEL===\nrenovated\n"
        ]
    )
    fake_router(mutate_module, llm)

    response = client.post(
        "/mutate/start",
        params={"key": "test-key"},
        json={"block_id": "police_station", "criteria": "add an armory"},
    )

    assert response.status_code == 200
    job = _wait_for_job(response.json()["job_id"])
    assert job.status == "done"
    assert job.outcome == {"block_id": "police_station_mut_renovated"}


def test_dissect_start_runs_in_background_and_saves(settings, monkeypatch, fake_router):
    document = _load_dissect_fixture()
    monkeypatch.setattr(docs_api, "get_document", lambda doc_id, settings=None: document)
    client = _client(settings, monkeypatch)
    monkeypatch.setattr(webapp, "get_auth_provider", lambda s: _connected_provider(s))
    fake_router(dissect_module, FakeLLMClient())  # naming client must not be called -- no conflicts

    response = client.post(
        "/dissect/start", params={"key": "test-key"}, json={"doc": "https://docs.google.com/document/d/FAKEID/edit"}
    )

    assert response.status_code == 200
    job_id = response.json()["job_id"]
    job = _wait_for_job(job_id)
    assert job.status == "done"
    assert job.outcome == {
        "saved": [
            {"block_id": "police_station", "name": "Police Station"},
            {"block_id": "lumber", "name": "Lumber"},
        ],
        "skipped_duplicates": [],
        "variants": [],
    }


def test_dissect_start_second_pass_reports_duplicates(settings, monkeypatch, fake_router):
    document = _load_dissect_fixture()
    monkeypatch.setattr(docs_api, "get_document", lambda doc_id, settings=None: document)
    client = _client(settings, monkeypatch)
    monkeypatch.setattr(webapp, "get_auth_provider", lambda s: _connected_provider(s))
    fake_router(dissect_module, FakeLLMClient())

    first = client.post("/dissect/start", params={"key": "test-key"}, json={"doc": "doc1"})
    _wait_for_job(first.json()["job_id"])

    second = client.post("/dissect/start", params={"key": "test-key"}, json={"doc": "doc1"})
    job = _wait_for_job(second.json()["job_id"])

    assert job.status == "done"
    assert job.outcome["saved"] == []
    assert len(job.outcome["skipped_duplicates"]) == 2


def test_dissect_stream_delivers_progress_then_done_outcome(settings, monkeypatch, fake_router):
    document = _load_dissect_fixture()
    monkeypatch.setattr(docs_api, "get_document", lambda doc_id, settings=None: document)
    client = _client(settings, monkeypatch)
    monkeypatch.setattr(webapp, "get_auth_provider", lambda s: _connected_provider(s))
    fake_router(dissect_module, FakeLLMClient())

    start = client.post("/dissect/start", params={"key": "test-key"}, json={"doc": "doc1"})
    job_id = start.json()["job_id"]

    parsed = _stream(client, f"/stream/{job_id}?key=test-key")

    kinds = [payload["kind"] for kind, payload in parsed if kind == "data"]
    assert kinds.count("dissect_row") == 2
    assert parsed[-1][0] == "complete"
    assert parsed[-1][1]["status"] == "done"
    assert len(parsed[-1][1]["saved"]) == 2


def test_dissect_start_rejects_empty_doc(settings, monkeypatch):
    client = _client(settings, monkeypatch)
    jobs_before = len(web_jobs._jobs)

    response = client.post("/dissect/start", params={"key": "test-key"}, json={"doc": "   "})

    assert response.status_code == 400
    assert len(web_jobs._jobs) == jobs_before


def test_dissect_start_rejects_when_not_configured_for_hosted_mode(settings, monkeypatch):
    client = _client(settings, monkeypatch)
    jobs_before = len(web_jobs._jobs)
    monkeypatch.setattr(webapp, "get_auth_provider", lambda s: object())

    response = client.post("/dissect/start", params={"key": "test-key"}, json={"doc": "doc1"})

    assert response.status_code == 400
    assert "not configured" in response.text
    assert len(web_jobs._jobs) == jobs_before


def test_dissect_start_rejects_when_not_connected(settings, monkeypatch):
    client = _client(settings, monkeypatch)
    jobs_before = len(web_jobs._jobs)
    monkeypatch.setattr(
        webapp, "get_auth_provider", lambda s: WebAuthProvider(s, FakeCredentialsStorage(None))
    )

    response = client.post("/dissect/start", params={"key": "test-key"}, json={"doc": "doc1"})

    assert response.status_code == 400
    assert len(web_jobs._jobs) == jobs_before


def test_generate_start_rejects_empty_criteria(settings, monkeypatch):
    client = _client(settings, monkeypatch)

    response = client.post("/generate/start", params={"key": "test-key"}, json={"criteria": "   "})

    assert response.status_code == 400


def test_generate_start_rejects_unknown_style_from_id(settings, monkeypatch):
    client = _client(settings, monkeypatch)

    response = client.post(
        "/generate/start",
        params={"key": "test-key"},
        json={"criteria": "a sheriff outpost", "style_from": ["does-not-exist"]},
    )

    assert response.status_code == 400


def test_mutate_start_rejects_unknown_block_id(settings, monkeypatch):
    client = _client(settings, monkeypatch)

    response = client.post(
        "/mutate/start",
        params={"key": "test-key"},
        json={"block_id": "does-not-exist", "criteria": "add an armory"},
    )

    assert response.status_code == 400


def test_mutate_start_rejects_empty_criteria(settings, monkeypatch):
    FilesystemBlockStorage(settings.blocks_path).save(
        Block(id="", body="## Police Station\n\nRegular station.\n\n**Rooms:**\n- Office\n"),
        filename_stem="police_station",
    )
    client = _client(settings, monkeypatch)

    response = client.post(
        "/mutate/start", params={"key": "test-key"}, json={"block_id": "police_station", "criteria": "  "}
    )

    assert response.status_code == 400


def test_generate_stream_delivers_progress_then_done_outcome(settings, monkeypatch, fake_router):
    client = _client(settings, monkeypatch)
    llm = FakeLLMClient(replies=["## Sheriff Outpost\n\nA frontier outpost.\n\n**Role:** nobody\n"])
    fake_router(generate_module, llm)

    start = client.post("/generate/start", params={"key": "test-key"}, json={"criteria": "a sheriff outpost"})
    job_id = start.json()["job_id"]

    parsed = _stream(client, f"/stream/{job_id}?key=test-key")

    kinds = [payload["kind"] for kind, payload in parsed if kind == "data"]
    assert "generate_start" in kinds
    assert "naming" in kinds
    assert parsed[-1] == (
        "complete",
        {"status": "done", "block_id": "sheriff_outpost", "duplicate": False, "duplicate_of": None},
    )


def test_mutate_stream_delivers_progress_then_done_outcome(settings, monkeypatch, fake_router):
    FilesystemBlockStorage(settings.blocks_path).save(
        Block(id="", body="## Police Station\n\nRegular station.\n\n**Rooms:**\n- Office\n"),
        filename_stem="police_station",
    )
    client = _client(settings, monkeypatch)
    llm = FakeLLMClient(
        replies=[
            "===BODY===\n## Police Station\n\nRenovated station.\n\n**Rooms:**\n- Office\n"
            "- Armory\n===LABEL===\nrenovated\n"
        ]
    )
    fake_router(mutate_module, llm)

    start = client.post(
        "/mutate/start",
        params={"key": "test-key"},
        json={"block_id": "police_station", "criteria": "add an armory"},
    )
    job_id = start.json()["job_id"]

    parsed = _stream(client, f"/stream/{job_id}?key=test-key")

    kinds = [payload["kind"] for kind, payload in parsed if kind == "data"]
    assert "mutate_start" in kinds
    assert parsed[-1] == ("complete", {"status": "done", "block_id": "police_station_mut_renovated"})


def test_generate_stream_reports_error_outcome_on_exhausted_retry(settings, monkeypatch, fake_router):
    client = _client(settings, monkeypatch)
    llm = FakeLLMClient(replies=["still no heading", "still no heading"])
    fake_router(generate_module, llm)

    start = client.post("/generate/start", params={"key": "test-key"}, json={"criteria": "a sheriff outpost"})
    job_id = start.json()["job_id"]

    parsed = _stream(client, f"/stream/{job_id}?key=test-key")

    kind, payload = parsed[-1]
    assert kind == "complete"
    assert payload["status"] == "error"
    assert "error" in payload


def test_stream_connect_after_job_finished_still_replays_full_history(settings, monkeypatch, fake_router):
    client = _client(settings, monkeypatch)
    llm = FakeLLMClient(replies=["## Sheriff Outpost\n\nA frontier outpost.\n\n**Role:** nobody\n"])
    fake_router(generate_module, llm)

    start = client.post("/generate/start", params={"key": "test-key"}, json={"criteria": "a sheriff outpost"})
    job_id = start.json()["job_id"]
    _wait_for_job(job_id)  # job already finished before we ever connect to the stream

    parsed = _stream(client, f"/stream/{job_id}?key=test-key")

    kinds = [payload["kind"] for kind, payload in parsed if kind == "data"]
    assert "generate_start" in kinds
    assert "naming" in kinds
    assert parsed[-1][0] == "complete"
    assert parsed[-1][1]["status"] == "done"


def test_generate_stream_rejects_unknown_job_id(settings, monkeypatch):
    client = _client(settings, monkeypatch)

    response = client.get("/stream/does-not-exist", params={"key": "test-key"})

    assert response.status_code == 404


def test_mutate_stream_rejects_unknown_job_id(settings, monkeypatch):
    client = _client(settings, monkeypatch)

    response = client.get("/stream/does-not-exist", params={"key": "test-key"})

    assert response.status_code == 404


def test_generate_start_rejects_missing_key(settings, monkeypatch):
    # `key` has no default, so a missing one is a 422 from FastAPI's own validation,
    # not the route body's 401 _authorized check.
    client = _client(settings, monkeypatch)
    jobs_before = len(web_jobs._jobs)

    response = client.post("/generate/start", json={"criteria": "a sheriff outpost"})

    assert response.status_code == 422
    assert len(web_jobs._jobs) == jobs_before


def test_generate_start_rejects_wrong_key(settings, monkeypatch):
    client = _client(settings, monkeypatch)
    jobs_before = len(web_jobs._jobs)

    response = client.post(
        "/generate/start", params={"key": "wrong-key"}, json={"criteria": "a sheriff outpost"}
    )

    assert response.status_code == 401
    assert len(web_jobs._jobs) == jobs_before


def test_mutate_start_rejects_missing_key(settings, monkeypatch):
    client = _client(settings, monkeypatch)
    jobs_before = len(web_jobs._jobs)

    response = client.post("/mutate/start", json={"block_id": "police_station", "criteria": "add an armory"})

    assert response.status_code == 422
    assert len(web_jobs._jobs) == jobs_before


def test_mutate_start_rejects_wrong_key(settings, monkeypatch):
    client = _client(settings, monkeypatch)
    jobs_before = len(web_jobs._jobs)

    response = client.post(
        "/mutate/start",
        params={"key": "wrong-key"},
        json={"block_id": "police_station", "criteria": "add an armory"},
    )

    assert response.status_code == 401
    assert len(web_jobs._jobs) == jobs_before


def test_generate_stream_rejects_missing_key(settings, monkeypatch, fake_router):
    client = _client(settings, monkeypatch)
    llm = FakeLLMClient(replies=["## Sheriff Outpost\n\nA frontier outpost.\n\n**Role:** nobody\n"])
    fake_router(generate_module, llm)
    start = client.post("/generate/start", params={"key": "test-key"}, json={"criteria": "a sheriff outpost"})
    job_id = start.json()["job_id"]

    response = client.get(f"/stream/{job_id}")

    assert response.status_code == 422
    assert not response.headers["content-type"].startswith("text/event-stream")


def test_generate_stream_rejects_wrong_key(settings, monkeypatch, fake_router):
    client = _client(settings, monkeypatch)
    llm = FakeLLMClient(replies=["## Sheriff Outpost\n\nA frontier outpost.\n\n**Role:** nobody\n"])
    fake_router(generate_module, llm)
    start = client.post("/generate/start", params={"key": "test-key"}, json={"criteria": "a sheriff outpost"})
    job_id = start.json()["job_id"]

    response = client.get(f"/stream/{job_id}", params={"key": "wrong-key"})

    assert response.status_code == 401
    assert not response.headers["content-type"].startswith("text/event-stream")


def test_mutate_stream_rejects_missing_key(settings, monkeypatch, fake_router):
    FilesystemBlockStorage(settings.blocks_path).save(
        Block(id="", body="## Police Station\n\nRegular station.\n\n**Rooms:**\n- Office\n"),
        filename_stem="police_station",
    )
    client = _client(settings, monkeypatch)
    llm = FakeLLMClient(
        replies=[
            "===BODY===\n## Police Station\n\nRenovated station.\n\n**Rooms:**\n- Office\n"
            "- Armory\n===LABEL===\nrenovated\n"
        ]
    )
    fake_router(mutate_module, llm)
    start = client.post(
        "/mutate/start",
        params={"key": "test-key"},
        json={"block_id": "police_station", "criteria": "add an armory"},
    )
    job_id = start.json()["job_id"]

    response = client.get(f"/stream/{job_id}")

    assert response.status_code == 422
    assert not response.headers["content-type"].startswith("text/event-stream")


def test_mutate_stream_rejects_wrong_key(settings, monkeypatch, fake_router):
    FilesystemBlockStorage(settings.blocks_path).save(
        Block(id="", body="## Police Station\n\nRegular station.\n\n**Rooms:**\n- Office\n"),
        filename_stem="police_station",
    )
    client = _client(settings, monkeypatch)
    llm = FakeLLMClient(
        replies=[
            "===BODY===\n## Police Station\n\nRenovated station.\n\n**Rooms:**\n- Office\n"
            "- Armory\n===LABEL===\nrenovated\n"
        ]
    )
    fake_router(mutate_module, llm)
    start = client.post(
        "/mutate/start",
        params={"key": "test-key"},
        json={"block_id": "police_station", "criteria": "add an armory"},
    )
    job_id = start.json()["job_id"]

    response = client.get(f"/stream/{job_id}", params={"key": "wrong-key"})

    assert response.status_code == 401
    assert not response.headers["content-type"].startswith("text/event-stream")


def test_auth_google_login_rejects_missing_key(settings, monkeypatch):
    client = _client(settings, monkeypatch)

    response = client.get("/auth/google/login", follow_redirects=False)

    assert response.status_code == 422


def test_stream_route_behaves_identically_across_all_three_tools(settings, monkeypatch, fake_router):
    client = _client(settings, monkeypatch)

    fake_router(generate_module, FakeLLMClient(replies=["## Sheriff Outpost\n\nA frontier outpost.\n\n**Role:** nobody\n"]))
    gen_start = client.post("/generate/start", params={"key": "test-key"}, json={"criteria": "a sheriff outpost"})
    gen_job_id = gen_start.json()["job_id"]
    _wait_for_job(gen_job_id)

    FilesystemBlockStorage(settings.blocks_path).save(
        Block(id="", body="## Watchtower\n\nRegular tower.\n\n**Rooms:**\n- Deck\n"),
        filename_stem="watchtower",
    )
    fake_router(
        mutate_module,
        FakeLLMClient(
            replies=[
                "===BODY===\n## Watchtower\n\nRenovated tower.\n\n**Rooms:**\n- Deck\n"
                "- Armory\n===LABEL===\nrenovated\n"
            ]
        ),
    )
    mut_start = client.post(
        "/mutate/start",
        params={"key": "test-key"},
        json={"block_id": "watchtower", "criteria": "add an armory"},
    )
    mut_job_id = mut_start.json()["job_id"]
    _wait_for_job(mut_job_id)

    document = _load_dissect_fixture()
    monkeypatch.setattr(docs_api, "get_document", lambda doc_id, settings=None: document)
    monkeypatch.setattr(webapp, "get_auth_provider", lambda s: _connected_provider(s))
    fake_router(dissect_module, FakeLLMClient())
    dis_start = client.post("/dissect/start", params={"key": "test-key"}, json={"doc": "doc1"})
    dis_job_id = dis_start.json()["job_id"]
    _wait_for_job(dis_job_id)

    for job_id in (gen_job_id, mut_job_id, dis_job_id):
        parsed = _stream(client, f"/stream/{job_id}?key=test-key")
        data_events = [payload for kind, payload in parsed if kind == "data"]
        assert len(data_events) >= 1
        assert parsed[-1][0] == "complete"
        assert parsed[-1][1]["status"] == "done"

    response = client.get("/stream/does-not-exist", params={"key": "test-key"})
    assert response.status_code == 404
