import pytest

from auth.installed_app import InstalledAppAuthProvider
from auth.router import get_auth_provider
from auth.web import WebAuthProvider
from config import Settings, load_settings
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


def test_get_auth_provider_dispatches_to_installed_app_for_filesystem(tmp_path):
    settings = Settings()
    settings.google.token_path = str(tmp_path / "token.json")

    provider = get_auth_provider(settings)

    assert isinstance(provider, InstalledAppAuthProvider)


def test_get_auth_provider_dispatches_to_web_for_sqlite(tmp_path):
    settings = Settings()
    settings.storage.backend = "sqlite"
    settings.storage.sqlite_path = str(tmp_path / "cvdocs.db")

    provider = get_auth_provider(settings)

    assert isinstance(provider, WebAuthProvider)


def test_get_auth_provider_raises_a_clear_error_for_an_unknown_backend():
    settings = Settings()
    settings.storage.backend = "postgres"

    with pytest.raises(ConfigError, match="postgres"):
        get_auth_provider(settings)


def test_get_auth_provider_follows_the_cvdocs_storage_backend_env_override(tmp_path, monkeypatch):
    """FR-007: connection method is a consequence of deployment mode alone — the same
    env var that already decides storage.backend (no separate 'which auth flow' setting)."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"storage:\n  backend: filesystem\n  sqlite_path: {tmp_path / 'cvdocs.db'}\n"
        f"google:\n  token_path: {tmp_path / 'token.json'}\n",
        encoding="utf-8",
    )

    monkeypatch.delenv("CVDOCS_STORAGE_BACKEND", raising=False)
    local_settings = load_settings(config_path)
    assert isinstance(get_auth_provider(local_settings), InstalledAppAuthProvider)

    monkeypatch.setenv("CVDOCS_STORAGE_BACKEND", "sqlite")
    hosted_settings = load_settings(config_path)
    assert isinstance(get_auth_provider(hosted_settings), WebAuthProvider)
