"""One event schema for both the user-facing tool narrative and LLM-call diagnostics
(see llm/logging_client.py)."""

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from rich.console import Console
from rich.markup import escape


@dataclass(frozen=True)
class ProgressEvent:
    kind: str
    message: str
    step: int | None = None
    total: int | None = None
    block_id: str | None = None
    data: dict | None = None
    # diagnostic-only fields, populated by llm_call_* events, ignored by narrative sinks:
    model: str | None = None
    latency_ms: float | None = None
    token_usage: dict | None = None
    error: str | None = None
    at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ProgressSink(Protocol):
    def __call__(self, event: ProgressEvent) -> None: ...


class RichConsoleSink:
    """Prints the narrative to a Rich console; skips llm_call_* diagnostic events."""

    def __init__(self, console: Console) -> None:
        self._console = console

    def __call__(self, event: ProgressEvent) -> None:
        if event.kind.startswith("llm_call_"):
            return
        style = "red" if event.kind in ("error", "cancelled") else "dim"
        self._console.print(f"[{style}]{escape(event.message)}[/{style}]")


class FileProgressSink:
    """Appends every event as one JSON object per line; not wired in by default."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, event: ProgressEvent) -> None:
        record = asdict(event)
        record["at"] = event.at.isoformat()
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")


class MultiSink:
    """Fans one event out to several sinks at once, e.g. console + file."""

    def __init__(self, *sinks: ProgressSink) -> None:
        self._sinks = sinks

    def __call__(self, event: ProgressEvent) -> None:
        for sink in self._sinks:
            sink(event)
