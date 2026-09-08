import core.config as config
from core.config import Settings, load_settings


def test_load_settings_maps_each_model_task_to_its_own_independent_setting(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(
        "llm:\n"
        "  models:\n"
        "    generate: providera:model-generate\n"
        "    mutate: providerb:model-mutate\n"
        "    compose: providerc:model-compose\n"
        "    naming: providerd:model-naming\n"
        "    keywords: providere:model-keywords\n",
        encoding="utf-8",
    )

    settings = load_settings(p)

    assert settings.llm.models.generate == "providera:model-generate"
    assert settings.llm.models.mutate == "providerb:model-mutate"
    assert settings.llm.models.compose == "providerc:model-compose"
    assert settings.llm.models.naming == "providerd:model-naming"
    assert settings.llm.models.keywords == "providere:model-keywords"


def test_load_settings_allows_naming_and_keywords_to_share_the_same_model(tmp_path):
    """An operator pointing naming and keywords at the same model is a valid configuration
    choice, not an error -- nothing in this system requires them to differ."""
    p = tmp_path / "config.yaml"
    p.write_text(
        "llm:\n  models:\n    naming: shared:one-model\n    keywords: shared:one-model\n",
        encoding="utf-8",
    )

    settings = load_settings(p)

    assert settings.llm.models.naming == "shared:one-model"
    assert settings.llm.models.keywords == "shared:one-model"


def test_defaults_when_config_file_is_missing(tmp_path):
    settings = load_settings(tmp_path / "missing.yaml")
    assert settings.path.blocks_dir == "output/blocks"
    assert settings.llm.models.generate == "openrouter:nvidia/nemotron-3-super-120b-a12b:free"
    assert settings.llm.models.naming == "openrouter:nvidia/nemotron-3-super-120b-a12b:free"
    assert settings.llm.models.keywords == "openrouter:nvidia/nemotron-3-super-120b-a12b:free"


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
