from unittest.mock import MagicMock, patch

import pytest

from config import Settings
from errors import LLMError
from llm.providers.ollama import OllamaClient
from llm.providers.openrouter import OpenRouterClient
from llm.router import get_client_and_model


def _fake_openai_response(text):
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=text))]
    return resp


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


@patch("llm.providers.ollama.OpenAI")
def test_ollama_chat_returns_content_with_no_api_key_needed(mock_openai_cls):
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _fake_openai_response("local reply")
    mock_openai_cls.return_value = mock_client

    client = OllamaClient(base_url="http://localhost:11434")
    result = client.chat([{"role": "user", "content": "hi"}], "qwen3-coder-next")

    assert result == "local reply"


@patch("llm.providers.ollama.OpenAI")
def test_ollama_wraps_connection_errors_as_llmerror(mock_openai_cls):
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = RuntimeError("connection refused")
    mock_openai_cls.return_value = mock_client

    client = OllamaClient()
    with pytest.raises(LLMError):
        client.chat([{"role": "user", "content": "hi"}], "qwen3-coder-next")


@patch("llm.providers.ollama.OpenAI")
@patch("llm.providers.openrouter.OpenAI")
def test_router_dispatches_by_provider_and_caches_per_provider_not_per_model(
    mock_openrouter_openai, mock_ollama_openai
):
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
