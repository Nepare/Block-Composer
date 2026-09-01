"""Auth provider dispatch — mirrors storage/router.py's get_block_storage: pick a
concrete implementation by a config string, one chokepoint every caller goes through.
"""

from auth.base import AuthProvider
from auth.installed_app import InstalledAppAuthProvider
from auth.web import WebAuthProvider
from config import Settings
from errors import ConfigError
from storage.filesystem import FilesystemCredentialsStorage
from storage.sqlite import SqliteCredentialsStorage


def get_auth_provider(settings: Settings) -> AuthProvider:
    if settings.storage.backend == "filesystem":
        storage = FilesystemCredentialsStorage(
            settings.resolve(settings.google.token_path), settings.google.scopes
        )
        return InstalledAppAuthProvider(settings, storage)
    if settings.storage.backend == "sqlite":
        storage = SqliteCredentialsStorage(settings.storage_db_path)
        return WebAuthProvider(settings, storage)
    raise ConfigError(f"Unknown storage backend {settings.storage.backend!r}.")
