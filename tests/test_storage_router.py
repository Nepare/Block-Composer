import pytest

from config import Settings
from errors import ConfigError
from storage.filesystem import FilesystemBlockStorage, FilesystemResultStorage
from storage.router import get_block_storage, get_result_storage
from storage.sqlite import SqliteBlockStorage, SqliteResultStorage


def test_get_block_storage_dispatches_to_filesystem_by_default(tmp_path):
    settings = Settings()
    settings.blocks_dir = str(tmp_path / "blocks")

    store = get_block_storage(settings)

    assert isinstance(store, FilesystemBlockStorage)
    assert store.root == tmp_path / "blocks"


def test_get_result_storage_dispatches_to_filesystem_by_default(tmp_path):
    settings = Settings()
    settings.results_dir = str(tmp_path / "results")

    store = get_result_storage(settings)

    assert isinstance(store, FilesystemResultStorage)
    assert store.root == tmp_path / "results"


def test_get_block_storage_dispatches_to_sqlite(tmp_path):
    settings = Settings()
    settings.storage.backend = "sqlite"
    settings.storage.sqlite_path = str(tmp_path / "cvdocs.db")

    store = get_block_storage(settings)

    assert isinstance(store, SqliteBlockStorage)
    assert store.path == tmp_path / "cvdocs.db"


def test_get_result_storage_dispatches_to_sqlite(tmp_path):
    settings = Settings()
    settings.storage.backend = "sqlite"
    settings.storage.sqlite_path = str(tmp_path / "cvdocs.db")

    store = get_result_storage(settings)

    assert isinstance(store, SqliteResultStorage)
    assert store.path == tmp_path / "cvdocs.db"


def test_get_block_storage_raises_a_clear_error_for_an_unknown_backend():
    settings = Settings()
    settings.storage.backend = "postgres"

    with pytest.raises(ConfigError, match="postgres"):
        get_block_storage(settings)


def test_get_result_storage_raises_a_clear_error_for_an_unknown_backend():
    settings = Settings()
    settings.storage.backend = "postgres"

    with pytest.raises(ConfigError, match="postgres"):
        get_result_storage(settings)
