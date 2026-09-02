import re

import pytest

from core.errors import InputError
from core.text_input import resolve_text_input


def test_inline_only_returns_stripped_text():
    result = resolve_text_input("  hello world  ", None, flag_inline="--criteria", flag_file="--criteria-file")

    assert result == "hello world"


def test_file_only_returns_stripped_file_content(tmp_path):
    path = tmp_path / "criteria.md"
    path.write_text("  build a rocket  \n", encoding="utf-8")

    result = resolve_text_input(None, path, flag_inline="--criteria", flag_file="--criteria-file")

    assert result == "build a rocket"


def test_missing_file_raises_input_error(tmp_path):
    path = tmp_path / "does_not_exist.md"

    with pytest.raises(InputError, match=re.escape(str(path))):
        resolve_text_input(None, path, flag_inline="--criteria", flag_file="--criteria-file")


def test_both_inline_and_file_given_raises_input_error(tmp_path):
    path = tmp_path / "criteria.md"
    path.write_text("content", encoding="utf-8")

    with pytest.raises(InputError, match="--criteria.*--criteria-file"):
        resolve_text_input("inline text", path, flag_inline="--criteria", flag_file="--criteria-file")


def test_neither_given_and_required_raises_input_error():
    with pytest.raises(InputError):
        resolve_text_input(None, None, flag_inline="--criteria", flag_file="--criteria-file")


def test_neither_given_and_not_required_returns_empty_string():
    result = resolve_text_input(
        None, None, flag_inline="the request argument", flag_file="--request-file", required=False
    )

    assert result == ""


def test_empty_inline_string_is_treated_as_not_given():
    # compose's request positional defaults to "" -- must not be mistaken for a real value
    result = resolve_text_input("", None, flag_inline="the request argument", flag_file="--request-file", required=False)

    assert result == ""


def test_non_ascii_file_content_round_trips(tmp_path):
    path = tmp_path / "criteria.md"
    path.write_text("Café — 日本語", encoding="utf-8")

    result = resolve_text_input(None, path, flag_inline="--criteria", flag_file="--criteria-file")

    assert result == "Café — 日本語"
