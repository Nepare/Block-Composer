import asyncio
import json
import threading

from web import web_jobs
from core.errors import CvdocsError
from core.progress import ProgressEvent


def _collect(gen):
    async def _run():
        return [item async for item in gen]

    return asyncio.run(_run())


def _parse_sse(chunks):
    parsed = []
    for chunk in chunks:
        kind = "complete" if chunk.startswith("event: complete") else "data"
        payload = json.loads(chunk.split("data: ", 1)[1].strip())
        parsed.append((kind, payload))
    return parsed


def test_events_buffered_before_reader_connects_are_still_delivered_in_order():
    started = threading.Event()
    release = threading.Event()

    def work(on_progress, cancel_event):
        on_progress(ProgressEvent(kind="step_one", message="first"))
        on_progress(ProgressEvent(kind="step_two", message="second"))
        started.set()
        release.wait(timeout=5)
        return {"result": "ok"}

    job = web_jobs.start_job(work)
    assert started.wait(timeout=5)
    # both events already sitting in the queue -- nothing has consumed them yet
    assert job.queue.qsize() == 2

    release.set()
    parsed = _parse_sse(_collect(web_jobs.sse_events(job)))

    assert [kind for kind, _ in parsed] == ["data", "data", "complete"]
    assert parsed[0][1]["kind"] == "step_one"
    assert parsed[1][1]["kind"] == "step_two"
    assert parsed[2][1] == {"status": "done", "result": "ok"}


def test_successful_job_reports_done_status_with_outcome():
    def work(on_progress, cancel_event):
        return {"foo": "bar"}

    job = web_jobs.start_job(work)
    parsed = _parse_sse(_collect(web_jobs.sse_events(job)))

    assert parsed[-1] == ("complete", {"status": "done", "foo": "bar"})
    assert job.status == "done"


def test_failing_job_reports_error_status_and_still_terminates():
    def work(on_progress, cancel_event):
        raise CvdocsError("boom")

    job = web_jobs.start_job(work)
    parsed = _parse_sse(_collect(web_jobs.sse_events(job)))

    assert parsed[-1] == ("complete", {"status": "error", "error": "boom"})
    assert job.status == "error"


def test_get_job_returns_the_registered_job():
    def work(on_progress, cancel_event):
        return {}

    job = web_jobs.start_job(work)
    _collect(web_jobs.sse_events(job))  # drain so the worker thread isn't left lingering

    assert web_jobs.get_job(job.id) is job


def test_get_job_returns_none_for_unknown_id():
    assert web_jobs.get_job("does-not-exist") is None


def test_start_job_defaults_to_no_cancel_event_and_passes_none_to_work():
    received = {}

    def work(on_progress, cancel_event):
        received["cancel_event"] = cancel_event
        return {}

    job = web_jobs.start_job(work)
    _collect(web_jobs.sse_events(job))

    assert job.cancel_event is None
    assert received["cancel_event"] is None


def test_start_job_with_cancellable_true_creates_a_real_cancel_event():
    def work(on_progress, cancel_event):
        return {}

    job = web_jobs.start_job(work, cancellable=True)
    _collect(web_jobs.sse_events(job))

    assert isinstance(job.cancel_event, threading.Event)


def test_worker_reports_cancelled_status_when_outcome_marks_it_cancelled():
    def work(on_progress, cancel_event):
        return {"cancelled": True, "block_id": "x"}

    job = web_jobs.start_job(work)
    parsed = _parse_sse(_collect(web_jobs.sse_events(job)))

    assert job.status == "cancelled"
    assert parsed[-1] == ("complete", {"status": "cancelled", "cancelled": True, "block_id": "x"})


def test_worker_reports_done_status_when_outcome_has_no_cancelled_key():
    def work(on_progress, cancel_event):
        return {"block_id": "x"}

    job = web_jobs.start_job(work)
    _collect(web_jobs.sse_events(job))

    assert job.status == "done"


def test_event_json_includes_data_field_defaulting_to_none():
    payload = json.loads(web_jobs._event_json(ProgressEvent(kind="step", message="m")))

    assert payload["data"] is None


def test_event_json_includes_data_field_when_set():
    payload = json.loads(
        web_jobs._event_json(ProgressEvent(kind="step", message="m", data={"foo": "bar"}))
    )

    assert payload["data"] == {"foo": "bar"}
