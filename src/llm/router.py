from config import Settings
from errors import LLMError
from llm.client import LLMClient
from llm.logging_client import LoggingLLMClient
from llm.providers.ollama import OllamaClient
from llm.providers.openrouter import OpenRouterClient
from progress import ProgressSink

_clients: dict[str, LLMClient] = {}


def get_client_and_model(
    spec: str, settings: Settings, on_progress: ProgressSink | None = None
) -> tuple[LLMClient, str]:
    """Split a "provider:model-id" spec and return a cached client for that provider —
    the one chokepoint every task-level model setting flows through, hosted or local.
    When `on_progress` is given, the returned client is wrapped (not cached) in
    LoggingLLMClient so every chat() call emits llm_call_* progress events — the raw
    client stays cached so connection reuse is unaffected by whether logging is
    requested on a given call."""
    if ":" not in spec:
        raise LLMError(
            f"Model spec {spec!r} must be 'provider:model-id', e.g. 'openrouter:openrouter/free'."
        )
    provider, model = spec.split(":", 1)
    if provider not in _clients:
        if provider == "openrouter":
            _clients[provider] = OpenRouterClient(
                api_key=settings.openrouter.api_key, base_url=settings.openrouter.base_url
            )
        elif provider == "ollama":
            _clients[provider] = OllamaClient(base_url=settings.ollama.base_url)
        else:
            raise LLMError(f"Unknown provider {provider!r} in model spec {spec!r}.")
    client = _clients[provider]
    if on_progress is not None:
        client = LoggingLLMClient(client, on_progress)
    return client, model
