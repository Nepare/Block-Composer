from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import cli
from config import Settings

PROJECT_ROOT = Path(__file__).resolve().parent.parent

runner = CliRunner()


@pytest.fixture
def cli_settings(tmp_path, monkeypatch):
    """Points cli._settings() at a scratch Settings instance instead of the real
    config.yaml/output dirs, and hands the instance back for assertions."""
    s = Settings()
    s.blocks_dir = str(tmp_path / "blocks")
    s.results_dir = str(tmp_path / "results")
    s.templates_path = str(PROJECT_ROOT / "templates.yaml")
    monkeypatch.setattr(cli, "_settings", lambda: s)
    return s


def test_generate_criteria_file_is_read_and_passed_through(tmp_path, cli_settings, monkeypatch):
    criteria_path = tmp_path / "criteria.md"
    criteria_path.write_text("a rugged frontier outpost", encoding="utf-8")
    captured = {}

    def fake_run_generate(criteria, **kwargs):
        captured["criteria"] = criteria
        return SimpleNamespace(), SimpleNamespace(action="save_plain", duplicate_of=None), tmp_path / "result.md"

    monkeypatch.setattr(cli.generate_module, "run_generate", fake_run_generate)

    result = runner.invoke(cli.app, ["generate", "--criteria-file", str(criteria_path)])

    assert result.exit_code == 0
    assert captured["criteria"] == "a rugged frontier outpost"


def test_generate_both_inline_and_file_given_fails_clearly(tmp_path, cli_settings):
    criteria_path = tmp_path / "criteria.md"
    criteria_path.write_text("x", encoding="utf-8")

    result = runner.invoke(cli.app, ["generate", "--criteria", "y", "--criteria-file", str(criteria_path)])

    assert result.exit_code == 1
    assert "--criteria" in result.output
    assert "--criteria-file" in result.output


def test_compose_request_file_is_read_and_passed_through(tmp_path, cli_settings, monkeypatch):
    request_path = tmp_path / "request.md"
    request_path.write_text("aim for 2 backend projects", encoding="utf-8")
    captured = {}

    def fake_run_compose(request, **kwargs):
        captured["request"] = request
        return [], None

    monkeypatch.setattr(cli.compose_module, "run_compose", fake_run_compose)

    result = runner.invoke(cli.app, ["compose", "--request-file", str(request_path), "--dry-run"])

    assert result.exit_code == 0
    assert captured["request"] == "aim for 2 backend projects"
