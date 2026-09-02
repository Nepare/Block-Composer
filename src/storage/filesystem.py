"""Filesystem-backed BlockStorage/ResultStorage (storage/base.py) — flat Markdown files,
the CLI/local default; save()/save_with_dedup() return a stem, not a Path, since other
backends have none to give."""

from pathlib import Path

import frontmatter
from google.oauth2.credentials import Credentials

from core import naming
from models.blocks import Block
from core.errors import BlockNotFoundError
from storage.base import Result


class FilesystemBlockStorage:
    """Loads/saves/searches Block files: flat Markdown + YAML frontmatter, hand-editable."""

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, filename_stem: str) -> Path:
        return self.root / f"{filename_stem}.md"

    def exists(self, filename_stem: str) -> bool:
        return self.path_for(filename_stem).exists()

    def save(self, block: Block, *, filename_stem: str | None = None) -> str:
        stem = filename_stem or block.id or naming.slugify(block.name)
        block.id = stem
        path = self.path_for(stem)
        frontmatter.dump(block.to_post(), str(path))
        return stem

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
    ) -> tuple[naming.NamingDecision, str | None]:
        """Brand-new name saves immediately; an exact duplicate is skipped; a partial match
        gets a cheap-model variant name (see naming.decide)."""
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
        stem = self.save(block, filename_stem=decision.stem)
        return decision, stem


class FilesystemResultStorage:
    """Loads/saves/searches compose Result files as plain-text `.md` under
    `output/results/` — only `content` persists; `request`/`use_ids`/`slots`/
    `progress_log` are accepted by `save`/`save_with_dedup` but not stored here."""

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, filename_stem: str) -> Path:
        return self.root / f"{filename_stem}.md"

    def exists(self, filename_stem: str) -> bool:
        return self.path_for(filename_stem).exists()

    def save(self, result: Result, *, filename_stem: str | None = None) -> str:
        stem = filename_stem or result.id or naming.slugify(result.name)
        result.id = stem
        path = self.path_for(stem)
        path.write_text(result.content, encoding="utf-8")
        return stem

    def load(self, filename_stem: str) -> Result:
        path = self.path_for(filename_stem)
        if not path.exists():
            raise BlockNotFoundError(f"No result at {path}")
        return Result(id=filename_stem, content=path.read_text(encoding="utf-8"), name=filename_stem)

    def all(self) -> list[Result]:
        return [self.load(p.stem) for p in sorted(self.root.glob("*.md"))]

    def siblings(self, base_slug: str) -> list[Result]:
        out = []
        for path in sorted(self.root.glob(f"{base_slug}*.md")):
            if path.stem == base_slug or path.stem.startswith(f"{base_slug}_mut_"):
                out.append(self.load(path.stem))
        return out

    def search(self, query: str | None = None) -> list[Result]:
        results = self.all()
        if query:
            q = query.lower()
            results = [r for r in results if q in r.name.lower() or q in r.content.lower()]
        return results

    def save_with_dedup(
        self,
        result: Result,
        *,
        naming_client,
        naming_model: str,
        naming_constraints: str = "",
    ) -> tuple[naming.NamingDecision, str | None]:
        """Same dedup shape as the Block version, but a result file has no persisted
        title, so every sibling candidate reuses the new result's own `name` and the
        dedup decision hinges on content equality alone."""
        base_slug = naming.slugify(result.name)
        existing = [
            (sibling.id, naming.Candidate(name=result.name, full_text=sibling.content))
            for sibling in self.siblings(base_slug)
        ]
        decision = naming.decide(
            result.to_candidate(),
            existing,
            exists=self.exists,
            naming_client=naming_client,
            naming_model=naming_model,
            constraints=naming_constraints,
        )
        if decision.action == "skip_duplicate":
            return decision, None
        stem = self.save(result, filename_stem=decision.stem)
        return decision, stem


class FilesystemCredentialsStorage:
    """Persists Credentials as token.json via
    `Credentials.from_authorized_user_file`/`to_json`, behind the CredentialsStorage
    Protocol."""

    def __init__(self, token_path: Path | str, scopes: list[str]):
        self.token_path = Path(token_path)
        self.scopes = scopes

    def save(self, creds: Credentials) -> None:
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(creds.to_json(), encoding="utf-8")

    def load(self) -> Credentials | None:
        if not self.token_path.exists():
            return None
        return Credentials.from_authorized_user_file(str(self.token_path), self.scopes)
