import json
from unittest.mock import MagicMock, patch

import pytest

from config import Settings
from errors import LLMError
from llm.logging_client import LoggingLLMClient
from llm.providers.ollama import OllamaClient
from llm.providers.openrouter import OpenRouterClient
from llm.router import get_client_and_model


def _fake_openai_response(text):
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=text))]
    return resp


def _fake_urlopen_cm(payload: dict):
    cm = MagicMock()
    cm.__enter__.return_value.read.return_value = json.dumps(payload).encode("utf-8")
    return cm


@patch("llm.providers.openrouter.OpenAI")
def test_openrouter_chat_returns_content_and_passes_model_through(mock_openai_cls):
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _fake_openai_response("hello")
    mock_openai_cls.return_value = mock_client

    client = OpenRouterClient(api_key="sk-test")
    result = client.chat([{"role": "user", "content": "hi"}], "openrouter/free")

    assert result == "hello"
    _, kwargs = mock_client.chat.completions.create.call_args
    assert kwargs["model"] == "openrouter/free"


@patch("llm.providers.openrouter.OpenAI")
def test_openrouter_raises_without_api_key_before_calling_the_sdk(mock_openai_cls):
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client

    client = OpenRouterClient(api_key="")
    with pytest.raises(LLMError):
        client.chat([{"role": "user", "content": "hi"}], "openrouter/free")

    mock_client.chat.completions.create.assert_not_called()


@patch("llm.providers.openrouter.OpenAI")
def test_openrouter_wraps_sdk_exceptions_as_llmerror(mock_openai_cls):
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = RuntimeError("boom")
    mock_openai_cls.return_value = mock_client

    client = OpenRouterClient(api_key="sk-test")
    with pytest.raises(LLMError):
        client.chat([{"role": "user", "content": "hi"}], "openrouter/free")


@patch("llm.providers.ollama.urllib.request.urlopen")
def test_ollama_chat_returns_content_with_no_api_key_needed(mock_urlopen):
    mock_urlopen.return_value = _fake_urlopen_cm({"message": {"content": "local reply"}})

    client = OllamaClient(base_url="http://localhost:11434")
    result = client.chat([{"role": "user", "content": "hi"}], "qwen3:1.7b")

    assert result == "local reply"


@patch("llm.providers.ollama.urllib.request.urlopen")
def test_ollama_disables_thinking_and_passes_options_through(mock_urlopen):
    """Verified live against a real Qwen3 model: without `think: false`, a hybrid-
    reasoning model can burn its whole token budget on invisible thinking and return
    nothing — this must be sent on every request, not just opt-in."""
    mock_urlopen.return_value = _fake_urlopen_cm({"message": {"content": "ok"}})

    client = OllamaClient()
    client.chat([{"role": "user", "content": "hi"}], "qwen3:1.7b", temperature=0.2, max_tokens=40)

    request = mock_urlopen.call_args[0][0]
    body = json.loads(request.data)
    assert body["model"] == "qwen3:1.7b"
    assert body["think"] is False
    assert body["options"]["temperature"] == 0.2
    assert body["options"]["num_predict"] == 40


@patch("llm.providers.ollama.urllib.request.urlopen")
def test_ollama_wraps_connection_errors_as_llmerror(mock_urlopen):
    mock_urlopen.side_effect = RuntimeError("connection refused")

    client = OllamaClient()
    with pytest.raises(LLMError):
        client.chat([{"role": "user", "content": "hi"}], "qwen3:1.7b")


@patch("llm.providers.openrouter.OpenAI")
def test_router_dispatches_by_provider_and_caches_per_provider_not_per_model(mock_openrouter_openai):
    settings = Settings()

    client1, model1 = get_client_and_model("openrouter:openrouter/free", settings)
    client2, model2 = get_client_and_model("openrouter:z-ai/glm-5.3", settings)
    assert model1 == "openrouter/free"
    assert model2 == "z-ai/glm-5.3"
    assert client1 is client2  # same cached OpenRouter client regardless of model id

    client3, model3 = get_client_and_model("ollama:qwen3-coder-next", settings)
    assert model3 == "qwen3-coder-next"
    assert client3 is not client1


def test_router_rejects_spec_without_provider_prefix():
    with pytest.raises(LLMError):
        get_client_and_model("not-a-valid-spec", Settings())


def test_router_rejects_unknown_provider():
    with pytest.raises(LLMError):
        get_client_and_model("mystery:model", Settings())


@patch("llm.providers.openrouter.OpenAI")
def test_router_wraps_with_logging_client_when_on_progress_is_given(mock_openai_cls):
    client, model = get_client_and_model(
        "openrouter:openrouter/free", Settings(), on_progress=lambda e: None
    )

    assert isinstance(client, LoggingLLMClient)
    assert model == "openrouter/free"


@patch("llm.providers.openrouter.OpenAI")
def test_router_does_not_wrap_when_on_progress_is_omitted(mock_openai_cls):
    client, _model = get_client_and_model("openrouter:openrouter/free", Settings())

    assert not isinstance(client, LoggingLLMClient)


@patch("llm.providers.openrouter.OpenAI")
def test_router_wrapping_does_not_disturb_the_cached_raw_client(mock_openai_cls):
    plain_client, _ = get_client_and_model("openrouter:openrouter/free", Settings())
    wrapped_client, _ = get_client_and_model(
        "openrouter:openrouter/free", Settings(), on_progress=lambda e: None
    )

    assert wrapped_client._inner is plain_client
