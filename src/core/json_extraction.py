"""Pull JSON objects out of text that may wrap them in commentary -- LLM replies routinely
do this, especially local reasoning models that ignore "reply with ONLY the JSON" instructions.
"""

import json
from collections.abc import Iterator


def iter_json_objects(text: str) -> Iterator[dict]:
    """Yields every top-level JSON object found in `text`, in the order its opening "{"
    appears. Uses the stdlib decoder itself (`raw_decode`) to find each object's true extent
    rather than pairing braces by hand, so quoted braces and escapes are handled for free."""
    decoder = json.JSONDecoder()
    idx = text.find("{")
    while idx != -1:
        try:
            obj, end = decoder.raw_decode(text, idx)
            if isinstance(obj, dict):
                yield obj
            idx = text.find("{", end)
        except json.JSONDecodeError:
            idx = text.find("{", idx + 1)
