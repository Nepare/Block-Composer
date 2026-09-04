from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import cli
from core.config import Settings
from core.errors import InputError
from models.blocks import Block
from storage.base import Result
from storage.router import get_block_storage, get_result_storage
from tools.compose import ComposeOutcome

MOCK_TEMPLATES = Path(__file__).resolve().parent / "fixtures" / "templates.yaml"

runner = CliRunner()


@pytest.fixture
def cli_settings(tmp_path, monkeypatch):
    """Points cli._settings() at a scratch Settings instance instead of the real
    config.yaml/output dirs, and hands the instance back for assertions."""
    s = Settings()
    s.path.blocks_dir = str(tmp_path / "blocks")
    s.path.results_dir = str(tmp_path / "results")
    s.path.templates_path = str(MOCK_TEMPLATES)
    monkeypatch.setattr(cli, "_settings", lambda: s)
    return s


def test_generate_criteria_file_is_read_and_passed_through(tmp_path, cli_settings, monkeypatch):
    criteria_path = tmp_path / "criteria.md"
    criteria_path.write_text("a rugged frontier outpost", encoding="utf-8")
    captured = {}

    def fake_run_generate(criteria, **kwargs):
        captured["criteria"] = criteria
        return SimpleNamespace(), SimpleNamespace(action="save_plain", duplicate_of=None), "result"

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


def test_generate_name_is_passed_through(cli_settings, monkeypatch):
    captured = {}

    def fake_run_generate(criteria, **kwargs):
        captured["name"] = kwargs.get("name")
        return SimpleNamespace(), SimpleNamespace(action="save_plain", duplicate_of=None), "result"

    monkeypatch.setattr(cli.generate_module, "run_generate", fake_run_generate)

    result = runner.invoke(cli.app, ["generate", "--criteria", "x", "--name", "widget"])

    assert result.exit_code == 0
    assert captured["name"] == "widget"


def test_mutate_name_is_passed_through(cli_settings, monkeypatch):
    captured = {}

    def fake_run_mutate(block_id, criteria, **kwargs):
        captured["name"] = kwargs.get("name")
        return SimpleNamespace(), "result"

    monkeypatch.setattr(cli.mutate_module, "run_mutate", fake_run_mutate)

    result = runner.invoke(cli.app, ["mutate", "some-id", "--criteria", "x", "--name", "widget"])

    assert result.exit_code == 0
    assert captured["name"] == "widget"


def test_mutate_input_error_fails_clearly(cli_settings, monkeypatch):
    def fake_run_mutate(block_id, criteria, **kwargs):
        raise InputError("name and --in-place cannot be combined")

    monkeypatch.setattr(cli.mutate_module, "run_mutate", fake_run_mutate)

    result = runner.invoke(cli.app, ["mutate", "some-id", "--criteria", "x", "--name", "widget", "--in-place"])

    assert result.exit_code == 1
    assert "in-place" in result.output


def test_compose_name_is_passed_through(cli_settings, monkeypatch):
    captured = {}

    def fake_run_compose(request, **kwargs):
        captured["name"] = kwargs.get("name")
        return ComposeOutcome(slots=[], result_path=None, result_id=None, name=None, content=None, cancelled=False)

    monkeypatch.setattr(cli.compose_module, "run_compose", fake_run_compose)

    result = runner.invoke(cli.app, ["compose", "some request", "--name", "widget", "--dry-run"])

    assert result.exit_code == 0
    assert captured["name"] == "widget"


def test_compose_request_file_is_read_and_passed_through(tmp_path, cli_settings, monkeypatch):
    request_path = tmp_path / "request.md"
    request_path.write_text("aim for 2 backend projects", encoding="utf-8")
    captured = {}

    def fake_run_compose(request, **kwargs):
        captured["request"] = request
        return ComposeOutcome(slots=[], result_path=None, result_id=None, name=None, content=None, cancelled=False)

    monkeypatch.setattr(cli.compose_module, "run_compose", fake_run_compose)

    result = runner.invoke(cli.app, ["compose", "--request-file", str(request_path), "--dry-run"])

    assert result.exit_code == 0
    assert captured["request"] == "aim for 2 backend projects"


def test_compose_count_is_passed_through(tmp_path, cli_settings, monkeypatch):
    captured = {}

    def fake_run_compose(request, **kwargs):
        captured["count"] = kwargs.get("count")
        return ComposeOutcome(slots=[], result_path=None, result_id=None, name=None, content=None, cancelled=False)

    monkeypatch.setattr(cli.compose_module, "run_compose", fake_run_compose)

    result = runner.invoke(cli.app, ["compose", "some request", "--count", "5", "--dry-run"])

    assert result.exit_code == 0
    assert captured["count"] == 5


def test_compose_count_defaults_to_none(tmp_path, cli_settings, monkeypatch):
    captured = {}

    def fake_run_compose(request, **kwargs):
        captured["count"] = kwargs.get("count")
        return ComposeOutcome(slots=[], result_path=None, result_id=None, name=None, content=None, cancelled=False)

    monkeypatch.setattr(cli.compose_module, "run_compose", fake_run_compose)

    result = runner.invoke(cli.app, ["compose", "some request", "--dry-run"])

    assert result.exit_code == 0
    assert captured["count"] is None


def test_blocks_delete_removes_existing_block(cli_settings):
    store = get_block_storage(cli_settings)
    store.save(Block(id="", body="# A block\nbody text"), filename_stem="a-block")

    result = runner.invoke(cli.app, ["blocks", "delete", "a-block"])

    assert result.exit_code == 0
    assert "a-block" in result.output
    assert not store.exists("a-block")


def test_blocks_delete_missing_id_fails(cli_settings):
    result = runner.invoke(cli.app, ["blocks", "delete", "does-not-exist"])

    assert result.exit_code == 1
    assert "does-not-exist" in result.output


def test_results_delete_removes_existing_result(cli_settings):
    store = get_result_storage(cli_settings)
    store.save(Result(id="", content="result body", name="a-result", request="req"), filename_stem="a-result")

    result = runner.invoke(cli.app, ["results", "delete", "a-result"])

    assert result.exit_code == 0
    assert "a-result" in result.output
    assert not store.exists("a-result")


def test_results_delete_missing_id_fails(cli_settings):
    result = runner.invoke(cli.app, ["results", "delete", "does-not-exist"])

    assert result.exit_code == 1
    assert "does-not-exist" in result.output


def test_results_list_empty_is_not_an_error(cli_settings):
    result = runner.invoke(cli.app, ["results", "list"])

    assert result.exit_code == 0


def test_results_list_shows_saved_result(cli_settings):
    store = get_result_storage(cli_settings)
    store.save(
        Result(id="", content="body", name="cover-letter", request="write a cover letter"),
        filename_stem="cover-letter",
    )

    result = runner.invoke(cli.app, ["results", "list"])

    assert result.exit_code == 0
    assert "cover-letter" in result.output
    assert "write a cover letter" in result.output


def test_results_list_query_filters_to_matching_result(cli_settings):
    store = get_result_storage(cli_settings)
    store.save(Result(id="", content="body", name="frontend-summary", request="x"), filename_stem="frontend-summary")
    store.save(Result(id="", content="body", name="backend-summary", request="y"), filename_stem="backend-summary")

    result = runner.invoke(cli.app, ["results", "list", "--query", "frontend"])

    assert result.exit_code == 0
    assert "frontend-summary" in result.output
    assert "backend-summary" not in result.output


def test_results_show_prints_content_and_request_metadata(cli_settings):
    store = get_result_storage(cli_settings)
    store.save(
        Result(
            id="",
            content="the full result content",
            name="a-result",
            request="aim for 2 backend projects",
            use_ids=["block-1", "block-2"],
            generate_criteria=["a rugged frontier outpost"],
        ),
        filename_stem="a-result",
    )

    result = runner.invoke(cli.app, ["results", "show", "a-result"])

    assert result.exit_code == 0
    assert "the full result content" in result.output
    assert "aim for 2 backend projects" in result.output
    assert "block-1" in result.output
    assert "block-2" in result.output
    assert "a rugged frontier outpost" in result.output


def test_results_show_missing_id_fails(cli_settings):
    result = runner.invoke(cli.app, ["results", "show", "does-not-exist"])

    assert result.exit_code == 1
    assert "does-not-exist" in result.output
