"""Storage backend dispatch — mirrors llm/router.py's get_client_and_model: pick a
concrete implementation by a config string, one chokepoint every caller goes through.
"""

from core.config import Settings
from core.errors import ConfigError
from storage.base import BlockStorage, ResultStorage
from storage.filesystem import FilesystemBlockStorage, FilesystemResultStorage
from storage.sqlite import SqliteBlockStorage, SqliteResultStorage


def get_block_storage(settings: Settings) -> BlockStorage:
    if settings.path.storage.backend == "filesystem":
        return FilesystemBlockStorage(settings.blocks_path)
    if settings.path.storage.backend == "sqlite":
        return SqliteBlockStorage(settings.storage_db_path)
    raise ConfigError(f"Unknown storage backend {settings.path.storage.backend!r}.")


def get_result_storage(settings: Settings) -> ResultStorage:
    if settings.path.storage.backend == "filesystem":
        return FilesystemResultStorage(settings.results_path)
    if settings.path.storage.backend == "sqlite":
        return SqliteResultStorage(settings.storage_db_path)
    raise ConfigError(f"Unknown storage backend {settings.path.storage.backend!r}.")
