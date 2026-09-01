"""SQLite-backed implementations of BlockStorage/ResultStorage (storage/base.py) — the
Docker/web deployment backend. Written directly against `sqlite3` (stdlib), not an ORM:
the Protocol is what buys future Postgres portability, not SQLAlchemy, and a hand-written
layer is proportionate for a two-table schema.

Connections use `isolation_level=None` (autocommit) so each class manages transactions
explicitly rather than relying on sqlite3's implicit-transaction default — `save()` wraps
its own single write in BEGIN/COMMIT, `save_with_dedup()` wraps the whole exists-check ->
naming.decide() -> insert sequence in one BEGIN IMMEDIATE/COMMIT (via a private `_insert()`
helper with no commit of its own, reused by both, so the transaction boundary is only ever
set by the outermost caller) — this is what makes the check-then-act dedup race atomic
under concurrent web requests, unlike the filesystem backend.
"""

import json
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.oauth2.credentials import Credentials

import naming
from blocks import Block
from errors import BlockNotFoundError
from storage.base import Result

DEFAULT_USER_ID = "default"


def _connect(path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


class SqliteBlockStorage:
    """Same behavior/shape as FilesystemBlockStorage, backed by a `blocks` table instead
    of `*.md` files. `path_for()` always returns None -- there's no filesystem path here."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = _connect(self.path)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS blocks (
                id TEXT PRIMARY KEY,
                body TEXT NOT NULL,
                schema TEXT,
                tags TEXT NOT NULL DEFAULT '[]',
                source TEXT NOT NULL DEFAULT 'manual',
                created_by TEXT NOT NULL DEFAULT 'manual',
                created_at TEXT,
                generation_criteria TEXT,
                mutated_from TEXT
            )
            """
        )

    def path_for(self, filename_stem: str) -> None:
        return None

    def exists(self, filename_stem: str) -> bool:
        row = self._conn.execute("SELECT 1 FROM blocks WHERE id = ?", (filename_stem,)).fetchone()
        return row is not None

    @staticmethod
    def _row_to_block(row: sqlite3.Row) -> Block:
        return Block(
            id=row["id"],
            body=row["body"],
            schema=row["schema"],
            tags=json.loads(row["tags"]),
            source=row["source"],
            created_by=row["created_by"],
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
            generation_criteria=row["generation_criteria"],
            mutated_from=row["mutated_from"],
        )

    def _insert(self, block: Block, stem: str) -> None:
        self._conn.execute(
            """
            INSERT INTO blocks (id, body, schema, tags, source, created_by, created_at,
                                 generation_criteria, mutated_from)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                body=excluded.body, schema=excluded.schema, tags=excluded.tags,
                source=excluded.source, created_by=excluded.created_by,
                created_at=excluded.created_at, generation_criteria=excluded.generation_criteria,
                mutated_from=excluded.mutated_from
            """,
            (
                stem,
                block.body,
                block.schema,
                json.dumps(block.tags),
                block.source,
                block.created_by,
                (block.created_at or datetime.now(timezone.utc)).isoformat(),
                block.generation_criteria,
                block.mutated_from,
            ),
        )

    def save(self, block: Block, *, filename_stem: str | None = None) -> str:
        stem = filename_stem or block.id or naming.slugify(block.name)
        block.id = stem
        self._conn.execute("BEGIN")
        try:
            self._insert(block, stem)
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        self._conn.execute("COMMIT")
        return stem

    def load(self, filename_stem: str) -> Block:
        row = self._conn.execute("SELECT * FROM blocks WHERE id = ?", (filename_stem,)).fetchone()
        if row is None:
            raise BlockNotFoundError(f"No block {filename_stem!r} in {self.path}")
        return self._row_to_block(row)

    def all(self) -> list[Block]:
        rows = self._conn.execute("SELECT * FROM blocks ORDER BY id").fetchall()
        return [self._row_to_block(r) for r in rows]

    def siblings(self, base_slug: str) -> list[Block]:
        rows = self._conn.execute(
            "SELECT * FROM blocks WHERE id = ? OR id LIKE ? ORDER BY id",
            (base_slug, f"{base_slug}_mut_%"),
        ).fetchall()
        return [self._row_to_block(r) for r in rows]

    def search(
        self,
        query: str | None = None,
        tags: list[str] | None = None,
        source: str | None = None,
    ) -> list[Block]:
        # Same "load all, filter in Python" approach as FilesystemBlockStorage.search --
        # deliberately not pushed into SQL yet; a real UI's query patterns aren't known,
        # and hand-writing JSON-array tag queries prematurely is exactly the
        # over-normalizing this phase avoids.
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
        base_slug = naming.slugify(block.name)
        self._conn.execute("BEGIN IMMEDIATE")
        try:
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
                self._conn.execute("COMMIT")
                return decision, None
            self._insert(block, decision.stem)
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        self._conn.execute("COMMIT")
        block.id = decision.stem
        return decision, decision.stem


class SqliteResultStorage:
    """Same behavior/shape as FilesystemResultStorage, backed by a `results` table —
    but unlike the filesystem backend, the full Result (request/use_ids/generate_criteria/
    slots/progress_log) is actually persisted here, not just `content`."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = _connect(self.path)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS results (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                name TEXT NOT NULL,
                request TEXT NOT NULL DEFAULT '',
                use_ids TEXT NOT NULL DEFAULT '[]',
                generate_criteria TEXT NOT NULL DEFAULT '[]',
                slots TEXT NOT NULL DEFAULT '[]',
                progress_log TEXT NOT NULL DEFAULT '[]',
                created_at TEXT
            )
            """
        )

    def path_for(self, filename_stem: str) -> None:
        return None

    def exists(self, filename_stem: str) -> bool:
        row = self._conn.execute("SELECT 1 FROM results WHERE id = ?", (filename_stem,)).fetchone()
        return row is not None

    @staticmethod
    def _row_to_result(row: sqlite3.Row) -> Result:
        return Result(
            id=row["id"],
            content=row["content"],
            name=row["name"],
            request=row["request"],
            use_ids=json.loads(row["use_ids"]),
            generate_criteria=json.loads(row["generate_criteria"]),
            slots=json.loads(row["slots"]),
            progress_log=[],  # not populated by any caller yet -- see storage/sqlite.py docstring
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
        )

    def _insert(self, result: Result, stem: str) -> None:
        self._conn.execute(
            """
            INSERT INTO results (id, content, name, request, use_ids, generate_criteria,
                                  slots, progress_log, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                content=excluded.content, name=excluded.name, request=excluded.request,
                use_ids=excluded.use_ids, generate_criteria=excluded.generate_criteria,
                slots=excluded.slots, progress_log=excluded.progress_log,
                created_at=excluded.created_at
            """,
            (
                stem,
                result.content,
                result.name,
                result.request,
                json.dumps(result.use_ids),
                json.dumps(result.generate_criteria),
                json.dumps(result.slots),
                json.dumps([]),  # progress_log: always empty for now, see class docstring
                (result.created_at or datetime.now(timezone.utc)).isoformat(),
            ),
        )

    def save(self, result: Result, *, filename_stem: str | None = None) -> str:
        stem = filename_stem or result.id or naming.slugify(result.name)
        result.id = stem
        self._conn.execute("BEGIN")
        try:
            self._insert(result, stem)
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        self._conn.execute("COMMIT")
        return stem

    def load(self, filename_stem: str) -> Result:
        row = self._conn.execute("SELECT * FROM results WHERE id = ?", (filename_stem,)).fetchone()
        if row is None:
            raise BlockNotFoundError(f"No result {filename_stem!r} in {self.path}")
        return self._row_to_result(row)

    def all(self) -> list[Result]:
        rows = self._conn.execute("SELECT * FROM results ORDER BY id").fetchall()
        return [self._row_to_result(r) for r in rows]

    def siblings(self, base_slug: str) -> list[Result]:
        rows = self._conn.execute(
            "SELECT * FROM results WHERE id = ? OR id LIKE ? ORDER BY id",
            (base_slug, f"{base_slug}_mut_%"),
        ).fetchall()
        return [self._row_to_result(r) for r in rows]

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
        """Same name-reuse twist as FilesystemResultStorage.save_with_dedup (see its
        docstring) -- a Result's `name` isn't recoverable independent of the row that
        already stores it, but staying consistent with the filesystem backend's exact
        matching semantics matters more than using the (also-correct) stored name here."""
        base_slug = naming.slugify(result.name)
        self._conn.execute("BEGIN IMMEDIATE")
        try:
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
                self._conn.execute("COMMIT")
                return decision, None
            self._insert(result, decision.stem)
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        self._conn.execute("COMMIT")
        result.id = decision.stem
        return decision, decision.stem


class SqliteCredentialsStorage:
    """Stores a single Google OAuth `Credentials` per `user_id` (reserved for future
    multi-tenant use; always `DEFAULT_USER_ID` today), backed by a `credentials` table."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = _connect(self.path)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS credentials (
                user_id TEXT PRIMARY KEY,
                token TEXT NOT NULL,
                refresh_token TEXT,
                client_id TEXT,
                client_secret TEXT,
                expiry TEXT,
                scopes TEXT NOT NULL DEFAULT '[]'
            )
            """
        )

    def save(self, creds: Credentials) -> None:
        self._conn.execute("BEGIN")
        try:
            self._conn.execute(
                """
                INSERT INTO credentials (user_id, token, refresh_token, client_id,
                                          client_secret, expiry, scopes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    token=excluded.token, refresh_token=excluded.refresh_token,
                    client_id=excluded.client_id, client_secret=excluded.client_secret,
                    expiry=excluded.expiry, scopes=excluded.scopes
                """,
                (
                    DEFAULT_USER_ID,
                    creds.token,
                    creds.refresh_token,
                    creds.client_id,
                    creds.client_secret,
                    creds.expiry.isoformat() if creds.expiry else None,
                    json.dumps(list(creds.scopes) if creds.scopes else []),
                ),
            )
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        self._conn.execute("COMMIT")

    def load(self) -> Credentials | None:
        row = self._conn.execute(
            "SELECT * FROM credentials WHERE user_id = ?", (DEFAULT_USER_ID,)
        ).fetchone()
        if row is None:
            return None
        return Credentials(
            token=row["token"],
            refresh_token=row["refresh_token"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=row["client_id"],
            client_secret=row["client_secret"],
            scopes=json.loads(row["scopes"]),
            expiry=datetime.fromisoformat(row["expiry"]) if row["expiry"] else None,
        )


class SqlitePendingSignInStore:
    """Anti-replay/anti-CSRF state for the Google OAuth sign-in flow -- at most one
    pending sign-in attempt exists at a time, backed by a `sign_in_attempts` table."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = _connect(self.path)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sign_in_attempts (
                state TEXT PRIMARY KEY,
                code_verifier TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )

    def start(self) -> tuple[str, str]:
        state = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(64)
        self._conn.execute("BEGIN")
        try:
            self._conn.execute("DELETE FROM sign_in_attempts")
            self._conn.execute(
                "INSERT INTO sign_in_attempts (state, code_verifier, created_at) VALUES (?, ?, ?)",
                (state, code_verifier, datetime.now(timezone.utc).isoformat()),
            )
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        self._conn.execute("COMMIT")
        return state, code_verifier

    def verify_and_consume(self, state: str) -> str | None:
        row = self._conn.execute("SELECT * FROM sign_in_attempts").fetchone()
        if row is None or row["state"] != state:
            return None
        created_at = datetime.fromisoformat(row["created_at"])
        if datetime.now(timezone.utc) - created_at > timedelta(minutes=10):
            return None
        self._conn.execute("BEGIN")
        try:
            self._conn.execute("DELETE FROM sign_in_attempts")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        self._conn.execute("COMMIT")
        return row["code_verifier"]
