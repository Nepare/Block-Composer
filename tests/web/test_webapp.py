import json
import time
from pathlib import Path

from fastapi.testclient import TestClient
from google.oauth2.credentials import Credentials

from tools import compose as compose_module
from tools import dissect as dissect_module
from tools import docs_api
from tools import generate as generate_module
from tools import mutate as mutate_module
from web import web_jobs
from web import webapp
from auth.web import WebAuthProvider
from core.naming import NamingDecision
from models.blocks import Block
from fakes import FakeLLMClient
from storage.base import Result
from storage.filesystem import FilesystemBlockStorage, FilesystemResultStorage

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


def test_compose_start_runs_in_background_and_saves(settings, monkeypatch, fake_router):
    FilesystemBlockStorage(settings.blocks_path).save(
        Block(id="", body="## School\n\nTeaches children.\n\n**Rooms:**\n- Classroom\n"),
        filename_stem="school",
    )
    client = _client(settings, monkeypatch)
    plan = json.dumps(
        {
            "steps": [
                {"order": 1, "action": "use", "block_id": "school", "criteria": None},
                {"order": 2, "action": "generate", "block_id": None, "criteria": "a sawmill"},
            ]
        }
    )
    unparseable_keywords_reply = "I cannot help with that."
    generate_reply = "## Sawmill\n\nCuts logs.\n\n**Rooms:**\n- Saw room\n"
    # explicit count skips the target-count-detection call entirely -- reply order is
    # keyword extraction, planning, the generate step's own body, then result naming
    llm = FakeLLMClient(replies=[unparseable_keywords_reply, plan, generate_reply, "school_and_sawmill"])
    fake_router(compose_module, llm)
    fake_router(generate_module, llm)

    response = client.post(
        "/compose/start",
        params={"key": "test-key"},
        json={"request": "need a school and a sawmill", "count": 2},
    )

    assert response.status_code == 200
    job = _wait_for_job(response.json()["job_id"])
    assert job.status == "done"
    outcome = job.outcome
    assert outcome["cancelled"] is False
    assert outcome["result_id"] is not None
    assert outcome["name"] is not None
    assert outcome["content"] is not None
    assert len(outcome["slots"]) == 2
    assert all(slot["resolved_id"] is not None for slot in outcome["slots"])


def test_compose_start_rejects_all_empty(settings, monkeypatch):
    client = _client(settings, monkeypatch)
    jobs_before = len(web_jobs._jobs)

    response = client.post(
        "/compose/start",
        params={"key": "test-key"},
        json={"request": "", "specifiers": "", "use_ids": [], "generate_criteria": []},
    )

    assert response.status_code == 400
    assert response.text == (
        "compose needs a request, specifiers, use_ids, or generate_criteria — "
        "nothing to do with all empty."
    )
    assert len(web_jobs._jobs) == jobs_before


def test_compose_start_rejects_unknown_use_id(settings, monkeypatch):
    client = _client(settings, monkeypatch)
    jobs_before = len(web_jobs._jobs)

    response = client.post(
        "/compose/start", params={"key": "test-key"}, json={"use_ids": ["does-not-exist"]}
    )

    assert response.status_code == 400
    assert len(web_jobs._jobs) == jobs_before


def test_compose_start_rejects_non_positive_count(settings, monkeypatch):
    FilesystemBlockStorage(settings.blocks_path).save(
        Block(id="", body="## School\n\nTeaches children.\n\n**Rooms:**\n- Classroom\n"),
        filename_stem="school",
    )
    client = _client(settings, monkeypatch)

    for count in (0, -1):
        jobs_before = len(web_jobs._jobs)
        response = client.post(
            "/compose/start",
            params={"key": "test-key"},
            json={"use_ids": ["school"], "count": count},
        )
        assert response.status_code == 400
        assert response.text == f"count must be a positive integer, got {count}."
        assert len(web_jobs._jobs) == jobs_before


def test_compose_start_rejects_missing_key(settings, monkeypatch):
    client = _client(settings, monkeypatch)
    jobs_before = len(web_jobs._jobs)

    response = client.post("/compose/start", json={"use_ids": []})

    assert response.status_code == 422
    assert len(web_jobs._jobs) == jobs_before


def test_compose_start_rejects_wrong_key(settings, monkeypatch):
    FilesystemBlockStorage(settings.blocks_path).save(
        Block(id="", body="## School\n\nTeaches children.\n\n**Rooms:**\n- Classroom\n"),
        filename_stem="school",
    )
    client = _client(settings, monkeypatch)
    jobs_before = len(web_jobs._jobs)

    response = client.post(
        "/compose/start", params={"key": "wrong-key"}, json={"use_ids": ["school"]}
    )

    assert response.status_code == 401
    assert len(web_jobs._jobs) == jobs_before


def test_cancel_stops_mid_run_and_keeps_completed_work(settings, monkeypatch, fake_router):
    FilesystemBlockStorage(settings.blocks_path).save(
        Block(id="", body="## Police Station\n\nRegular station.\n\n**Rooms:**\n- Office\n"),
        filename_stem="police_station",
    )
    client = _client(settings, monkeypatch)
    plan = json.dumps(
        {
            "steps": [
                {"order": 1, "action": "mutate", "block_id": "police_station", "criteria": "adapt"},
                {"order": 2, "action": "generate", "block_id": None, "criteria": "a sawmill"},
            ]
        }
    )
    mutate_reply = (
        "===BODY===\n## Sheriff Station\n\nAdapted.\n\n**Rooms:**\n- Office\n===LABEL===\nsheriff"
    )
    unparseable_keywords_reply = "I cannot help with that."
    job_id_holder: dict[str, str] = {}

    class CancellingClient(FakeLLMClient):
        # Fires the real /cancel HTTP call from inside the compose background thread, right
        # after the mutate step's own reply is delivered -- deterministic (no sleep/race):
        # by the time run_compose's loop reaches slot 2's cancel_check, cancellation is set.
        def chat(self, messages, model, **kwargs):
            reply = super().chat(messages, model, **kwargs)
            if reply == mutate_reply:
                while "id" not in job_id_holder:
                    time.sleep(0.001)
                client.post(f"/cancel/{job_id_holder['id']}", params={"key": "test-key"})
            return reply

    llm = CancellingClient(replies=["NONE", unparseable_keywords_reply, plan, mutate_reply])
    fake_router(compose_module, llm)
    fake_router(mutate_module, llm)

    response = client.post(
        "/compose/start", params={"key": "test-key"}, json={"request": "need law enforcement and lumber"}
    )
    job_id = response.json()["job_id"]
    job_id_holder["id"] = job_id

    job = _wait_for_job(job_id)

    assert job.status == "cancelled"
    outcome = job.outcome
    assert outcome["cancelled"] is True
    assert outcome["result_id"] is None
    assert outcome["name"] is None
    assert outcome["content"] is None
    slots = {s["order"]: s for s in outcome["slots"]}
    assert slots[1]["resolved_id"] == "sheriff_station"
    assert slots[2]["resolved_id"] is None
    assert FilesystemBlockStorage(settings.blocks_path).exists("sheriff_station")


def test_cancel_rejected_for_non_cancellable_job(settings, monkeypatch, fake_router):
    client = _client(settings, monkeypatch)
    llm = FakeLLMClient(replies=["## Sheriff Outpost\n\nA frontier outpost.\n\n**Role:** nobody\n"])
    fake_router(generate_module, llm)
    start = client.post("/generate/start", params={"key": "test-key"}, json={"criteria": "a sheriff outpost"})
    job_id = start.json()["job_id"]
    _wait_for_job(job_id)

    response = client.post(f"/cancel/{job_id}", params={"key": "test-key"})

    assert response.status_code == 400
    assert response.text == "This operation does not support cancellation."


def test_cancel_rejected_for_already_finished_job(settings, monkeypatch, fake_router):
    FilesystemBlockStorage(settings.blocks_path).save(
        Block(id="", body="## School\n\nTeaches children.\n\n**Rooms:**\n- Classroom\n"),
        filename_stem="school",
    )
    client = _client(settings, monkeypatch)
    fake_router(compose_module, FakeLLMClient(replies=["school_result"]))
    start = client.post("/compose/start", params={"key": "test-key"}, json={"use_ids": ["school"]})
    job_id = start.json()["job_id"]
    _wait_for_job(job_id)

    response = client.post(f"/cancel/{job_id}", params={"key": "test-key"})

    assert response.status_code == 400
    assert response.text == "This operation is no longer running."


def test_cancel_rejected_for_unknown_job_id(settings, monkeypatch):
    client = _client(settings, monkeypatch)

    response = client.post("/cancel/does-not-exist", params={"key": "test-key"})

    assert response.status_code == 404


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


def test_compose_stream_delivers_events_in_expected_order(settings, monkeypatch, fake_router):
    FilesystemBlockStorage(settings.blocks_path).save(
        Block(id="", body="## Block Zero\n\nFirst block.\n\n**Rooms:**\n- Room\n"), filename_stem="block_0"
    )
    FilesystemBlockStorage(settings.blocks_path).save(
        Block(id="", body="## Block One\n\nSecond block.\n\n**Rooms:**\n- Room\n"), filename_stem="block_1"
    )
    client = _client(settings, monkeypatch)
    keywords_reply = "ROLE: \nENVIRONMENT: Jira\nRESPONSIBILITIES: \nDOMAIN: \n"
    plan = json.dumps(
        {
            "steps": [
                {"order": 1, "action": "use", "block_id": "block_0", "criteria": None},
                {"order": 2, "action": "use", "block_id": "block_1", "criteria": None},
            ]
        }
    )
    llm = FakeLLMClient(replies=[keywords_reply, plan, "two_blocks_result"])
    fake_router(compose_module, llm)

    start = client.post(
        "/compose/start",
        params={"key": "test-key"},
        json={"request": "need two blocks that use Jira", "count": 2},
    )
    job_id = start.json()["job_id"]

    parsed = _stream(client, f"/stream/{job_id}?key=test-key")
    data_events = [payload for kind, payload in parsed if kind == "data"]
    kinds = [payload["kind"] for payload in data_events]

    def first_index(kind):
        return kinds.index(kind)

    assert first_index("keyword_extraction_start") < first_index("keyword_extraction_done")
    assert first_index("keyword_extraction_done") < first_index("narrowing_done")
    assert first_index("narrowing_done") < first_index("plan_start")
    assert first_index("plan_start") < first_index("plan_done")
    assert first_index("plan_done") < first_index("plan")
    assert first_index("plan") < first_index("use")
    assert kinds.count("use") == 2
    assert first_index("use") < first_index("naming")

    plan_payload = next(payload for payload in data_events if payload["kind"] == "plan")
    assert plan_payload["data"]["steps"] == [
        {"order": 1, "action": "use", "block_id": "block_0", "criteria": None},
        {"order": 2, "action": "use", "block_id": "block_1", "criteria": None},
    ]

    assert parsed[-1][0] == "complete"
    assert parsed[-1][1]["status"] == "done"


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


def test_stream_and_cancel_behave_consistently_across_all_four_tools(settings, monkeypatch, fake_router):
    client = _client(settings, monkeypatch)

    fake_router(
        generate_module, FakeLLMClient(replies=["## Sheriff Outpost\n\nA frontier outpost.\n\n**Role:** nobody\n"])
    )
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
        "/mutate/start", params={"key": "test-key"}, json={"block_id": "watchtower", "criteria": "add an armory"}
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

    FilesystemBlockStorage(settings.blocks_path).save(
        Block(id="", body="## School\n\nTeaches children.\n\n**Rooms:**\n- Classroom\n"),
        filename_stem="school",
    )
    fake_router(compose_module, FakeLLMClient(replies=["school_result"]))
    comp_start = client.post("/compose/start", params={"key": "test-key"}, json={"use_ids": ["school"]})
    comp_job_id = comp_start.json()["job_id"]
    _wait_for_job(comp_job_id)

    for job_id in (gen_job_id, mut_job_id, dis_job_id, comp_job_id):
        parsed = _stream(client, f"/stream/{job_id}?key=test-key")
        data_events = [payload for kind, payload in parsed if kind == "data"]
        assert len(data_events) >= 1
        assert parsed[-1][0] == "complete"
        assert parsed[-1][1]["status"] == "done"

    response = client.get("/stream/does-not-exist", params={"key": "test-key"})
    assert response.status_code == 404

    for job_id in (gen_job_id, mut_job_id, dis_job_id):
        response = client.post(f"/cancel/{job_id}", params={"key": "test-key"})
        assert response.status_code == 400
        assert response.text == "This operation does not support cancellation."

    response = client.post(f"/cancel/{comp_job_id}", params={"key": "test-key"})
    assert response.status_code == 400
    assert response.text == "This operation is no longer running."

    response = client.post("/cancel/does-not-exist", params={"key": "test-key"})
    assert response.status_code == 404


def test_blocks_list_returns_all_blocks(settings, monkeypatch):
    store = FilesystemBlockStorage(settings.blocks_path)
    store.save(
        Block(id="", body="## Sheriff Outpost\n\nA frontier outpost.\n", tags=["law"], source="manual"),
        filename_stem="sheriff_outpost",
    )
    store.save(
        Block(id="", body="## Sawmill\n\nCuts logs.\n", schema="project_entry", source="generated"),
        filename_stem="sawmill",
    )
    client = _client(settings, monkeypatch)

    response = client.get("/blocks", params={"key": "test-key"})

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    by_id = {b["id"]: b for b in body}
    assert by_id["sheriff_outpost"]["name"] == "Sheriff Outpost"
    assert by_id["sheriff_outpost"]["tags"] == ["law"]
    assert by_id["sheriff_outpost"]["source"] == "manual"
    assert by_id["sawmill"]["schema"] == "project_entry"
    assert by_id["sawmill"]["source"] == "generated"
    assert "body" not in by_id["sheriff_outpost"]


def test_blocks_list_empty_library_returns_empty_list(settings, monkeypatch):
    client = _client(settings, monkeypatch)

    response = client.get("/blocks", params={"key": "test-key"})

    assert response.status_code == 200
    assert response.json() == []


def test_blocks_get_returns_full_content(settings, monkeypatch):
    store = FilesystemBlockStorage(settings.blocks_path)
    store.save(
        Block(id="", body="## Sheriff Outpost\n\nA frontier outpost.\n", tags=["law"]),
        filename_stem="sheriff_outpost",
    )
    client = _client(settings, monkeypatch)

    response = client.get("/blocks/sheriff_outpost", params={"key": "test-key"})

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "sheriff_outpost"
    assert body["body"].strip() == "## Sheriff Outpost\n\nA frontier outpost."
    assert body["created_by"] == "manual"


def test_blocks_get_rejects_unknown_id(settings, monkeypatch):
    client = _client(settings, monkeypatch)

    response = client.get("/blocks/does-not-exist", params={"key": "test-key"})

    assert response.status_code == 404


def test_blocks_list_rejects_missing_key(settings, monkeypatch):
    client = _client(settings, monkeypatch)

    response = client.get("/blocks")

    assert response.status_code == 422


def test_blocks_list_rejects_wrong_key(settings, monkeypatch):
    client = _client(settings, monkeypatch)

    response = client.get("/blocks", params={"key": "wrong-key"})

    assert response.status_code == 401


def test_blocks_get_rejects_missing_key(settings, monkeypatch):
    store = FilesystemBlockStorage(settings.blocks_path)
    store.save(Block(id="", body="## Sheriff Outpost\n\nA frontier outpost.\n"), filename_stem="sheriff_outpost")
    client = _client(settings, monkeypatch)

    response = client.get("/blocks/sheriff_outpost")

    assert response.status_code == 422


def test_blocks_get_rejects_wrong_key(settings, monkeypatch):
    store = FilesystemBlockStorage(settings.blocks_path)
    store.save(Block(id="", body="## Sheriff Outpost\n\nA frontier outpost.\n"), filename_stem="sheriff_outpost")
    client = _client(settings, monkeypatch)

    response = client.get("/blocks/sheriff_outpost", params={"key": "wrong-key"})

    assert response.status_code == 401


def test_results_list_returns_all_results(settings, monkeypatch):
    store = FilesystemResultStorage(settings.results_path)
    store.save(
        Result(id="", content="A quiet outpost.", name="Quiet Outpost", request="a small outpost"),
        filename_stem="quiet_outpost",
    )
    store.save(
        Result(id="", content="A busy sawmill town.", name="Sawmill Town", request="a logging town"),
        filename_stem="sawmill_town",
    )
    client = _client(settings, monkeypatch)

    response = client.get("/results", params={"key": "test-key"})

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    by_id = {r["id"]: r for r in body}
    assert by_id["quiet_outpost"]["name"] == "Quiet Outpost"
    assert by_id["quiet_outpost"]["request"] == "a small outpost"
    assert by_id["sawmill_town"]["request"] == "a logging town"
    assert "content" not in by_id["quiet_outpost"]


def test_results_list_empty_store_returns_empty_list(settings, monkeypatch):
    client = _client(settings, monkeypatch)

    response = client.get("/results", params={"key": "test-key"})

    assert response.status_code == 200
    assert response.json() == []


def test_results_get_returns_full_content_and_inputs(settings, monkeypatch):
    store = FilesystemResultStorage(settings.results_path)
    store.save(
        Result(
            id="",
            content="A quiet outpost.",
            name="Quiet Outpost",
            request="a small outpost",
            use_ids=["sheriff_outpost"],
            generate_criteria=["a trading post"],
            slots=[{"order": 1, "action": "use", "block_id": "sheriff_outpost"}],
        ),
        filename_stem="quiet_outpost",
    )
    client = _client(settings, monkeypatch)

    response = client.get("/results/quiet_outpost", params={"key": "test-key"})

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "quiet_outpost"
    assert body["content"] == "A quiet outpost."
    assert body["use_ids"] == ["sheriff_outpost"]
    assert body["generate_criteria"] == ["a trading post"]
    assert body["slots"] == [{"order": 1, "action": "use", "block_id": "sheriff_outpost"}]


def test_results_get_rejects_unknown_id(settings, monkeypatch):
    client = _client(settings, monkeypatch)

    response = client.get("/results/does-not-exist", params={"key": "test-key"})

    assert response.status_code == 404


def test_results_list_rejects_missing_key(settings, monkeypatch):
    client = _client(settings, monkeypatch)

    response = client.get("/results")

    assert response.status_code == 422


def test_results_list_rejects_wrong_key(settings, monkeypatch):
    client = _client(settings, monkeypatch)

    response = client.get("/results", params={"key": "wrong-key"})

    assert response.status_code == 401


def test_results_get_rejects_missing_key(settings, monkeypatch):
    store = FilesystemResultStorage(settings.results_path)
    store.save(Result(id="", content="A quiet outpost.", name="Quiet Outpost"), filename_stem="quiet_outpost")
    client = _client(settings, monkeypatch)

    response = client.get("/results/quiet_outpost")

    assert response.status_code == 422


def test_results_get_rejects_wrong_key(settings, monkeypatch):
    store = FilesystemResultStorage(settings.results_path)
    store.save(Result(id="", content="A quiet outpost.", name="Quiet Outpost"), filename_stem="quiet_outpost")
    client = _client(settings, monkeypatch)

    response = client.get("/results/quiet_outpost", params={"key": "wrong-key"})

    assert response.status_code == 401


def test_blocks_delete_removes_block(settings, monkeypatch):
    store = FilesystemBlockStorage(settings.blocks_path)
    store.save(Block(id="", body="## Sheriff Outpost\n\nA frontier outpost.\n"), filename_stem="sheriff_outpost")
    client = _client(settings, monkeypatch)

    response = client.delete("/blocks/sheriff_outpost", params={"key": "test-key"})

    assert response.status_code == 200
    assert response.json() == {"deleted": "sheriff_outpost"}
    assert client.get("/blocks", params={"key": "test-key"}).json() == []
    assert client.get("/blocks/sheriff_outpost", params={"key": "test-key"}).status_code == 404


def test_blocks_delete_rejects_unknown_id(settings, monkeypatch):
    client = _client(settings, monkeypatch)

    response = client.delete("/blocks/does-not-exist", params={"key": "test-key"})

    assert response.status_code == 404


def test_blocks_delete_twice_second_call_404s(settings, monkeypatch):
    store = FilesystemBlockStorage(settings.blocks_path)
    store.save(Block(id="", body="## Sheriff Outpost\n\nA frontier outpost.\n"), filename_stem="sheriff_outpost")
    client = _client(settings, monkeypatch)

    first = client.delete("/blocks/sheriff_outpost", params={"key": "test-key"})
    second = client.delete("/blocks/sheriff_outpost", params={"key": "test-key"})

    assert first.status_code == 200
    assert second.status_code == 404


def test_blocks_delete_leaves_referencing_result_untouched(settings, monkeypatch):
    block_store = FilesystemBlockStorage(settings.blocks_path)
    block_store.save(Block(id="", body="## Sheriff Outpost\n\nA frontier outpost.\n"), filename_stem="sheriff_outpost")
    result_store = FilesystemResultStorage(settings.results_path)
    result_store.save(
        Result(
            id="",
            content="A quiet outpost.",
            name="Quiet Outpost",
            request="a small outpost",
            use_ids=["sheriff_outpost"],
        ),
        filename_stem="quiet_outpost",
    )
    client = _client(settings, monkeypatch)

    response = client.delete("/blocks/sheriff_outpost", params={"key": "test-key"})

    assert response.status_code == 200
    still_there = client.get("/results/quiet_outpost", params={"key": "test-key"})
    assert still_there.status_code == 200
    assert still_there.json()["use_ids"] == ["sheriff_outpost"]


def test_blocks_delete_rejects_missing_key(settings, monkeypatch):
    store = FilesystemBlockStorage(settings.blocks_path)
    store.save(Block(id="", body="## Sheriff Outpost\n\nA frontier outpost.\n"), filename_stem="sheriff_outpost")
    client = _client(settings, monkeypatch)

    response = client.delete("/blocks/sheriff_outpost")

    assert response.status_code == 422


def test_blocks_delete_rejects_wrong_key(settings, monkeypatch):
    store = FilesystemBlockStorage(settings.blocks_path)
    store.save(Block(id="", body="## Sheriff Outpost\n\nA frontier outpost.\n"), filename_stem="sheriff_outpost")
    client = _client(settings, monkeypatch)

    response = client.delete("/blocks/sheriff_outpost", params={"key": "wrong-key"})

    assert response.status_code == 401


def test_results_delete_removes_result(settings, monkeypatch):
    store = FilesystemResultStorage(settings.results_path)
    store.save(Result(id="", content="A quiet outpost.", name="Quiet Outpost"), filename_stem="quiet_outpost")
    client = _client(settings, monkeypatch)

    response = client.delete("/results/quiet_outpost", params={"key": "test-key"})

    assert response.status_code == 200
    assert response.json() == {"deleted": "quiet_outpost"}
    assert client.get("/results", params={"key": "test-key"}).json() == []
    assert client.get("/results/quiet_outpost", params={"key": "test-key"}).status_code == 404


def test_results_delete_rejects_unknown_id(settings, monkeypatch):
    client = _client(settings, monkeypatch)

    response = client.delete("/results/does-not-exist", params={"key": "test-key"})

    assert response.status_code == 404


def test_results_delete_twice_second_call_404s(settings, monkeypatch):
    store = FilesystemResultStorage(settings.results_path)
    store.save(Result(id="", content="A quiet outpost.", name="Quiet Outpost"), filename_stem="quiet_outpost")
    client = _client(settings, monkeypatch)

    first = client.delete("/results/quiet_outpost", params={"key": "test-key"})
    second = client.delete("/results/quiet_outpost", params={"key": "test-key"})

    assert first.status_code == 200
    assert second.status_code == 404


def test_results_delete_rejects_missing_key(settings, monkeypatch):
    store = FilesystemResultStorage(settings.results_path)
    store.save(Result(id="", content="A quiet outpost.", name="Quiet Outpost"), filename_stem="quiet_outpost")
    client = _client(settings, monkeypatch)

    response = client.delete("/results/quiet_outpost")

    assert response.status_code == 422


def test_results_delete_rejects_wrong_key(settings, monkeypatch):
    store = FilesystemResultStorage(settings.results_path)
    store.save(Result(id="", content="A quiet outpost.", name="Quiet Outpost"), filename_stem="quiet_outpost")
    client = _client(settings, monkeypatch)

    response = client.delete("/results/quiet_outpost", params={"key": "wrong-key"})

    assert response.status_code == 401


def test_blocks_update_replaces_content(settings, monkeypatch):
    store = FilesystemBlockStorage(settings.blocks_path)
    store.save(
        Block(
            id="",
            body="## Sheriff Outpost\n\nA frontier outpost.\n",
            tags=["frontier"],
            schema="project_entry",
            source="generated",
            created_by="generate",
            generation_criteria="a lonely watchtower",
        ),
        filename_stem="sheriff_outpost",
    )
    client = _client(settings, monkeypatch)

    response = client.put(
        "/blocks/sheriff_outpost",
        params={"key": "test-key"},
        json={"body": "## Sheriff Outpost\n\nRebuilt after the storm.\n"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "sheriff_outpost"
    assert body["body"].strip() == "## Sheriff Outpost\n\nRebuilt after the storm."
    assert body["source"] == "generated"
    assert body["created_by"] == "generate"
    assert body["generation_criteria"] == "a lonely watchtower"
    assert body["mutated_from"] is None

    fetched = client.get("/blocks/sheriff_outpost", params={"key": "test-key"}).json()
    assert fetched["body"].strip() == "## Sheriff Outpost\n\nRebuilt after the storm."
    assert fetched["source"] == "generated"


def test_blocks_update_partial_tags_and_schema(settings, monkeypatch):
    store = FilesystemBlockStorage(settings.blocks_path)
    store.save(
        Block(id="", body="## Sheriff Outpost\n\nA frontier outpost.\n", tags=["frontier"], schema="project_entry"),
        filename_stem="sheriff_outpost",
    )
    client = _client(settings, monkeypatch)

    omitted = client.put(
        "/blocks/sheriff_outpost",
        params={"key": "test-key"},
        json={"body": "## Sheriff Outpost\n\nStill standing.\n"},
    )
    assert omitted.status_code == 200
    assert omitted.json()["tags"] == ["frontier"]
    assert omitted.json()["schema"] == "project_entry"

    tags_only = client.put(
        "/blocks/sheriff_outpost",
        params={"key": "test-key"},
        json={"body": "## Sheriff Outpost\n\nStill standing.\n", "tags": ["frontier", "coastal"]},
    )
    assert tags_only.status_code == 200
    assert tags_only.json()["tags"] == ["frontier", "coastal"]
    assert tags_only.json()["schema"] == "project_entry"


def test_blocks_update_rejects_unknown_id(settings, monkeypatch):
    client = _client(settings, monkeypatch)

    response = client.put(
        "/blocks/does-not-exist", params={"key": "test-key"}, json={"body": "New content."}
    )

    assert response.status_code == 404
    assert client.get("/blocks", params={"key": "test-key"}).json() == []


def test_blocks_update_rejects_empty_body(settings, monkeypatch):
    store = FilesystemBlockStorage(settings.blocks_path)
    store.save(Block(id="", body="## Sheriff Outpost\n\nA frontier outpost.\n"), filename_stem="sheriff_outpost")
    client = _client(settings, monkeypatch)

    response = client.put("/blocks/sheriff_outpost", params={"key": "test-key"}, json={"body": "   "})

    assert response.status_code == 400


def test_blocks_update_rejects_missing_key(settings, monkeypatch):
    store = FilesystemBlockStorage(settings.blocks_path)
    store.save(Block(id="", body="## Sheriff Outpost\n\nA frontier outpost.\n"), filename_stem="sheriff_outpost")
    client = _client(settings, monkeypatch)

    response = client.put("/blocks/sheriff_outpost", json={"body": "New content."})

    assert response.status_code == 422


def test_blocks_update_rejects_wrong_key(settings, monkeypatch):
    store = FilesystemBlockStorage(settings.blocks_path)
    store.save(Block(id="", body="## Sheriff Outpost\n\nA frontier outpost.\n"), filename_stem="sheriff_outpost")
    client = _client(settings, monkeypatch)

    response = client.put(
        "/blocks/sheriff_outpost", params={"key": "wrong-key"}, json={"body": "New content."}
    )

    assert response.status_code == 401


def test_generate_start_threads_explicit_name_into_run_generate(settings, monkeypatch):
    client = _client(settings, monkeypatch)
    captured = {}

    def fake_run_generate(*args, **kwargs):
        captured["kwargs"] = kwargs
        block = Block(id="widget", body="## Widget\n\nA widget.\n\n**Role:** nobody\n")
        return block, NamingDecision(action="save_plain", stem="widget"), "widget"

    monkeypatch.setattr(generate_module, "run_generate", fake_run_generate)

    response = client.post(
        "/generate/start",
        params={"key": "test-key"},
        json={"criteria": "a sheriff outpost", "name": "widget"},
    )

    assert response.status_code == 200
    job = _wait_for_job(response.json()["job_id"])
    assert job.status == "done"
    assert captured["kwargs"]["name"] == "widget"


def test_generate_start_rejects_degenerate_name_synchronously(settings, monkeypatch):
    client = _client(settings, monkeypatch)
    jobs_before = len(web_jobs._jobs)

    response = client.post(
        "/generate/start",
        params={"key": "test-key"},
        json={"criteria": "a sheriff outpost", "name": "!!!"},
    )

    assert response.status_code == 400
    assert len(web_jobs._jobs) == jobs_before


def test_mutate_start_rejects_name_combined_with_in_place(settings, monkeypatch):
    FilesystemBlockStorage(settings.blocks_path).save(
        Block(id="", body="## Police Station\n\nRegular station.\n\n**Rooms:**\n- Office\n"),
        filename_stem="police_station",
    )
    client = _client(settings, monkeypatch)
    jobs_before = len(web_jobs._jobs)

    response = client.post(
        "/mutate/start",
        params={"key": "test-key"},
        json={"block_id": "police_station", "criteria": "add an armory", "name": "widget", "in_place": True},
    )

    assert response.status_code == 400
    assert response.text == "name cannot be combined with in_place."
    assert len(web_jobs._jobs) == jobs_before


def test_compose_start_threads_explicit_name_into_run_compose(settings, monkeypatch):
    FilesystemBlockStorage(settings.blocks_path).save(
        Block(id="", body="## School\n\nTeaches children.\n\n**Rooms:**\n- Classroom\n"),
        filename_stem="school",
    )
    client = _client(settings, monkeypatch)
    captured = {}

    def fake_run_compose(*args, **kwargs):
        captured["kwargs"] = kwargs
        return compose_module.ComposeOutcome(
            slots=[], result_path=None, result_id="result-1", name="My Result", content="content", cancelled=False
        )

    monkeypatch.setattr(compose_module, "run_compose", fake_run_compose)

    response = client.post(
        "/compose/start",
        params={"key": "test-key"},
        json={"use_ids": ["school"], "name": "My Result"},
    )

    assert response.status_code == 200
    job = _wait_for_job(response.json()["job_id"])
    assert job.status == "done"
    assert captured["kwargs"]["name"] == "My Result"
