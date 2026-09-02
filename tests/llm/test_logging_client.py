import pytest

from fakes import FakeLLMClient
from llm.logging_client import LoggingLLMClient
from core.progress import ProgressEvent


def test_logging_client_emits_start_and_done_around_a_successful_call():
    inner = FakeLLMClient(replies=["hello"])
    events: list[ProgressEvent] = []
    client = LoggingLLMClient(inner, events.append)

    result = client.chat([{"role": "user", "content": "hi"}], "some-model")

    assert result == "hello"
    assert [e.kind for e in events] == ["llm_call_start", "llm_call_done"]
    assert events[0].model == "some-model"
    assert events[1].model == "some-model"
    assert events[1].latency_ms is not None and events[1].latency_ms >= 0


def test_logging_client_emits_error_event_and_reraises_on_failure():
    class BrokenClient:
        def chat(self, *args, **kwargs):
            raise RuntimeError("boom")

    events: list[ProgressEvent] = []
    client = LoggingLLMClient(BrokenClient(), events.append)

    with pytest.raises(RuntimeError):
        client.chat([{"role": "user", "content": "hi"}], "some-model")

    assert [e.kind for e in events] == ["llm_call_start", "llm_call_error"]
    assert events[1].error == "boom"


def test_logging_client_delegates_call_tracking_to_the_inner_client():
    inner = FakeLLMClient(replies=["a", "b"])
    client = LoggingLLMClient(inner, lambda _e: None)

    client.chat([{"role": "user", "content": "1"}], "m")
    client.chat([{"role": "user", "content": "2"}], "m")

    assert inner.call_count == 2
