import pytest

import constraints
from config import Settings


def _settings_with(tmp_path, **paths):
    s = Settings()
    for task, rel in paths.items():
        setattr(s.constraints, task, str(tmp_path / rel))
    return s


def test_load_reads_an_existing_file(tmp_path):
    (tmp_path / "gen.md").write_text("Don't invent dates.\n", encoding="utf-8")
    settings = _settings_with(tmp_path, generate="gen.md")

    assert constraints.load(settings, "generate") == "Don't invent dates."


def test_load_returns_empty_string_for_a_missing_file(tmp_path):
    settings = _settings_with(tmp_path, mutate="does_not_exist.md")

    assert constraints.load(settings, "mutate") == ""


def test_load_rejects_an_unknown_task():
    with pytest.raises(ValueError):
        constraints.load(Settings(), "not_a_real_task")


def test_load_covers_all_four_tasks(tmp_path):
    for task in ("generate", "naming", "mutate", "compose"):
        (tmp_path / f"{task}.md").write_text(f"{task} rule", encoding="utf-8")
    settings = _settings_with(
        tmp_path,
        generate="generate.md",
        naming="naming.md",
        mutate="mutate.md",
        compose="compose.md",
    )

    for task in ("generate", "naming", "mutate", "compose"):
        assert constraints.load(settings, task) == f"{task} rule"
