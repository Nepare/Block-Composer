import asyncio
import json
import threading

import web_jobs
from errors import CvdocsError
from progress import ProgressEvent


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

    def work(on_progress):
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
    def work(on_progress):
        return {"foo": "bar"}

    job = web_jobs.start_job(work)
    parsed = _parse_sse(_collect(web_jobs.sse_events(job)))

    assert parsed[-1] == ("complete", {"status": "done", "foo": "bar"})
    assert job.status == "done"


def test_failing_job_reports_error_status_and_still_terminates():
    def work(on_progress):
        raise CvdocsError("boom")

    job = web_jobs.start_job(work)
    parsed = _parse_sse(_collect(web_jobs.sse_events(job)))

    assert parsed[-1] == ("complete", {"status": "error", "error": "boom"})
    assert job.status == "error"


def test_get_job_returns_the_registered_job():
    def work(on_progress):
        return {}

    job = web_jobs.start_job(work)
    _collect(web_jobs.sse_events(job))  # drain so the worker thread isn't left lingering

    assert web_jobs.get_job(job.id) is job


def test_get_job_returns_none_for_unknown_id():
    assert web_jobs.get_job("does-not-exist") is None
