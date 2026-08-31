from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import frontmatter

import naming
from block_fields import BlockFields, parse_block_body
from errors import BlockNotFoundError


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
        """Structured access to this block's own labeled fields (Author, Environment,
        etc.) — see block_fields.py. Recomputed each access rather than cached, since
        nothing here guarantees `body` never changes after construction."""
        return parse_block_body(self.body)

    def to_post(self) -> frontmatter.Post:
        meta = {
            "id": self.id,
            "tags": self.tags,
            "source": self.source,
            "created_by": self.created_by,
            "created_at": (self.created_at or datetime.now(timezone.utc)).isoformat(),
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
        )


class BlockStore:
    """Loads/saves/searches Block files: flat Markdown + YAML frontmatter, hand-editable."""

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, filename_stem: str) -> Path:
        return self.root / f"{filename_stem}.md"

    def exists(self, filename_stem: str) -> bool:
        return self.path_for(filename_stem).exists()

    def save(self, block: Block, *, filename_stem: str | None = None) -> Path:
        stem = filename_stem or block.id or naming.slugify(block.name)
        block.id = stem
        path = self.path_for(stem)
        frontmatter.dump(block.to_post(), str(path))
        return path

    def load(self, filename_stem: str) -> Block:
        path = self.path_for(filename_stem)
        if not path.exists():
            raise BlockNotFoundError(f"No block at {path}")
        post = frontmatter.load(str(path))
        return Block.from_post(post, default_id=path.stem)

    def all(self) -> list[Block]:
        return [
            Block.from_post(frontmatter.load(str(p)), default_id=p.stem)
            for p in sorted(self.root.glob("*.md"))
        ]

    def siblings(self, base_slug: str) -> list[Block]:
        """Every block sharing a base slug: `<base_slug>.md` and `<base_slug>_mut_x.md`."""
        out = []
        for path in sorted(self.root.glob(f"{base_slug}*.md")):
            if path.stem == base_slug or path.stem.startswith(f"{base_slug}_mut_"):
                out.append(Block.from_post(frontmatter.load(str(path)), default_id=path.stem))
        return out

    def search(
        self,
        query: str | None = None,
        tags: list[str] | None = None,
        source: str | None = None,
    ) -> list[Block]:
        results = self.all()
        if tags:
            wanted = {t.lower() for t in tags}
            results = [b for b in results if wanted & {t.lower() for t in b.tags}]
        if source:
            results = [b for b in results if b.source == source]
        if query:
            q = query.lower()
            results = [b for b in results if q in b.name.lower() or q in b.body.lower()]
        return results

    def save_with_dedup(
        self,
        block: Block,
        *,
        naming_client,
        naming_model: str,
        naming_constraints: str = "",
    ) -> tuple[naming.NamingDecision, Path | None]:
        """The shared dissect/generate entry point: brand-new name -> saved immediately, no
        LLM call; exact duplicate of an existing block -> skipped; partial match -> one
        cheap-model call to produce a variant name (see naming.decide)."""
        base_slug = naming.slugify(block.name)
        existing = [(b.id, b.to_candidate()) for b in self.siblings(base_slug)]
        decision = naming.decide(
            block.to_candidate(),
            existing,
            exists=self.exists,
            naming_client=naming_client,
            naming_model=naming_model,
            constraints=naming_constraints,
        )
        if decision.action == "skip_duplicate":
            return decision, None
        path = self.save(block, filename_stem=decision.stem)
        return decision, path
