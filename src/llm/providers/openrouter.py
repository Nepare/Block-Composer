from openai import OpenAI

from errors import LLMError


class OpenRouterClient:
    """OpenRouter is OpenAI-API-compatible, so this is just the `openai` SDK pointed at
    OpenRouter's base_url with an OpenRouter key — no bespoke HTTP client needed."""

    def __init__(self, api_key: str, base_url: str = "https://openrouter.ai/api/v1"):
        self._api_key = api_key
        self._client = OpenAI(
            api_key=api_key or "unset",
            base_url=base_url,
            default_headers={"HTTP-Referer": "https://github.com/cvdocs", "X-Title": "cvdocs"},
        )

    def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        *,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> str:
        if not self._api_key:
            raise LLMError(
                "OPENROUTER_API_KEY is not set — add it to .env. The free tier costs $0 "
                "but still needs a key from https://openrouter.ai/keys."
            )
        try:
            response = self._client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            raise LLMError(f"OpenRouter request failed ({model}): {exc}") from exc
        return response.choices[0].message.content or ""
