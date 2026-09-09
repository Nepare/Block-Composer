from pathlib import Path
from types import SimpleNamespace

import pytest
from rich.console import Console
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


@pytest.fixture(autouse=True)
def _no_forced_color(monkeypatch):
    """cli.console is a module-level Console() singleton whose color-system detection is
    cached at construction time — a FORCE_COLOR/CLICOLOR_FORCE env var picked up back at
    import time would survive any later per-test env change, so swap in a fresh no-color
    Console rather than relying on env alone to keep ANSI codes out of result.output."""
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.delenv("CLICOLOR_FORCE", raising=False)
    monkeypatch.setattr(cli, "console", Console(no_color=True))


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


def test_generate_preserve_flag_is_passed_through(cli_settings, monkeypatch):
    captured = {}

    def fake_run_generate(criteria, **kwargs):
        captured["preserve"] = kwargs.get("preserve")
        return SimpleNamespace(), SimpleNamespace(action="save_plain", duplicate_of=None), "result"

    monkeypatch.setattr(cli.generate_module, "run_generate", fake_run_generate)

    result = runner.invoke(cli.app, ["generate", "--criteria", "x", "--preserve"])

    assert result.exit_code == 0
    assert captured["preserve"] is True


def test_generate_without_preserve_flag_defaults_to_false(cli_settings, monkeypatch):
    captured = {}

    def fake_run_generate(criteria, **kwargs):
        captured["preserve"] = kwargs.get("preserve")
        return SimpleNamespace(), SimpleNamespace(action="save_plain", duplicate_of=None), "result"

    monkeypatch.setattr(cli.generate_module, "run_generate", fake_run_generate)

    result = runner.invoke(cli.app, ["generate", "--criteria", "x"])

    assert result.exit_code == 0
    assert captured["preserve"] is False


def test_mutate_preserve_flag_is_passed_through(cli_settings, monkeypatch):
    captured = {}

    def fake_run_mutate(block_id, criteria, **kwargs):
        captured["preserve"] = kwargs.get("preserve")
        return SimpleNamespace(), "result"

    monkeypatch.setattr(cli.mutate_module, "run_mutate", fake_run_mutate)

    result = runner.invoke(cli.app, ["mutate", "some-id", "--criteria", "x", "--preserve"])

    assert result.exit_code == 0
    assert captured["preserve"] is True


def test_mutate_preserve_combined_with_in_place(cli_settings, monkeypatch):
    captured = {}

    def fake_run_mutate(block_id, criteria, **kwargs):
        captured["preserve"] = kwargs.get("preserve")
        captured["in_place"] = kwargs.get("in_place")
        return SimpleNamespace(), "result"

    monkeypatch.setattr(cli.mutate_module, "run_mutate", fake_run_mutate)

    result = runner.invoke(cli.app, ["mutate", "some-id", "--criteria", "x", "--preserve", "--in-place"])

    assert result.exit_code == 0
    assert captured["preserve"] is True
    assert captured["in_place"] is True


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


def test_compose_preserve_flag_is_passed_through(cli_settings, monkeypatch):
    captured = {}

    def fake_run_compose(request, **kwargs):
        captured["preserve"] = kwargs.get("preserve")
        return ComposeOutcome(slots=[], result_path=None, result_id=None, name=None, content=None, cancelled=False)

    monkeypatch.setattr(cli.compose_module, "run_compose", fake_run_compose)

    result = runner.invoke(cli.app, ["compose", "some request", "--preserve", "--dry-run"])

    assert result.exit_code == 0
    assert captured["preserve"] is True


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


def test_blocks_preserve_marks_existing_block_preserved(cli_settings):
    store = get_block_storage(cli_settings)
    store.save(Block(id="", body="# A block\nbody text"), filename_stem="a-block")

    result = runner.invoke(cli.app, ["blocks", "preserve", "a-block"])

    assert result.exit_code == 0
    assert store.load("a-block").preserved is True


def test_blocks_preserve_is_idempotent(cli_settings):
    store = get_block_storage(cli_settings)
    store.save(Block(id="", body="# A block\nbody text"), filename_stem="a-block")

    result1 = runner.invoke(cli.app, ["blocks", "preserve", "a-block"])
    result2 = runner.invoke(cli.app, ["blocks", "preserve", "a-block"])

    assert result1.exit_code == 0
    assert result2.exit_code == 0
    assert store.load("a-block").preserved is True


def test_blocks_unpreserve_marks_preserved_block_not_preserved(cli_settings):
    store = get_block_storage(cli_settings)
    store.save(Block(id="", body="# A block\nbody text"), filename_stem="a-block")
    runner.invoke(cli.app, ["blocks", "preserve", "a-block"])

    result = runner.invoke(cli.app, ["blocks", "unpreserve", "a-block"])

    assert result.exit_code == 0
    assert store.load("a-block").preserved is False


def test_blocks_unpreserve_is_idempotent(cli_settings):
    store = get_block_storage(cli_settings)
    store.save(Block(id="", body="# A block\nbody text"), filename_stem="a-block")

    result = runner.invoke(cli.app, ["blocks", "unpreserve", "a-block"])

    assert result.exit_code == 0
    assert store.load("a-block").preserved is False


def test_blocks_preserve_missing_id_fails(cli_settings):
    result = runner.invoke(cli.app, ["blocks", "preserve", "does-not-exist"])

    assert result.exit_code == 1
    assert "does-not-exist" in result.output


def test_blocks_show_reflects_preserved_state(cli_settings):
    store = get_block_storage(cli_settings)
    store.save(Block(id="", body="# A block\nbody text"), filename_stem="a-block")
    runner.invoke(cli.app, ["blocks", "preserve", "a-block"])

    result = runner.invoke(cli.app, ["blocks", "show", "a-block"])

    assert result.exit_code == 0
    assert "Preserved" in result.output
    assert "True" in result.output


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


def test_results_preserve_marks_existing_result_preserved(cli_settings):
    store = get_result_storage(cli_settings)
    store.save(Result(id="", content="result body", name="a-result", request="req"), filename_stem="a-result")

    result = runner.invoke(cli.app, ["results", "preserve", "a-result"])

    assert result.exit_code == 0
    assert store.load("a-result").preserved is True


def test_results_preserve_is_idempotent(cli_settings):
    store = get_result_storage(cli_settings)
    store.save(Result(id="", content="result body", name="a-result", request="req"), filename_stem="a-result")

    result1 = runner.invoke(cli.app, ["results", "preserve", "a-result"])
    result2 = runner.invoke(cli.app, ["results", "preserve", "a-result"])

    assert result1.exit_code == 0
    assert result2.exit_code == 0
    assert store.load("a-result").preserved is True


def test_results_unpreserve_marks_preserved_result_not_preserved(cli_settings):
    store = get_result_storage(cli_settings)
    store.save(Result(id="", content="result body", name="a-result", request="req"), filename_stem="a-result")
    runner.invoke(cli.app, ["results", "preserve", "a-result"])

    result = runner.invoke(cli.app, ["results", "unpreserve", "a-result"])

    assert result.exit_code == 0
    assert store.load("a-result").preserved is False


def test_results_unpreserve_is_idempotent(cli_settings):
    store = get_result_storage(cli_settings)
    store.save(Result(id="", content="result body", name="a-result", request="req"), filename_stem="a-result")

    result = runner.invoke(cli.app, ["results", "unpreserve", "a-result"])

    assert result.exit_code == 0
    assert store.load("a-result").preserved is False


def test_results_preserve_missing_id_fails(cli_settings):
    result = runner.invoke(cli.app, ["results", "preserve", "does-not-exist"])

    assert result.exit_code == 1
    assert "does-not-exist" in result.output


def test_results_show_reflects_preserved_state(cli_settings):
    store = get_result_storage(cli_settings)
    store.save(Result(id="", content="result body", name="a-result", request="req"), filename_stem="a-result")
    runner.invoke(cli.app, ["results", "preserve", "a-result"])

    result = runner.invoke(cli.app, ["results", "show", "a-result"])

    assert result.exit_code == 0
    assert "Preserved" in result.output
    assert "True" in result.output


def test_blocks_clear_removes_unpreserved_keeps_preserved(cli_settings):
    store = get_block_storage(cli_settings)
    store.save(Block(id="", body="# Block 1\nbody"), filename_stem="block-1")
    store.save(Block(id="", body="# Block 2\nbody"), filename_stem="block-2")
    store.save(Block(id="", body="# Block 3\nbody"), filename_stem="block-3")
    runner.invoke(cli.app, ["blocks", "preserve", "block-2"])

    result = runner.invoke(cli.app, ["blocks", "clear"])

    assert result.exit_code == 0
    assert "deleted=2" in result.output
    assert "skipped_preserved=1" in result.output
    assert not store.exists("block-1")
    assert store.exists("block-2")
    assert not store.exists("block-3")


def test_blocks_clear_on_empty_library_reports_zero(cli_settings):
    result = runner.invoke(cli.app, ["blocks", "clear"])

    assert result.exit_code == 0
    assert "deleted=0" in result.output
    assert "skipped_preserved=0" in result.output


def test_blocks_clear_all_preserved_deletes_nothing(cli_settings):
    store = get_block_storage(cli_settings)
    store.save(Block(id="", body="# Block 1\nbody"), filename_stem="block-1")
    store.save(Block(id="", body="# Block 2\nbody"), filename_stem="block-2")
    runner.invoke(cli.app, ["blocks", "preserve", "block-1"])
    runner.invoke(cli.app, ["blocks", "preserve", "block-2"])

    result = runner.invoke(cli.app, ["blocks", "clear"])

    assert result.exit_code == 0
    assert "deleted=0" in result.output
    assert "skipped_preserved=2" in result.output
    assert store.exists("block-1")
    assert store.exists("block-2")


def test_blocks_clear_does_not_affect_results(cli_settings):
    block_store = get_block_storage(cli_settings)
    result_store = get_result_storage(cli_settings)
    block_store.save(Block(id="", body="# A block\nbody text"), filename_stem="a-block")
    result_store.save(Result(id="", content="result body", name="a-result", request="req"), filename_stem="a-result")

    result = runner.invoke(cli.app, ["blocks", "clear"])

    assert result.exit_code == 0
    assert result_store.exists("a-result")


def test_results_clear_on_empty_library_reports_zero(cli_settings):
    result = runner.invoke(cli.app, ["results", "clear"])

    assert result.exit_code == 0
    assert "deleted=0" in result.output
    assert "skipped_preserved=0" in result.output


def test_results_clear_removes_unpreserved_keeps_preserved(cli_settings):
    store = get_result_storage(cli_settings)
    store.save(Result(id="", content="body", name="result-1", request="req"), filename_stem="result-1")
    store.save(Result(id="", content="body", name="result-2", request="req"), filename_stem="result-2")
    store.save(Result(id="", content="body", name="result-3", request="req"), filename_stem="result-3")
    runner.invoke(cli.app, ["results", "preserve", "result-2"])

    result = runner.invoke(cli.app, ["results", "clear"])

    assert result.exit_code == 0
    assert "deleted=2" in result.output
    assert "skipped_preserved=1" in result.output
    assert not store.exists("result-1")
    assert store.exists("result-2")
    assert not store.exists("result-3")


def test_results_clear_all_preserved_deletes_nothing(cli_settings):
    store = get_result_storage(cli_settings)
    store.save(Result(id="", content="body", name="result-1", request="req"), filename_stem="result-1")
    store.save(Result(id="", content="body", name="result-2", request="req"), filename_stem="result-2")
    runner.invoke(cli.app, ["results", "preserve", "result-1"])
    runner.invoke(cli.app, ["results", "preserve", "result-2"])

    result = runner.invoke(cli.app, ["results", "clear"])

    assert result.exit_code == 0
    assert "deleted=0" in result.output
    assert "skipped_preserved=2" in result.output
    assert store.exists("result-1")
    assert store.exists("result-2")


def test_results_clear_does_not_affect_blocks(cli_settings):
    block_store = get_block_storage(cli_settings)
    result_store = get_result_storage(cli_settings)
    block_store.save(Block(id="", body="# A block\nbody text"), filename_stem="a-block")
    result_store.save(Result(id="", content="result body", name="a-result", request="req"), filename_stem="a-result")

    result = runner.invoke(cli.app, ["results", "clear"])

    assert result.exit_code == 0
    assert block_store.exists("a-block")


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
        ),
        filename_stem="a-result",
    )

    result = runner.invoke(cli.app, ["results", "show", "a-result"])

    assert result.exit_code == 0
    assert "the full result content" in result.output
    assert "aim for 2 backend projects" in result.output


def test_results_show_missing_id_fails(cli_settings):
    result = runner.invoke(cli.app, ["results", "show", "does-not-exist"])

    assert result.exit_code == 1
    assert "does-not-exist" in result.output
