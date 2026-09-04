"""Shared filename/dedup logic for every block-writing path and for compose's result
output: a slug with nothing at it saves plainly; an exact-content match is skipped as a
duplicate; otherwise a cheap model proposes a variant label and the candidate saves as
`<slug>_mut_<label>.md` — the first arrival at a slug is always the unsuffixed anchor."""

import re
from dataclasses import dataclass
from typing import Callable, Sequence

from core.errors import InputError
from llm.client import LLMClient

NAMING_SYSTEM_PROMPT = (
    "You name variant files in a small personal library. Given an existing entry and a "
    "new, similar one that collided on the same base name, reply with ONLY a short 1-3 "
    "word label (lowercase, letters/numbers/spaces only) that captures what makes the new "
    "one different from the existing one, e.g. 'local', 'remote', 'hosted'. Do not repeat "
    "the base name and do not explain yourself."
)


def _raw_slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")


def slugify(text: str) -> str:
    return _raw_slug(text) or "item"


def validate_explicit_name(name: str) -> str:
    """Rejects a caller-supplied name with no usable characters left after slugifying —
    e.g. `"!!!"` or all whitespace — rather than silently falling back to the generic
    `"item"` placeholder. Returns the raw, unnumbered slug base; numbering happens later,
    inside a storage backend's guarded save, never here."""
    raw = _raw_slug(name)
    if not raw:
        raise InputError(f"--name {name!r} has no usable characters to build a name from.")
    return raw


def unique_stem(base: str, exists: Callable[[str], bool]) -> str:
    if not exists(base):
        return base
    n = 2
    while exists(f"{base}_{n}"):
        n += 1
    return f"{base}_{n}"


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


def _propose_label(
    candidate: Candidate, reference: Candidate, client: LLMClient, model: str, constraints: str = ""
) -> str:
    prompt = (
        f"Existing entry:\n{reference.full_text}\n\n"
        f"New entry that collided with it on the same name:\n{candidate.full_text}\n\n"
        "Label for the new entry:"
    )
    system = NAMING_SYSTEM_PROMPT
    if constraints:
        system = f"{system}\n\n## User constraints — follow these strictly\n{constraints}"
    reply = client.chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        model,
        temperature=0.2,
        max_tokens=40,
    )
    # bound to the first non-empty line: a model that ignores the "only the label"
    # instruction and rambles must never have that whole ramble become the file name
    lines = [line.strip() for line in reply.strip().splitlines() if line.strip()]
    label = lines[0].strip("[]").strip() if lines else ""
    # a real label is a short phrase, not a sentence -- if it's implausibly long, the
    # model likely explained itself instead of answering; fall back rather than use it
    if len(label.split()) > 6:
        return "variant"
    return label or "variant"


def decide(
    candidate: Candidate,
    existing: Sequence[tuple[str, Candidate]],
    *,
    exists: Callable[[str], bool],
    naming_client: LLMClient,
    naming_model: str,
    constraints: str = "",
) -> NamingDecision:
    """`existing` is (filename_stem, Candidate) pairs already sharing the candidate's base
    slug. `constraints` is the caller's already-loaded NAMING_CONSTRAINTS.md content, if
    any — naming.py stays decoupled from Settings/file IO by design, so callers load it."""
    base_slug = slugify(candidate.name)
    if not existing:
        return NamingDecision(action="save_plain", stem=base_slug)

    for stem, other in existing:
        if _is_exact_match(candidate, other):
            return NamingDecision(action="skip_duplicate", stem=None, duplicate_of=stem)

    _reference_stem, reference = existing[0]
    label = _propose_label(candidate, reference, naming_client, naming_model, constraints)
    stem = unique_stem(f"{base_slug}_mut_{slugify(label)}", exists)
    return NamingDecision(action="save_variant", stem=stem, label=label, called_llm=True)
