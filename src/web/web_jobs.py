import asyncio
import json
import queue
import threading
import uuid
from dataclasses import dataclass, field
from typing import Callable

from core.errors import CvdocsError
from core.progress import ProgressEvent


@dataclass
class Job:
    id: str
    queue: "queue.Queue" = field(default_factory=queue.Queue)
    status: str = "running"  # running | done | error
    outcome: dict = field(default_factory=dict)


_jobs: dict[str, Job] = {}
_jobs_lock = threading.Lock()


def start_job(work: Callable[[Callable[[ProgressEvent], None]], dict]) -> Job:
    job = Job(id=str(uuid.uuid4()))
    with _jobs_lock:
        _jobs[job.id] = job

    def worker() -> None:
        try:
            job.outcome = work(job.queue.put)
            job.status = "done"
        except CvdocsError as exc:
            job.outcome = {"error": str(exc)}
            job.status = "error"
        finally:
            job.queue.put(None)  # terminal sentinel

    threading.Thread(target=worker, daemon=True).start()
    return job


def get_job(job_id: str) -> Job | None:
    return _jobs.get(job_id)


def _event_json(event: ProgressEvent) -> str:
    return json.dumps(
        {
            "kind": event.kind,
            "message": event.message,
            "step": event.step,
            "total": event.total,
            "block_id": event.block_id,
            "at": event.at.isoformat(),
        }
    )


async def sse_events(job: Job):
    loop = asyncio.get_running_loop()
    while True:
        event = await loop.run_in_executor(None, job.queue.get)
        if event is None:
            break
        yield f"data: {_event_json(event)}\n\n"
    final = {"status": job.status, **job.outcome}
    yield f"event: complete\ndata: {json.dumps(final)}\n\n"
