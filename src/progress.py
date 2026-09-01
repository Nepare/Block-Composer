"""Structured, pluggable progress/diagnostic events — replaces the old bare
Callable[[str], None] callback. One event schema serves both the user-facing narrative
(compose/generate/mutate/dissect's own progress calls) and LLM-call diagnostics (see
llm/logging_client.py), so there's one persisted trail instead of two mechanisms to
reconcile later for a web UI's plan/log display.
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from rich.console import Console
from rich.markup import escape


@dataclass(frozen=True)
class ProgressEvent:
    kind: str  # "plan_start" | "plan_retry" | "plan_done" | "keyword_extraction" |
    # "narrowing" | "use" | "mutate_start" | "mutate_retry" | "mutate_done" |
    # "generate_start" | "generate_retry" | "generate_done" | "naming" | "dissect_row" |
    # "result_saved" | "cancelled" | "error" | "llm_call_start" | "llm_call_done" |
    # "llm_call_error"
    message: str
    step: int | None = None
    total: int | None = None
    block_id: str | None = None
    # diagnostic-only fields, populated by llm_call_* events, ignored by narrative sinks:
    model: str | None = None
    latency_ms: float | None = None
    token_usage: dict | None = None
    error: str | None = None
    at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ProgressSink(Protocol):
    def __call__(self, event: ProgressEvent) -> None: ...


class RichConsoleSink:
    """Prints the user-facing narrative to a Rich console — the CLI's default sink.
    LLM-call diagnostic events (kind starting "llm_call_") are deliberately not printed
    here; they're too fine-grained for a scrolling console and belong in a log sink."""

    def __init__(self, console: Console) -> None:
        self._console = console

    def __call__(self, event: ProgressEvent) -> None:
        if event.kind.startswith("llm_call_"):
            return
        style = "red" if event.kind in ("error", "cancelled") else "dim"
        self._console.print(f"[{style}]{escape(event.message)}[/{style}]")


class FileProgressSink:
    """Appends every event, including LLM-call diagnostics, as one JSON object per line
    — directly replayable into a future persisted plan/progress UI without a second
    parser. Not wired in anywhere by default; a caller opts in by constructing one."""

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
