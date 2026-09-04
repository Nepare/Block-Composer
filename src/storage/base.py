"""Storage Protocols — the pluggable persistence boundary for blocks and compose results
(see storage/router.py's dispatch)."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

import frontmatter
from google.oauth2.credentials import Credentials

from models.blocks import Block
from core.naming import Candidate, NamingDecision
from core.progress import ProgressEvent


@dataclass
class Result:
    """A saved compose result. `slots` is a list of plain dicts, not ComposeSlot, to
    avoid a circular import with compose.py."""

    id: str = ""
    content: str = ""
    name: str = ""
    request: str = ""
    use_ids: list[str] = field(default_factory=list)
    generate_criteria: list[str] = field(default_factory=list)
    slots: list[dict] = field(default_factory=list)
    progress_log: list[ProgressEvent] = field(default_factory=list)
    created_at: datetime | None = None
    preserved: bool = False

    def to_candidate(self) -> Candidate:
        return Candidate(name=self.name, full_text=self.content)

    def to_post(self) -> frontmatter.Post:
        meta = {
            "id": self.id,
            "name": self.name,
            "request": self.request,
            "use_ids": self.use_ids,
            "generate_criteria": self.generate_criteria,
            "slots": self.slots,
            "created_at": (self.created_at or datetime.now(timezone.utc)).isoformat(),
            "preserved": self.preserved,
        }
        return frontmatter.Post(self.content.strip() + "\n", **meta)

    @classmethod
    def from_post(cls, post: frontmatter.Post, *, default_id: str) -> "Result":
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
            content=post.content,
            name=meta.get("name") or default_id,
            request=meta.get("request", ""),
            use_ids=list(meta.get("use_ids") or []),
            generate_criteria=list(meta.get("generate_criteria") or []),
            slots=list(meta.get("slots") or []),
            created_at=created_at,
            preserved=bool(meta.get("preserved", False)),
        )


@dataclass(frozen=True)
class ClearResult:
    deleted: int
    skipped_preserved: int


class BlockStorage(Protocol):
    def path_for(self, filename_stem: str) -> Path | None: ...
    def exists(self, filename_stem: str) -> bool: ...
    def save(self, block: Block, *, filename_stem: str | None = None) -> str: ...
    def load(self, filename_stem: str) -> Block: ...
    def all(self) -> list[Block]: ...
    def siblings(self, base_slug: str) -> list[Block]: ...
    def search(
        self, query: str | None = None, tags: list[str] | None = None, source: str | None = None
    ) -> list[Block]: ...
    # naming_client/naming_model are optional (unused when explicit_base skips naming/dedup and lets the backend derive the stem from it via naming.unique_stem inside its own guarded critical section)
    def save_with_dedup(
        self,
        block: Block,
        *,
        naming_client=None,
        naming_model: str | None = None,
        naming_constraints: str = "",
        explicit_base: str | None = None,
    ) -> tuple[NamingDecision, str | None]: ...
    def delete(self, filename_stem: str) -> None: ...
    def set_preserved(self, filename_stem: str, preserved: bool) -> None: ...
    def clear(self) -> ClearResult: ...


class ResultStorage(Protocol):
    def path_for(self, filename_stem: str) -> Path | None: ...
    def exists(self, filename_stem: str) -> bool: ...
    def save(self, result: Result, *, filename_stem: str | None = None) -> str: ...
    def load(self, filename_stem: str) -> Result: ...
    def all(self) -> list[Result]: ...
    def siblings(self, base_slug: str) -> list[Result]: ...
    def search(self, query: str | None = None) -> list[Result]: ...
    # naming_client/naming_model are optional (unused when explicit_base skips naming/dedup and lets the backend derive the stem from it via naming.unique_stem inside its own guarded critical section)
    def save_with_dedup(
        self,
        result: Result,
        *,
        naming_client=None,
        naming_model: str | None = None,
        naming_constraints: str = "",
        explicit_base: str | None = None,
    ) -> tuple[NamingDecision, str | None]: ...
    def delete(self, filename_stem: str) -> None: ...
    def set_preserved(self, filename_stem: str, preserved: bool) -> None: ...
    def clear(self) -> ClearResult: ...


class CredentialsStorage(Protocol):
    def save(self, creds: Credentials) -> None: ...
    def load(self) -> Credentials | None: ...
