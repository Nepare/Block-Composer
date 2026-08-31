import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from errors import TemplateError


def _slugify_label(label: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", label.strip().lower())
    return text.strip("_") or "field"


@dataclass
class KnownField:
    label: str
    name: str


@dataclass
class BlockSchema:
    name: str
    section_marker: str
    table_columns: int
    known_fields: list[KnownField] = field(default_factory=list)
    tag_fields: list[str] = field(default_factory=lambda: ["name"])

    def canonical_name(self, label: str) -> str:
        """Field key for a heading label — renamed via known_fields, else auto-slugified."""
        for kf in self.known_fields:
            if kf.label.strip().lower() == label.strip().lower():
                return kf.name
        return _slugify_label(label)

    def display_label(self, label: str) -> str:
        """Friendlier rendered label, e.g. 'Period' -> 'Time period'."""
        for kf in self.known_fields:
            if kf.label.strip().lower() == label.strip().lower():
                return kf.name.replace("_", " ").capitalize()
        return label.strip().capitalize()


def load_block_schema(path: Path | str) -> BlockSchema:
    path = Path(path)
    if not path.exists():
        raise TemplateError(f"No templates file at {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw = data.get("block_schema")
    if not raw:
        raise TemplateError(f"{path} has no top-level 'block_schema' entry.")

    section_marker = raw.get("section_marker")
    if not section_marker:
        raise TemplateError(f"{path}: block_schema.section_marker is required.")

    details = raw.get("columns", {}).get("details", {})
    known = [
        KnownField(label=kf["label"], name=kf["name"]) for kf in (details.get("known_fields") or [])
    ]
    return BlockSchema(
        name=raw.get("name", "project_entry"),
        section_marker=section_marker,
        table_columns=int(raw.get("table_columns", 2)),
        known_fields=known,
        tag_fields=list(raw.get("tag_fields") or ["name"]),
    )
