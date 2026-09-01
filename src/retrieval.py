"""Keyword-based candidate selection for compose: one LLM call turns the request into a
few categorized keywords, then every block in the library is scored against them using
data already sitting in its own body (block_fields.py) — no LLM in the scoring loop.

Keeps compose's planning prompt from having to include the whole library every time.
"""

import re
from dataclasses import dataclass, field
from typing import Callable

from blocks import Block
from llm.client import LLMClient
from llm.prompts import keyword_extraction_prompt, target_count_prompt

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


def _parse_signals_reply(reply: str, max_per_category: int) -> RetrievalSignals:
    values: dict[str, list[str]] = {cat: [] for cat in _CATEGORY_LABELS}
    for line in reply.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        label, _, rest = line.partition(":")
        label = label.strip().upper()
        rest = rest.strip()
        for category, wanted_label in _CATEGORY_LABELS.items():
            if label == wanted_label:
                tokens = [t.strip() for t in rest.split(",") if t.strip()]
                # enforced regardless of what the model actually returned -- the prompt's
                # count is a request, not a guarantee
                values[category] = tokens[:max_per_category] if max_per_category >= 0 else tokens
    return RetrievalSignals(keywords=CategorizedKeywords(**values))


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
    return signals


def extract_target_count(
    request: str, client: LLMClient, model: str, constraints: str = ""
) -> int | None:
    """Pure function like extract_retrieval_signals -- parses target_count_prompt's
    digit-or-NONE reply, then applies the same _request_mentions_count backstop before
    trusting it. Never raises."""
    prompt = target_count_prompt(request, constraints)
    try:
        reply = client.chat(prompt, model, temperature=0.0, max_tokens=10)
    except Exception:
        return None
    text = reply.strip()
    if not text.isdigit() or int(text) <= 0:
        return None
    count = int(text)
    if not _request_mentions_count(request, count):
        return None
    return count


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


def score_block(
    block: Block, keywords: CategorizedKeywords, *, keyword_weight: Callable[[str, str], float] | None = None
) -> ScoredBlock:
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
            weight_fn = keyword_weight or (lambda _category, _kw: 1.0)
            score += _WEIGHTS[category] * sum(weight_fn(category, kw) for kw in hits)

    return ScoredBlock(block=block, score=score, matched=matched)


def rank_blocks(
    blocks: list[Block],
    keywords: CategorizedKeywords,
    *,
    top_n: int,
    unmatched_reserve: int = 2,
    keyword_weight: Callable[[str, str], float] | None = None,
) -> list[Block]:
    """Top-scoring blocks first, plus a small deterministic sample of zero-scoring blocks
    (up to unmatched_reserve, sorted by id) so a block that shares no keywords isn't
    invisible to the planner as a possible mutate/generate gap-filler. Fixed rather than
    proportional to top_n -- a top_n // 3 reserve collapses to 0 for a small request-driven
    top_n (e.g. 2 or 3), silently removing the exact safety net it exists to provide."""
    scored = [score_block(b, keywords, keyword_weight=keyword_weight) for b in blocks]
    matched_sorted = sorted((s for s in scored if s.score > 0), key=lambda s: s.score, reverse=True)
    unmatched_sorted = sorted((s for s in scored if s.score == 0), key=lambda s: s.block.id)

    reserve = min(unmatched_reserve, len(unmatched_sorted))
    top_matched = matched_sorted[:top_n]
    filler = unmatched_sorted[:reserve]

    return [s.block for s in top_matched] + [s.block for s in filler]
