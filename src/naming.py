"""Shared filename/dedup logic for every block-writing path (dissect/generate/mutate)
and for compose's result output.

Decision flow: slugify the candidate's name; if nothing exists at that slug, save it
plainly with no LLM call; if something does, an exact-content match is skipped as a
duplicate (pure string comparison); otherwise a cheap model proposes a short bracket
label describing what's different, and the candidate is saved as `<slug> [<label>].md`.
The file with no bracket is always the "first"/anchor — later arrivals get the bracket,
never the other way around.
"""

import re
from dataclasses import dataclass
from typing import Callable, Sequence

from llm.client import LLMClient

NAMING_SYSTEM_PROMPT = (
    "You name variant files in a small personal library. Given an existing entry and a "
    "new, similar one that collided on the same base name, reply with ONLY a short 1-3 "
    "word bracket label (lowercase, no punctuation besides spaces) that captures what "
    "makes the new one different from the existing one, e.g. 'local', 'remote', "
    "'hosted'. Do not repeat the base name and do not explain yourself."
)


def slugify(text: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", text.strip().lower())
    return text.strip("_") or "item"


def unique_stem(base: str, exists: Callable[[str], bool]) -> str:
    if not exists(base):
        return base
    n = 2
    while exists(f"{base} {n}"):
        n += 1
    return f"{base} {n}"


@dataclass
class Candidate:
    name: str
    full_text: str


@dataclass
class NamingDecision:
    action: str  # "save_plain" | "save_variant" | "skip_duplicate"
    stem: str | None
    label: str | None = None
    duplicate_of: str | None = None
    called_llm: bool = False


def _normalize(text: str) -> str:
    return " ".join(text.split()).strip().lower()


def _is_exact_match(a: Candidate, b: Candidate) -> bool:
    return _normalize(a.name) == _normalize(b.name) and _normalize(a.full_text) == _normalize(
        b.full_text
    )


def _propose_label(candidate: Candidate, reference: Candidate, client: LLMClient, model: str) -> str:
    prompt = (
        f"Existing entry:\n{reference.full_text}\n\n"
        f"New entry that collided with it on the same name:\n{candidate.full_text}\n\n"
        "Bracket label for the new entry:"
    )
    reply = client.chat(
        [
            {"role": "system", "content": NAMING_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        model,
        temperature=0.2,
        max_tokens=20,
    )
    return reply.strip().strip("[]").strip() or "variant"


def decide(
    candidate: Candidate,
    existing: Sequence[tuple[str, Candidate]],
    *,
    exists: Callable[[str], bool],
    naming_client: LLMClient,
    naming_model: str,
) -> NamingDecision:
    """`existing` is (filename_stem, Candidate) pairs already sharing the candidate's base slug."""
    base_slug = slugify(candidate.name)
    if not existing:
        return NamingDecision(action="save_plain", stem=base_slug)

    for stem, other in existing:
        if _is_exact_match(candidate, other):
            return NamingDecision(action="skip_duplicate", stem=None, duplicate_of=stem)

    _reference_stem, reference = existing[0]
    label = _propose_label(candidate, reference, naming_client, naming_model)
    stem = unique_stem(f"{base_slug} [{slugify(label)}]", exists)
    return NamingDecision(action="save_variant", stem=stem, label=label, called_llm=True)
