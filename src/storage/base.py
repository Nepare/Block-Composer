"""Storage Protocols — the pluggable persistence boundary for blocks and compose results.
`FilesystemBlockStorage`/`FilesystemResultStorage` (storage/filesystem.py) are today's
only implementations; a future DB-backed pair implements the same shape (see
storage/router.py's dispatch). naming.py needs zero changes for any of this — its
decide()/unique_stem() already only consume plain in-memory Candidate data and an
injected `exists` callable (see storage/filesystem.py's save_with_dedup for how a backend
supplies both).
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol

from blocks import Block
from naming import Candidate, NamingDecision
from progress import ProgressEvent


@dataclass
class Result:
    """A saved compose result. Richer than what the filesystem backend actually persists
    today (see FilesystemResultStorage's docstring) — the extra fields exist now so a
    future DB backend has somewhere to put them without another signature change later.

    `slots` is a list of plain dicts (not ComposeSlot) deliberately: compose.py is a
    *consumer* of this module, so typing this against compose.ComposeSlot would create a
    circular import.
    """

    id: str = ""
    content: str = ""
    name: str = ""
    request: str = ""
    use_ids: list[str] = field(default_factory=list)
    generate_criteria: list[str] = field(default_factory=list)
    slots: list[dict] = field(default_factory=list)
    progress_log: list[ProgressEvent] = field(default_factory=list)
    created_at: datetime | None = None

    def to_candidate(self) -> Candidate:
        return Candidate(name=self.name, full_text=self.content)


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
    def save_with_dedup(
        self, block: Block, *, naming_client, naming_model: str, naming_constraints: str = ""
    ) -> tuple[NamingDecision, str | None]: ...


class ResultStorage(Protocol):
    def path_for(self, filename_stem: str) -> Path | None: ...
    def exists(self, filename_stem: str) -> bool: ...
    def save(self, result: Result, *, filename_stem: str | None = None) -> str: ...
    def load(self, filename_stem: str) -> Result: ...
    def all(self) -> list[Result]: ...
    def siblings(self, base_slug: str) -> list[Result]: ...
    def search(self, query: str | None = None) -> list[Result]: ...
    def save_with_dedup(
        self, result: Result, *, naming_client, naming_model: str, naming_constraints: str = ""
    ) -> tuple[NamingDecision, str | None]: ...
