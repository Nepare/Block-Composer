"""Wraps any LLMClient to emit llm_call_start/done/error ProgressEvents around chat() calls."""

import time

from llm.client import LLMClient
from core.progress import ProgressEvent, ProgressSink


class LoggingLLMClient:
    def __init__(self, inner: LLMClient, on_progress: ProgressSink) -> None:
        self._inner = inner
        self._on_progress = on_progress

    def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        *,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> str:
        self._on_progress(ProgressEvent(kind="llm_call_start", message=f"Calling {model}…", model=model))
        start = time.monotonic()
        try:
            reply = self._inner.chat(messages, model, temperature=temperature, max_tokens=max_tokens)
        except Exception as exc:
            latency_ms = (time.monotonic() - start) * 1000
            self._on_progress(
                ProgressEvent(
                    kind="llm_call_error",
                    message=f"{model} call failed: {exc}",
                    model=model,
                    latency_ms=latency_ms,
                    error=str(exc),
                )
            )
            raise
        latency_ms = (time.monotonic() - start) * 1000
        self._on_progress(
            ProgressEvent(kind="llm_call_done", message=f"{model} responded", model=model, latency_ms=latency_ms)
        )
        return reply
