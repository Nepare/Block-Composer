import pytest

from core.errors import DocsApiError
from parsing.structural_walk import find_blocks_table


def _para(text):
    return {"paragraph": {"elements": [{"textRun": {"content": text}}]}}


def _cell(*elems):
    return {"content": list(elems)}


def test_finds_table_after_marker_row_and_ignores_other_tables():
    marker_row = {"tableCells": [_cell(_para("Projects")), _cell(_para(""))]}
    block_row = {"tableCells": [_cell(_para("Police Station")), _cell(_para("Author"))]}
    unrelated_row = {"tableCells": [_cell(_para("Location")), _cell(_para("UK"))]}
    doc = {
        "body": {
            "content": [
                {"paragraph": _para("Greentown")},
                {"table": {"tableRows": [unrelated_row]}},  # right cell non-empty -> not a marker row
                {"table": {"tableRows": [marker_row, block_row]}},
            ]
        }
    }

    result = find_blocks_table(doc, section_marker="Projects", table_columns=2)

    assert result.rows == [block_row]


def test_ignores_table_with_wrong_column_count():
    marker_row_3col = {"tableCells": [_cell(_para("Projects")), _cell(_para("")), _cell(_para(""))]}
    doc = {"body": {"content": [{"table": {"tableRows": [marker_row_3col]}}]}}

    with pytest.raises(DocsApiError):
        find_blocks_table(doc, section_marker="Projects", table_columns=2)


def test_raises_when_no_marker_table_found():
    doc = {"body": {"content": [{"paragraph": _para("nothing here")}]}}

    with pytest.raises(DocsApiError):
        find_blocks_table(doc, section_marker="Projects", table_columns=2)


def test_marker_match_is_case_insensitive_and_substring():
    marker_row = {"tableCells": [_cell(_para("--- PROJECTS ---")), _cell(_para(""))]}
    block_row = {"tableCells": [_cell(_para("X")), _cell(_para("Y"))]}
    doc = {"body": {"content": [{"table": {"tableRows": [marker_row, block_row]}}]}}

    result = find_blocks_table(doc, section_marker="Projects", table_columns=2)

    assert result.rows == [block_row]


def test_marker_row_with_nonempty_right_cell_is_not_treated_as_a_marker():
    almost_marker = {"tableCells": [_cell(_para("Projects")), _cell(_para("not empty"))]}
    doc = {"body": {"content": [{"table": {"tableRows": [almost_marker]}}]}}

    with pytest.raises(DocsApiError):
        find_blocks_table(doc, section_marker="Projects", table_columns=2)


def test_empty_table_is_skipped_without_error():
    marker_row = {"tableCells": [_cell(_para("Projects")), _cell(_para(""))]}
    block_row = {"tableCells": [_cell(_para("X")), _cell(_para("Y"))]}
    doc = {
        "body": {
            "content": [
                {"table": {"tableRows": []}},
                {"table": {"tableRows": [marker_row, block_row]}},
            ]
        }
    }

    result = find_blocks_table(doc, section_marker="Projects", table_columns=2)

    assert result.rows == [block_row]
