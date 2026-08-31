class FakeLLMClient:
    """A stand-in LLMClient that replays scripted replies in order — no network, no key.

    Raises if asked for more replies than were scripted, so a test expecting N calls that
    actually triggers N+1 fails loudly instead of silently reusing a stale reply.
    """

    def __init__(self, replies: list[str] | None = None):
        self.replies = list(replies) if replies else []
        self.calls: list[dict] = []

    def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        *,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> str:
        self.calls.append(
            {"messages": messages, "model": model, "temperature": temperature, "max_tokens": max_tokens}
        )
        if not self.replies:
            raise AssertionError("FakeLLMClient ran out of scripted replies")
        return self.replies.pop(0)

    @property
    def call_count(self) -> int:
        return len(self.calls)
