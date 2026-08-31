"""Keyword-based candidate selection for compose: one LLM call turns the request into a
few categorized keywords, then every block in the library is scored against them using
data already sitting in its own body (block_fields.py) — no LLM in the scoring loop.

Keeps compose's planning prompt from having to include the whole library every time.
"""

import re
from dataclasses import dataclass, field

from blocks import Block
from llm.client import LLMClient
from llm.prompts import keyword_extraction_prompt

_CATEGORY_LABELS = {
    "role": "ROLE",
    "environment": "ENVIRONMENT",
    "responsibilities": "RESPONSIBILITIES",
    "domain": "DOMAIN",
}

_WEIGHTS = {"role": 1.5, "environment": 1.5, "responsibilities": 1.0, "domain": 1.0}

_NUMBER_WORDS = {
    1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven",
    8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve", 13: "thirteen",
    14: "fourteen", 15: "fifteen", 16: "sixteen", 17: "seventeen", 18: "eighteen",
    19: "nineteen", 20: "twenty",
}


def _request_mentions_count(request: str, count: int) -> bool:
    """A small local model can invent a plausible-sounding PROJECT_COUNT even when the
    request states no number at all (observed live) -- this is the deterministic backstop:
    only trust the extracted count if that number, digit or spelled-out, actually appears
    in the request text. Never raises."""
    lowered = request.lower()
    candidates = [str(count)]
    word = _NUMBER_WORDS.get(count)
    if word:
        candidates.append(word)
    return any(re.search(rf"\b{re.escape(c)}\b", lowered) for c in candidates)


@dataclass(frozen=True)
class CategorizedKeywords:
    role: list[str] = field(default_factory=list)
    environment: list[str] = field(default_factory=list)
    responsibilities: list[str] = field(default_factory=list)
    domain: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.role or self.environment or self.responsibilities or self.domain)


@dataclass(frozen=True)
class RetrievalSignals:
    keywords: CategorizedKeywords = field(default_factory=CategorizedKeywords)
    # e.g. "aim for 3 projects" -> 3; None if the request didn't specify a count, in which
    # case the caller falls back to its own configured default top_n
    requested_count: int | None = None


def _parse_signals_reply(reply: str, max_per_category: int) -> RetrievalSignals:
    values: dict[str, list[str]] = {cat: [] for cat in _CATEGORY_LABELS}
    requested_count: int | None = None
    for line in reply.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        label, _, rest = line.partition(":")
        label = label.strip().upper()
        rest = rest.strip()
        if label == "PROJECT_COUNT":
            if rest.isdigit() and int(rest) > 0:
                requested_count = int(rest)
            continue
        for category, wanted_label in _CATEGORY_LABELS.items():
            if label == wanted_label:
                tokens = [t.strip() for t in rest.split(",") if t.strip()]
                # enforced regardless of what the model actually returned -- the prompt's
                # count is a request, not a guarantee
                values[category] = tokens[:max_per_category] if max_per_category >= 0 else tokens
    return RetrievalSignals(keywords=CategorizedKeywords(**values), requested_count=requested_count)


def extract_retrieval_signals(
    request: str,
    client: LLMClient,
    model: str,
    constraints: str = "",
    *,
    min_per_category: int = 0,
    max_per_category: int = 4,
) -> RetrievalSignals:
    """Pure function like naming.py's _propose_label — caller supplies an already-built
    client/model and already-loaded constraints text, no Settings/file IO here. Any parse
    failure degrades to an all-empty result rather than raising; the caller's job is to
    treat that as "narrowing skipped," never a hard error."""
    prompt = keyword_extraction_prompt(
        request, constraints, min_per_category=min_per_category, max_per_category=max_per_category
    )
    try:
        reply = client.chat(prompt, model, temperature=0.2, max_tokens=170)
    except Exception:
        return RetrievalSignals()
    signals = _parse_signals_reply(reply, max_per_category)
    if signals.requested_count is not None and not _request_mentions_count(request, signals.requested_count):
        signals = RetrievalSignals(keywords=signals.keywords, requested_count=None)
    return signals


@dataclass(frozen=True)
class ScoredBlock:
    block: Block
    score: float
    matched: dict[str, list[str]]


def _category_text(fields, category: str) -> str:
    if category == "role":
        return f"{fields.name} {fields.description}"
    if category == "environment":
        return ", ".join(fields.environment)
    if category == "responsibilities":
        parts = []
        for value in fields.other_fields.values():
            parts.append(value if isinstance(value, str) else " ".join(value))
        return " ".join(parts)
    if category == "domain":
        return f"{fields.name} {fields.description}"
    return ""


def score_block(block: Block, keywords: CategorizedKeywords) -> ScoredBlock:
    fields = block.fields
    domain_text = f"{_category_text(fields, 'domain')} {' '.join(block.tags)}".lower()
    category_text = {
        "role": _category_text(fields, "role").lower(),
        "environment": _category_text(fields, "environment").lower(),
        "responsibilities": _category_text(fields, "responsibilities").lower(),
        "domain": domain_text,
    }

    score = 0.0
    matched: dict[str, list[str]] = {}
    for category, keyword_list in (
        ("role", keywords.role),
        ("environment", keywords.environment),
        ("responsibilities", keywords.responsibilities),
        ("domain", keywords.domain),
    ):
        hits = [kw for kw in keyword_list if kw.lower() in category_text[category]]
        if hits:
            matched[category] = hits
            score += _WEIGHTS[category] * len(hits)

    return ScoredBlock(block=block, score=score, matched=matched)


def rank_blocks(blocks: list[Block], keywords: CategorizedKeywords, *, top_n: int) -> list[Block]:
    """Top-scoring blocks first, plus a small deterministic sample of zero-scoring blocks
    (up to top_n // 3, sorted by id) so a block that shares no keywords isn't invisible to
    the planner as a possible mutate/generate gap-filler."""
    scored = [score_block(b, keywords) for b in blocks]
    matched_sorted = sorted((s for s in scored if s.score > 0), key=lambda s: s.score, reverse=True)
    unmatched_sorted = sorted((s for s in scored if s.score == 0), key=lambda s: s.block.id)

    reserve = max(0, top_n // 3)
    top_matched = matched_sorted[:top_n]
    filler = unmatched_sorted[:reserve]

    return [s.block for s in top_matched] + [s.block for s in filler]
