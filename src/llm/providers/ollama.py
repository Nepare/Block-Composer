import json
import re
import urllib.request

from core.errors import LLMError

_LEADING_THINK_BLOCK = re.compile(r"^\s*<think>.*?</think>\s*", re.DOTALL)


class OllamaClient:
    """Talks to Ollama's native /api/chat endpoint — its `think: false` reliably suppresses
    hybrid-reasoning models' invisible-thinking token burn, unlike the OpenAI-compatible shim."""

    def __init__(self, base_url: str = "http://localhost:11434"):
        self._base_url = base_url.rstrip("/")

    def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        *,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> str:
        options = {"temperature": temperature}
        if max_tokens is not None:
            options["num_predict"] = max_tokens
        payload = {
            "model": model,
            "messages": messages,
            "think": False,
            "stream": False,
            "options": options,
        }
        req = urllib.request.Request(
            f"{self._base_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read())
        except Exception as exc:
            raise LLMError(
                f"Ollama request failed ({model}) — is `ollama serve` running and is the "
                f"model pulled (`ollama pull {model}`)? {exc}"
            ) from exc
        content = data.get("message", {}).get("content") or ""
        # some builds ignore `think: false` and emit a leading <think> block anyway
        return _LEADING_THINK_BLOCK.sub("", content, count=1)
