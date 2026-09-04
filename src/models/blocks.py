from dataclasses import dataclass, field
from datetime import datetime, timezone

import frontmatter

from core import naming
from models.block_fields import BlockFields, parse_block_body


@dataclass
class Block:
    id: str
    body: str
    schema: str | None = None
    tags: list[str] = field(default_factory=list)
    source: str = "manual"
    created_by: str = "manual"
    created_at: datetime | None = None
    generation_criteria: str | None = None
    mutated_from: str | None = None
    preserved: bool = False

    @property
    def name(self) -> str:
        """The block's display name — its first Markdown heading, or its id."""
        for line in self.body.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                return stripped.lstrip("#").strip()
        return self.id or "untitled"

    def to_candidate(self) -> naming.Candidate:
        return naming.Candidate(name=self.name, full_text=self.body)

    @property
    def fields(self) -> BlockFields:
        """Structured access to this block's own labeled fields — recomputed each access, not cached."""
        return parse_block_body(self.body)

    def to_post(self) -> frontmatter.Post:
        meta = {
            "id": self.id,
            "tags": self.tags,
            "source": self.source,
            "created_by": self.created_by,
            "created_at": (self.created_at or datetime.now(timezone.utc)).isoformat(),
            "preserved": self.preserved,
        }
        if self.schema:
            meta["schema"] = self.schema
        if self.generation_criteria:
            meta["generation_criteria"] = self.generation_criteria
        if self.mutated_from:
            meta["mutated_from"] = self.mutated_from
        return frontmatter.Post(self.body.strip() + "\n", **meta)

    @classmethod
    def from_post(cls, post: frontmatter.Post, *, default_id: str) -> "Block":
        meta = post.metadata
        created_at = None
        raw = meta.get("created_at")
        if isinstance(raw, datetime):
            created_at = raw
        elif isinstance(raw, str):
            try:
                created_at = datetime.fromisoformat(raw)
            except ValueError:
                created_at = None
        return cls(
            id=meta.get("id") or default_id,
            body=post.content,
            schema=meta.get("schema"),
            tags=list(meta.get("tags") or []),
            source=meta.get("source", "manual"),
            created_by=meta.get("created_by", "manual"),
            created_at=created_at,
            generation_criteria=meta.get("generation_criteria"),
            mutated_from=meta.get("mutated_from"),
            preserved=bool(meta.get("preserved", False)),
        )
