from core.config import Settings
from core.errors import LLMError
from llm.client import LLMClient
from llm.logging_client import LoggingLLMClient
from llm.providers.ollama import OllamaClient
from llm.providers.openrouter import OpenRouterClient
from core.progress import ProgressSink

_clients: dict[str, LLMClient] = {}


def get_client_and_model(
    spec: str, settings: Settings, on_progress: ProgressSink | None = None
) -> tuple[LLMClient, str]:
    """Splits a "provider:model-id" spec and returns a cached client for that provider,
    wrapped in LoggingLLMClient (uncached) when `on_progress` is given."""
    if ":" not in spec:
        raise LLMError(
            f"Model spec {spec!r} must be 'provider:model-id', e.g. 'openrouter:openrouter/free'."
        )
    provider, model = spec.split(":", 1)
    if provider not in _clients:
        if provider == "openrouter":
            _clients[provider] = OpenRouterClient(
                api_key=settings.llm.openrouter.api_key, base_url=settings.llm.openrouter.base_url
            )
        elif provider == "ollama":
            _clients[provider] = OllamaClient(base_url=settings.llm.ollama.base_url)
        else:
            raise LLMError(f"Unknown provider {provider!r} in model spec {spec!r}.")
    client = _clients[provider]
    if on_progress is not None:
        client = LoggingLLMClient(client, on_progress)
    return client, model
