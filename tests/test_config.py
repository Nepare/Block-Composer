from config import Settings, load_settings


def test_defaults_when_config_file_is_missing(tmp_path):
    settings = load_settings(tmp_path / "missing.yaml")
    assert settings.blocks_dir == "output/blocks"
    assert settings.models.generate == "openrouter:openrouter/free"
    assert settings.models.naming == "openrouter:openrouter/free"


def test_load_settings_reads_yaml_overrides(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("blocks_dir: somewhere/else\n", encoding="utf-8")

    settings = load_settings(p)

    assert settings.blocks_dir == "somewhere/else"
    assert settings.results_dir == "output/results"  # untouched defaults still apply


def test_resolve_leaves_absolute_paths_alone_and_anchors_relative_ones(tmp_path):
    s = Settings()

    resolved_relative = s.resolve("output/blocks")
    assert resolved_relative.is_absolute()

    absolute_input = tmp_path / "elsewhere"
    assert s.resolve(absolute_input) == absolute_input


def test_openrouter_api_key_reads_from_environment(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-123")
    s = Settings()
    assert s.openrouter.api_key == "sk-test-123"


def test_openrouter_api_key_defaults_to_empty_string(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    s = Settings()
    assert s.openrouter.api_key == ""
