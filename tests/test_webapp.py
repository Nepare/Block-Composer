import json
import time

from fastapi.testclient import TestClient

import generate as generate_module
import mutate as mutate_module
import web_jobs
import webapp
from blocks import Block
from fakes import FakeLLMClient
from storage.filesystem import FilesystemBlockStorage


def _client(settings, monkeypatch):
    monkeypatch.setattr(webapp, "load_settings", lambda: settings)
    monkeypatch.setenv(settings.web_service.api_key_env, "test-key")
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

    parsed = _stream(client, f"/generate/stream/{job_id}?key=test-key")

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

    parsed = _stream(client, f"/mutate/stream/{job_id}?key=test-key")

    kinds = [payload["kind"] for kind, payload in parsed if kind == "data"]
    assert "mutate_start" in kinds
    assert parsed[-1] == ("complete", {"status": "done", "block_id": "police_station_mut_renovated"})


def test_generate_stream_reports_error_outcome_on_exhausted_retry(settings, monkeypatch, fake_router):
    client = _client(settings, monkeypatch)
    llm = FakeLLMClient(replies=["still no heading", "still no heading"])
    fake_router(generate_module, llm)

    start = client.post("/generate/start", params={"key": "test-key"}, json={"criteria": "a sheriff outpost"})
    job_id = start.json()["job_id"]

    parsed = _stream(client, f"/generate/stream/{job_id}?key=test-key")

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

    parsed = _stream(client, f"/generate/stream/{job_id}?key=test-key")

    kinds = [payload["kind"] for kind, payload in parsed if kind == "data"]
    assert "generate_start" in kinds
    assert "naming" in kinds
    assert parsed[-1][0] == "complete"
    assert parsed[-1][1]["status"] == "done"


def test_generate_stream_rejects_unknown_job_id(settings, monkeypatch):
    client = _client(settings, monkeypatch)

    response = client.get("/generate/stream/does-not-exist", params={"key": "test-key"})

    assert response.status_code == 404


def test_mutate_stream_rejects_unknown_job_id(settings, monkeypatch):
    client = _client(settings, monkeypatch)

    response = client.get("/mutate/stream/does-not-exist", params={"key": "test-key"})

    assert response.status_code == 404


def test_generate_start_rejects_missing_key(settings, monkeypatch):
    # `key` has no default, so FastAPI's own request validation rejects a missing one
    # (422) before the route body's _authorized check ever runs — still "rejected, no
    # job created," just via a different, earlier mechanism than a wrong key (401).
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

    response = client.get(f"/generate/stream/{job_id}")

    assert response.status_code == 422
    assert not response.headers["content-type"].startswith("text/event-stream")


def test_generate_stream_rejects_wrong_key(settings, monkeypatch, fake_router):
    client = _client(settings, monkeypatch)
    llm = FakeLLMClient(replies=["## Sheriff Outpost\n\nA frontier outpost.\n\n**Role:** nobody\n"])
    fake_router(generate_module, llm)
    start = client.post("/generate/start", params={"key": "test-key"}, json={"criteria": "a sheriff outpost"})
    job_id = start.json()["job_id"]

    response = client.get(f"/generate/stream/{job_id}", params={"key": "wrong-key"})

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

    response = client.get(f"/mutate/stream/{job_id}")

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

    response = client.get(f"/mutate/stream/{job_id}", params={"key": "wrong-key"})

    assert response.status_code == 401
    assert not response.headers["content-type"].startswith("text/event-stream")


def test_auth_google_login_rejects_missing_key(settings, monkeypatch):
    client = _client(settings, monkeypatch)

    response = client.get("/auth/google/login", follow_redirects=False)

    assert response.status_code == 422
