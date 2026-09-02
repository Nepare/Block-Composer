import json
import sys
import urllib.request

from core.config import load_settings

settings = load_settings()
provider, _, model = settings.llm.models.naming.partition(":")

if provider != "ollama":
    print(f"llm.models.naming is {settings.llm.models.naming!r}, not an ollama model -- nothing to pull.")
    sys.exit(0)

request = urllib.request.Request(
    "http://ollama:11434/api/pull",
    data=json.dumps({"model": model, "stream": False}).encode("utf-8"),
    headers={"Content-Type": "application/json"},
)
with urllib.request.urlopen(request) as response:
    result = json.loads(response.read())

if result.get("status") != "success":
    print(f"ollama pull failed: {result}")
    sys.exit(1)

print(f"pulled {model}")
