from openai import OpenAI

from core.errors import LLMError


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

        # One retry: a free/auto-routed model can land on a different provider each call,
        # and OpenRouter sometimes returns choices: null with HTTP 200 instead of raising.
        last_error_detail = None
        for attempt in range(2):
            try:
                response = self._client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    extra_body={"reasoning": {"exclude": True}},
                )
            except Exception as exc:
                raise LLMError(f"OpenRouter request failed ({model}): {exc}") from exc

            if not response.choices:
                err = getattr(response, "error", None)
                last_error_detail = getattr(err, "message", None) or str(err) if err else "no choices returned"
                continue

            choice = response.choices[0]
            content = choice.message.content or ""
            if content or choice.finish_reason != "length":
                return content
            last_error_detail = f"used its whole token budget (max_tokens={max_tokens}) without producing output"

        raise LLMError(
            f"OpenRouter model {model!r} failed twice in a row: {last_error_detail}. "
            "Retry, raise max_tokens, or pick a different model."
        )
