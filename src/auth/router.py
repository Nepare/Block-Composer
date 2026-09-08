"""Auth provider dispatch — mirrors storage/router.py's get_block_storage: pick a
concrete implementation by a config string, one chokepoint every caller goes through.
"""

from auth.base import AuthProvider
from auth.installed_app import InstalledAppAuthProvider
from auth.web import WebAuthProvider
from core.config import Settings
from core.errors import ConfigError
from storage.filesystem import FilesystemCredentialsStorage
from storage.sqlite import SqliteCredentialsStorage


def get_auth_provider(settings: Settings) -> AuthProvider:
    if settings.path.storage.backend == "filesystem":
        storage = FilesystemCredentialsStorage(
            settings.resolve(settings.auth.google.token_path), settings.auth.google.scopes
        )
        return InstalledAppAuthProvider(settings, storage)
    if settings.path.storage.backend == "sqlite":
        storage = SqliteCredentialsStorage(settings.storage_db_path)
        return WebAuthProvider(settings, storage)
    raise ConfigError(f"Unknown storage backend {settings.path.storage.backend!r}.")


def get_web_auth_provider(settings: Settings) -> WebAuthProvider:
    """The hosted web app's own OAuth routes always need WebAuthProvider — it's the only
    provider with build_authorization_url/exchange_code — regardless of path.storage.backend,
    which governs unrelated block/result storage."""
    storage = SqliteCredentialsStorage(settings.storage_db_path)
    return WebAuthProvider(settings, storage)
