from typing import Protocol


class LLMClient(Protocol):
    def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        *,
        temperature: float = 0.3,
        max_tokens: int | None = None,
        reasoning_effort: str | None = None,
    ) -> str: ...
