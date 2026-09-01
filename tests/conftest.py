from pathlib import Path

import pytest

from config import Settings

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def settings(tmp_path):
    """A Settings instance pointed entirely at a scratch tmp_path — never touches the
    real output/blocks or output/results directories."""
    s = Settings()
    s.blocks_dir = str(tmp_path / "blocks")
    s.results_dir = str(tmp_path / "results")
    s.templates_path = str(PROJECT_ROOT / "templates.yaml")
    return s


@pytest.fixture
def fake_router(monkeypatch):
    """fake_router(module, client) makes `module.get_client_and_model` always return
    `client`, regardless of which provider:model spec was requested — no network, no key."""

    def _patch(module, client):
        def fake_get_client_and_model(spec, settings, on_progress=None):
            _provider, model = spec.split(":", 1)
            if on_progress is not None:
                from llm.logging_client import LoggingLLMClient

                return LoggingLLMClient(client, on_progress), model
            return client, model

        monkeypatch.setattr(module, "get_client_and_model", fake_get_client_and_model)

    return _patch


@pytest.fixture(autouse=True)
def _clear_llm_router_cache():
    """llm.router caches one client per provider at module scope; reset it between tests
    so a leftover fake from one test can't leak into an unrelated one."""
    import llm.router as router

    router._clients.clear()
    yield
    router._clients.clear()
