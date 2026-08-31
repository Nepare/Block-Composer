from pathlib import Path

from parsing.table_to_block import extract_block
from templates import load_block_schema

TEMPLATES_PATH = Path(__file__).resolve().parent.parent / "templates.yaml"


def _para(text, style="NORMAL_TEXT", bullet=False):
    p = {"elements": [{"textRun": {"content": text}}], "paragraphStyle": {"namedStyleType": style}}
    if bullet:
        p["bullet"] = {"listId": "l1"}
    return {"paragraph": p}


def _cell(*elems):
    return {"content": list(elems)}


def _schema():
    return load_block_schema(TEMPLATES_PATH)


def test_extract_block_name_description_and_labeled_field():
    row = {
        "tableCells": [
            _cell(_para("Police Station"), _para("This is a police station.")),
            _cell(_para("Author", style="HEADING_2"), _para("Royal engineering company")),
        ]
    }

    block = extract_block(row, _schema())

    assert block.body.startswith("## Police Station")
    assert "This is a police station." in block.body
    assert "**Author:** Royal engineering company" in block.body
    assert block.schema == "project_entry"
    assert block.tags == ["police_station"]
    assert block.created_by == "dissected"


def test_extract_block_renames_period_to_time_period_via_known_fields():
    row = {
        "tableCells": [
            _cell(_para("X")),
            _cell(_para("Period", style="HEADING_2"), _para("07.2022 - till now")),
        ]
    }

    block = extract_block(row, _schema())

    assert "**Time period:** 07.2022 - till now" in block.body
    assert "**Period:**" not in block.body


def test_extract_block_bullet_list_field_is_rendered_as_a_list():
    row = {
        "tableCells": [
            _cell(_para("X")),
            _cell(
                _para("Rooms", style="HEADING_2"),
                _para("Office", bullet=True),
                _para("Jail", bullet=True),
                _para("Treasury", bullet=True),
            ),
        ]
    }

    block = extract_block(row, _schema())

    assert "**Rooms:**\n- Office\n- Jail\n- Treasury" in block.body


def test_extract_block_flattens_nested_table_field_exactly_once():
    """Some Docs add-ons write a field's heading+value one table deeper than the rest
    (e.g. a computed resource total) -- this must be scanned transparently, not dropped
    and not duplicated."""
    row = {
        "tableCells": [
            _cell(_para("Lumber"), _para("This is a lumber.")),
            _cell(
                _para("Author", style="HEADING_2"),
                _para("Uncle Jack"),
                {
                    "table": {
                        "tableRows": [
                            {
                                "tableCells": [
                                    _cell(
                                        _para("Environment", style="HEADING_2"),
                                        _para("10 wood, 3 wool, 2 iron."),
                                    )
                                ]
                            }
                        ]
                    }
                },
            ),
        ]
    }

    block = extract_block(row, _schema())

    assert "**Environment:** 10 wood, 3 wool, 2 iron." in block.body
    assert block.body.count("**Environment:**") == 1


def test_extract_block_description_joins_multiple_paragraphs():
    row = {
        "tableCells": [
            _cell(_para("Name"), _para("First sentence."), _para("Second sentence.")),
            _cell(_para("Author", style="HEADING_2"), _para("Someone")),
        ]
    }

    block = extract_block(row, _schema())

    assert "First sentence. Second sentence." in block.body


def test_extract_block_empty_row_yields_untitled_without_crashing():
    row = {"tableCells": [_cell(), _cell()]}

    block = extract_block(row, _schema())

    assert block.body.startswith("## untitled")


def test_extract_block_unrecognized_label_is_auto_slugified():
    row = {
        "tableCells": [
            _cell(_para("X")),
            _cell(_para("Special Notes", style="HEADING_2"), _para("Handle with care")),
        ]
    }

    block = extract_block(row, _schema())

    # display_label just title-cases an unrecognized label; the canonical *key* (not
    # asserted on the body, which only shows the display label) would be "special_notes"
    assert "**Special notes:** Handle with care" in block.body
