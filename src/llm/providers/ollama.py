import json
import urllib.request

from errors import LLMError


class OllamaClient:
    """Talks to Ollama's native /api/chat endpoint rather than its OpenAI-compatible
    shim. Verified directly: hybrid-reasoning local models (Qwen3 included) default to
    "thinking" mode, which can burn an entire token budget on invisible reasoning and
    return nothing — Ollama's native API reliably suppresses this via `think: false`;
    passing the same flag through the OpenAI-compatible endpoint via `extra_body` was
    tested and does NOT suppress it, so that endpoint isn't usable here."""

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
        return data.get("message", {}).get("content") or ""
