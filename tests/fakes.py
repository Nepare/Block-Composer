import naming
from errors import BlockNotFoundError


class FakeBlockStorage:
    """In-memory stand-in for BlockStorage (storage/base.py) — dict-backed, no
    filesystem. Reuses the real naming.decide()/slugify() logic (same as
    FilesystemBlockStorage) so dedup/variant behavior matches the real backend; only
    where the data lives differs. Exists to prove the Protocol is complete: if a real
    caller (run_generate/run_mutate/...) works against this with zero adaptation, the
    Protocol captures everything callers actually need.
    """

    def __init__(self):
        self._blocks: dict[str, object] = {}

    def path_for(self, filename_stem):
        return None

    def exists(self, filename_stem) -> bool:
        return filename_stem in self._blocks

    def save(self, block, *, filename_stem=None) -> str:
        stem = filename_stem or block.id or naming.slugify(block.name)
        block.id = stem
        self._blocks[stem] = block
        return stem

    def load(self, filename_stem):
        if filename_stem not in self._blocks:
            raise BlockNotFoundError(f"No block {filename_stem!r}")
        return self._blocks[filename_stem]

    def all(self) -> list:
        return list(self._blocks.values())

    def siblings(self, base_slug: str) -> list:
        return [
            b
            for stem, b in self._blocks.items()
            if stem == base_slug or stem.startswith(f"{base_slug}_mut_")
        ]

    def search(self, query=None, tags=None, source=None) -> list:
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

    def save_with_dedup(self, block, *, naming_client, naming_model, naming_constraints=""):
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


class FakeResultStorage:
    """In-memory stand-in for ResultStorage (storage/base.py), mirroring
    FakeBlockStorage. Reuses FilesystemResultStorage's name-reuse trick (see its
    docstring) since a Result's `name` isn't recoverable from `content` the way a
    Block's is from its own heading.
    """

    def __init__(self):
        self._results: dict[str, object] = {}

    def path_for(self, filename_stem):
        return None

    def exists(self, filename_stem) -> bool:
        return filename_stem in self._results

    def save(self, result, *, filename_stem=None) -> str:
        stem = filename_stem or result.id or naming.slugify(result.name)
        result.id = stem
        self._results[stem] = result
        return stem

    def load(self, filename_stem):
        if filename_stem not in self._results:
            raise BlockNotFoundError(f"No result {filename_stem!r}")
        return self._results[filename_stem]

    def all(self) -> list:
        return list(self._results.values())

    def siblings(self, base_slug: str) -> list:
        return [
            r
            for stem, r in self._results.items()
            if stem == base_slug or stem.startswith(f"{base_slug}_mut_")
        ]

    def search(self, query=None) -> list:
        results = self.all()
        if query:
            q = query.lower()
            results = [r for r in results if q in r.name.lower() or q in r.content.lower()]
        return results

    def save_with_dedup(self, result, *, naming_client, naming_model, naming_constraints=""):
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


class FakeLLMClient:
    """A stand-in LLMClient that replays scripted replies in order — no network, no key.

    Raises if asked for more replies than were scripted, so a test expecting N calls that
    actually triggers N+1 fails loudly instead of silently reusing a stale reply.
    """

    def __init__(self, replies: list[str] | None = None):
        self.replies = list(replies) if replies else []
        self.calls: list[dict] = []

    def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        *,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> str:
        self.calls.append(
            {"messages": messages, "model": model, "temperature": temperature, "max_tokens": max_tokens}
        )
        if not self.replies:
            raise AssertionError("FakeLLMClient ran out of scripted replies")
        return self.replies.pop(0)

    @property
    def call_count(self) -> int:
        return len(self.calls)
