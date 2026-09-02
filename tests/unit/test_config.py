from pathlib import Path

import core.config as config
from core.config import Settings, load_settings

PROJECT_CONFIG = Path(__file__).resolve().parent.parent.parent / "config.yaml"


def test_real_config_yaml_sends_naming_local_and_everything_else_to_openrouter():
    """naming is the cheapest, least quality-sensitive task -- it's the one deliberately
    routed to a local Ollama model instead of the pinned OpenRouter default."""
    settings = load_settings(PROJECT_CONFIG)
    assert settings.llm.models.naming.startswith("ollama:")
    assert settings.llm.models.generate.startswith("openrouter:")
    assert settings.llm.models.mutate.startswith("openrouter:")
    assert settings.llm.models.compose.startswith("openrouter:")


def test_defaults_when_config_file_is_missing(tmp_path):
    settings = load_settings(tmp_path / "missing.yaml")
    assert settings.path.blocks_dir == "output/blocks"
    assert settings.llm.models.generate == "openrouter:minimax/minimax-m3:free"
    assert settings.llm.models.naming == "openrouter:minimax/minimax-m3:free"


def test_load_settings_reads_yaml_overrides(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("path:\n  blocks_dir: somewhere/else\n", encoding="utf-8")

    settings = load_settings(p)

    assert settings.path.blocks_dir == "somewhere/else"
    assert settings.path.results_dir == "output/results"  # untouched defaults still apply


def test_resolve_leaves_absolute_paths_alone_and_anchors_relative_ones(tmp_path):
    s = Settings()

    resolved_relative = s.resolve("output/blocks")
    assert resolved_relative.is_absolute()

    absolute_input = tmp_path / "elsewhere"
    assert s.resolve(absolute_input) == absolute_input


def test_openrouter_api_key_reads_from_environment(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-123")
    s = Settings()
    assert s.llm.openrouter.api_key == "sk-test-123"


def test_openrouter_api_key_defaults_to_empty_string(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    s = Settings()
    assert s.llm.openrouter.api_key == ""


def test_load_settings_uses_docker_overrides_when_running_in_docker(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_running_in_docker", lambda: True)
    p = tmp_path / "config.yaml"
    p.write_text("", encoding="utf-8")

    settings = load_settings(p)

    assert settings.llm.ollama.base_url == "http://ollama:11434"
    assert settings.path.storage.backend == "sqlite"


def test_load_settings_keeps_local_defaults_when_not_running_in_docker(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_running_in_docker", lambda: False)
    p = tmp_path / "config.yaml"
    p.write_text("", encoding="utf-8")

    settings = load_settings(p)

    assert settings.llm.ollama.base_url == "http://localhost:11434"
    assert settings.path.storage.backend == "filesystem"
