"""Keyword-based candidate narrowing for compose: one LLM call extracts categorized
keywords, then blocks are scored against them locally, no LLM in the scoring loop."""

import re
from dataclasses import dataclass, field
from typing import Callable

from models.blocks import Block
from llm.client import LLMClient
from llm.prompts import keyword_extraction_prompt, target_count_prompt

_CATEGORY_LABELS = {
    "role": "ROLE",
    "environment": "ENVIRONMENT",
    "responsibilities": "RESPONSIBILITIES",
    "domain": "DOMAIN",
}

_WEIGHTS = {"role": 1.5, "environment": 1.5, "responsibilities": 1.0, "domain": 1.0}

_LEXICAL_STOPWORDS = {
    "a", "an", "the", "for", "of", "and", "or", "to", "in", "on", "with", "also", "system",
    "systems", "platform", "project", "device", "application", "app", "service", "software",
    "entry", "update", "mention", "add", "please", "my", "about", "that", "this", "into",
    "based", "solution", "tool", "development",
}

_LEXICAL_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _lexical_tokens(text: str) -> set[str]:
    """Lowercase alphanumeric word tokens, length > 2, generic stopwords removed."""
    tokens = _LEXICAL_TOKEN_RE.findall(text.lower())
    return {t for t in tokens if len(t) > 2 and t not in _LEXICAL_STOPWORDS}

_NUMBER_WORDS = {
    1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven",
    8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve", 13: "thirteen",
    14: "fourteen", 15: "fifteen", 16: "sixteen", 17: "seventeen", 18: "eighteen",
    19: "nineteen", 20: "twenty",
}


def _request_mentions_count(request: str, count: int) -> bool:
    """Deterministic backstop: only trust an extracted count if it actually appears,
    digit or spelled-out, in the request text. Never raises."""
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
    """Pure function — plain data/callables in, no Settings/file IO. Any parse failure
    degrades to an all-empty result rather than raising."""
    prompt = keyword_extraction_prompt(
        request, constraints, min_per_category=min_per_category, max_per_category=max_per_category
    )
    try:
        reply = client.chat(prompt, model, temperature=0.2, max_tokens=170)
    except Exception:
        return RetrievalSignals()
    signals = _parse_signals_reply(reply, max_per_category)
    return signals


_NUMBER_RE = re.compile(r"\b(\d+)\b")


def extract_target_count(request: str, client: LLMClient, model: str) -> int | None:
    """Pure function; applies the _request_mentions_count backstop before trusting a
    parsed count. Never raises -- tolerates a verbose reply by taking its last number."""
    prompt = target_count_prompt(request)
    try:
        reply = client.chat(prompt, model, temperature=0.0, max_tokens=60)
    except Exception:
        return None
    numbers = _NUMBER_RE.findall(reply)
    if not numbers:
        return None
    count = int(numbers[-1])
    if count <= 0:
        return None
    if not _request_mentions_count(request, count):
        return None
    return count


def _block_lexical_tokens(block: Block) -> set[str]:
    """Union of lexical tokens from the block's id, tags, and name."""
    normalized_id = block.id.replace("_", " ").replace("-", " ")
    tokens = set(_lexical_tokens(normalized_id))
    for tag in block.tags:
        normalized_tag = tag.replace("_", " ").replace("-", " ")
        tokens |= _lexical_tokens(normalized_tag)
    tokens |= _lexical_tokens(block.name)
    return tokens


def _project_lexical_token_sets(blocks: list[Block]) -> dict[tuple[str, ...], set[str]]:
    """Groups blocks by tag_signature, unioning each project's own variants' lexical tokens once."""
    groups: dict[tuple[str, ...], set[str]] = {}
    for block in blocks:
        groups.setdefault(block.tag_signature, set()).update(_block_lexical_tokens(block))
    return groups


def _lexical_document_frequencies(blocks: list[Block]) -> dict[str, int]:
    """Counts, per token, how many distinct projects (not stored blocks) contain it."""
    frequencies: dict[str, int] = {}
    for token_set in _project_lexical_token_sets(blocks).values():
        for token in token_set:
            frequencies[token] = frequencies.get(token, 0) + 1
    return frequencies


def lexical_matches(
    blocks: list[Block], request: str, *, min_overlap: int = 2, rare_df_max: int = 3
) -> list[Block]:
    """Force-include blocks whose corpus-rare, distinctive tokens overlap the request."""
    request_tokens = _lexical_tokens(request)
    if not request_tokens:
        return []
    df = _lexical_document_frequencies(blocks)
    matches = []
    for block in blocks:
        distinctive = {t for t in _block_lexical_tokens(block) if df.get(t, 0) <= rare_df_max}
        if not distinctive:
            continue
        overlap = distinctive & request_tokens
        threshold = min(min_overlap, len(distinctive))
        if len(overlap) >= threshold:
            matches.append(block)
    return matches


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


def _pick_representative_block(group: list[Block]) -> Block:
    """Prefers a non-"_mut"-suffixed member over an adapted variant, falling back to the first member."""
    non_variants = [
        b for b in group if not any(other is not b and b.id.startswith(other.id + "_mut") for other in group)
    ]
    return non_variants[0] if non_variants else group[0]


def _dedupe_by_project(scored: list[ScoredBlock]) -> list[ScoredBlock]:
    """Keeps one representative ScoredBlock per tag_signature group, in first-seen order."""
    groups: dict[tuple[str, ...], list[ScoredBlock]] = {}
    order: list[tuple[str, ...]] = []
    for s in scored:
        sig = s.block.tag_signature
        if sig not in groups:
            groups[sig] = []
            order.append(sig)
        groups[sig].append(s)
    return [
        next(s for s in groups[sig] if s.block is _pick_representative_block([g.block for g in groups[sig]]))
        for sig in order
    ]


def dedupe_blocks_by_project(blocks: list[Block]) -> list[Block]:
    """Same rule as _dedupe_by_project, for a plain Block list with no ScoredBlock wrapper."""
    groups: dict[tuple[str, ...], list[Block]] = {}
    order: list[tuple[str, ...]] = []
    for b in blocks:
        sig = b.tag_signature
        if sig not in groups:
            groups[sig] = []
            order.append(sig)
        groups[sig].append(b)
    return [_pick_representative_block(groups[sig]) for sig in order]


def rank_blocks(
    blocks: list[Block],
    keywords: CategorizedKeywords,
    *,
    top_n: int,
    unmatched_reserve: int = 2,
    keyword_weight: Callable[[str, str], float] | None = None,
    force_include: list[Block] | None = None,
) -> list[Block]:
    """Top-scoring blocks first, plus a fixed (not proportional to top_n) sample of
    zero-scoring blocks so an unmatched block stays visible as a gap-filler option."""
    scored = [score_block(b, keywords, keyword_weight=keyword_weight) for b in blocks]
    matched_sorted = sorted((s for s in scored if s.score > 0), key=lambda s: s.score, reverse=True)
    unmatched_sorted = sorted((s for s in scored if s.score == 0), key=lambda s: s.block.id)

    # force_include is deduped by the caller, not here, so a forced target is never at risk
    matched_sorted = _dedupe_by_project(matched_sorted)
    unmatched_sorted = _dedupe_by_project(unmatched_sorted)

    reserve = min(unmatched_reserve, len(unmatched_sorted))
    top_matched = matched_sorted[:top_n]
    filler = unmatched_sorted[:reserve]

    ranked = [s.block for s in top_matched] + [s.block for s in filler]
    if not force_include:
        return ranked

    ranked_ids = {b.id for b in ranked}
    seen = set()
    forced = []
    for block in force_include:
        if block.id not in ranked_ids and block.id not in seen:
            seen.add(block.id)
            forced.append(block)
    return forced + ranked
