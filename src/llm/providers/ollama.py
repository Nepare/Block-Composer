from openai import OpenAI

from errors import LLMError


class OllamaClient:
    """Modern Ollama exposes an OpenAI-compatible /v1/chat/completions endpoint, so this
    is the same `openai` SDK shape as OpenRouterClient, just pointed at localhost."""

    def __init__(self, base_url: str = "http://localhost:11434"):
        self._client = OpenAI(api_key="ollama", base_url=f"{base_url.rstrip('/')}/v1")

    def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        *,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> str:
        try:
            response = self._client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            raise LLMError(
                f"Ollama request failed ({model}) — is `ollama serve` running and is the "
                f"model pulled (`ollama pull {model}`)? {exc}"
            ) from exc
        return response.choices[0].message.content or ""
