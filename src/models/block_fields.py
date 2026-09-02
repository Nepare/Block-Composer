"""Parses a block's flat Markdown body into structured fields. Pure parsing: no LLM, no
Settings, never raises on malformed input — an unexpected shape just yields emptier fields.
"""

import re
from dataclasses import dataclass, field

from core import naming

_FIELD_RE = re.compile(r"^\*\*(.+?):\*\*\s*(.*)$")
_BULLET_RE = re.compile(r"^-\s+(.+)$")

_LABEL_ALIASES = {
    "period": "time_period",
    "time period": "time_period",
    "role": "role",
    "project roles": "role",
    "author": "role",
}


@dataclass(frozen=True)
class BlockFields:
    name: str = ""
    description: str = ""
    role: str | None = None
    time_period: str | None = None
    environment: list[str] = field(default_factory=list)
    other_fields: dict[str, list[str] | str] = field(default_factory=dict)


def _field_text(value: list[str] | str) -> str:
    return value if isinstance(value, str) else " ".join(value)


def parse_block_body(body: str) -> BlockFields:
    lines = body.splitlines()
    i = 0

    name = ""
    while i < len(lines):
        stripped = lines[i].strip()
        i += 1
        if stripped.startswith("#"):
            name = stripped.lstrip("#").strip()
            break

    description_lines: list[str] = []
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped:
            i += 1
            continue
        if _FIELD_RE.match(stripped):
            break
        description_lines.append(stripped)
        i += 1
    description = " ".join(description_lines)

    role: str | None = None
    time_period: str | None = None
    environment: list[str] = []
    other_fields: dict[str, list[str] | str] = {}

    current_label: str | None = None
    current_inline_value = ""
    current_bullets: list[str] = []

    def flush() -> None:
        nonlocal role, time_period
        if current_label is None:
            return
        value: list[str] | str = current_bullets or current_inline_value.strip()
        label_lower = current_label.strip().lower()
        alias = _LABEL_ALIASES.get(label_lower)
        if alias == "role":
            role = _field_text(value)
        elif alias == "time_period":
            time_period = _field_text(value)
        elif label_lower == "environment":
            environment.extend(t.strip() for t in _field_text(value).split(",") if t.strip())
        else:
            other_fields[naming.slugify(current_label)] = value

    while i < len(lines):
        stripped = lines[i].strip()
        i += 1
        if not stripped:
            continue
        field_match = _FIELD_RE.match(stripped)
        if field_match:
            flush()
            current_label = field_match.group(1)
            current_inline_value = field_match.group(2)
            current_bullets = []
            continue
        bullet_match = _BULLET_RE.match(stripped)
        if bullet_match and current_label is not None:
            current_bullets.append(bullet_match.group(1).strip())
            continue
        if current_label is not None and not current_bullets:
            current_inline_value = f"{current_inline_value} {stripped}".strip()
    flush()

    return BlockFields(
        name=name,
        description=description,
        role=role,
        time_period=time_period,
        environment=environment,
        other_fields=other_fields,
    )
