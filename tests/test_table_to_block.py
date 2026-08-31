from pathlib import Path

from parsing.table_to_block import extract_block
from templates import load_block_schema

TEMPLATES_PATH = Path(__file__).resolve().parent.parent / "templates.yaml"


def _para(text, bold=False, bullet=False, style="HEADING_2"):
    """`style` is set on every paragraph by default (matching the real source doc, where
    both a field's label AND its value are HEADING_2) precisely so it can't be mistaken
    for the label signal -- `bold` is what actually marks a label, verified against the
    live document."""
    run = {"content": text}
    if bold:
        run["textStyle"] = {"bold": True}
    p = {"elements": [{"textRun": run}], "paragraphStyle": {"namedStyleType": style}}
    if bullet:
        p["bullet"] = {"listId": "l1"}
    return {"paragraph": p}


def _label(text):
    return _para(text, bold=True)


def _cell(*elems):
    return {"content": list(elems)}


def _schema():
    return load_block_schema(TEMPLATES_PATH)


# Matches the real "Greentown" doc: HEADING_2 defaults to non-bold, so a label needs an
# explicit bold:true override (see _label()) and a plain value needs no override at all.
STYLE_DEFAULTS = {"HEADING_2": False}


def test_extract_block_name_description_and_labeled_field():
    row = {
        "tableCells": [
            _cell(_para("Police Station"), _para("This is a police station.")),
            _cell(_label("Author"), _para("Royal engineering company")),
        ]
    }

    block = extract_block(row, _schema(), STYLE_DEFAULTS)

    assert block.body.startswith("## Police Station")
    assert "This is a police station." in block.body
    assert "**Author:** Royal engineering company" in block.body
    assert block.schema == "project_entry"
    assert block.tags == ["police_station"]
    assert block.created_by == "dissected"


def test_label_and_value_sharing_the_same_paragraph_style_are_still_distinguished():
    """Regression test: on the real source doc, a field's label AND its value are BOTH
    HEADING_2 paragraphs -- only bold formatting on the run tells them apart. Getting this
    wrong turns every value into its own empty field (found by testing against the live
    doc, not caught by earlier hand-built fixtures that varied paragraphStyle instead)."""
    row = {
        "tableCells": [
            _cell(_para("X")),
            _cell(
                _label("Author"),
                _para("Royal engineering company"),  # same HEADING_2 style, NOT bold
                _label("Period"),
                _para("07.2022 - till now"),
            ),
        ]
    }

    block = extract_block(row, _schema(), STYLE_DEFAULTS)

    assert "**Author:** Royal engineering company" in block.body
    assert "**Time period:** 07.2022 - till now" in block.body
    # the value text must never itself become a field label
    assert "**Royal engineering company:**" not in block.body
    assert "**07.2022 - till now:**" not in block.body


def test_extract_block_renames_period_to_time_period_via_known_fields():
    row = {
        "tableCells": [
            _cell(_para("X")),
            _cell(_label("Period"), _para("07.2022 - till now")),
        ]
    }

    block = extract_block(row, _schema(), STYLE_DEFAULTS)

    assert "**Time period:** 07.2022 - till now" in block.body
    assert "**Period:**" not in block.body


def test_extract_block_bullet_list_field_is_rendered_as_a_list():
    row = {
        "tableCells": [
            _cell(_para("X")),
            _cell(
                _label("Rooms"),
                _para("Office", bullet=True),
                _para("Jail", bullet=True),
                _para("Treasury", bullet=True),
            ),
        ]
    }

    block = extract_block(row, _schema(), STYLE_DEFAULTS)

    assert "**Rooms:**\n- Office\n- Jail\n- Treasury" in block.body


def test_bold_bullet_item_is_never_mistaken_for_a_new_label():
    row = {
        "tableCells": [
            _cell(_para("X")),
            _cell(_label("Rooms"), _para("Office", bold=True, bullet=True)),
        ]
    }

    block = extract_block(row, _schema(), STYLE_DEFAULTS)

    assert "**Rooms:**\n- Office" in block.body
    assert "**Office:**" not in block.body


def test_extract_block_flattens_nested_table_field_exactly_once():
    """Some Docs add-ons write a field's label+value one table deeper than the rest (e.g.
    a computed resource total) -- this must be scanned transparently, not dropped and not
    duplicated. Confirmed against the real doc: both label and value inside the nested
    table are HEADING_2 too, so the bold check must still apply there."""
    row = {
        "tableCells": [
            _cell(_para("Lumber"), _para("This is a lumber.")),
            _cell(
                _label("Author"),
                _para("Uncle Jack"),
                {
                    "table": {
                        "tableRows": [
                            {
                                "tableCells": [
                                    _cell(
                                        _label("Environment"),
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

    block = extract_block(row, _schema(), STYLE_DEFAULTS)

    assert "**Environment:** 10 wood, 3 wool, 2 iron." in block.body
    assert block.body.count("**Environment:**") == 1


def test_extract_block_description_joins_multiple_paragraphs():
    row = {
        "tableCells": [
            _cell(_para("Name"), _para("First sentence."), _para("Second sentence.")),
            _cell(_label("Author"), _para("Someone")),
        ]
    }

    block = extract_block(row, _schema(), STYLE_DEFAULTS)

    assert "First sentence. Second sentence." in block.body


def test_extract_block_empty_row_yields_untitled_without_crashing():
    row = {"tableCells": [_cell(), _cell()]}

    block = extract_block(row, _schema(), STYLE_DEFAULTS)

    assert block.body.startswith("## untitled")


def test_extract_block_unrecognized_label_is_auto_slugified():
    row = {
        "tableCells": [
            _cell(_para("X")),
            _cell(_label("Special Notes"), _para("Handle with care")),
        ]
    }

    block = extract_block(row, _schema(), STYLE_DEFAULTS)

    # display_label just title-cases an unrecognized label; the canonical *key* (not
    # asserted on the body, which only shows the display label) would be "special_notes"
    assert "**Special notes:** Handle with care" in block.body


def test_extract_block_handles_inverted_bold_convention():
    """Regression test for a real second document: HEADING_2 there defaults to BOLD, so
    labels carry no textStyle override at all (inheriting bold) while values explicitly
    set bold:false to opt out. This is the exact opposite of Greentown's convention, and
    reading only the run's own textStyle.bold (ignoring the named style's default) turns
    EVERY paragraph into "not a label" here, silently dropping the whole details column."""
    inverted_defaults = {"HEADING_2": True}

    def para_no_override(text, bullet=False):
        p = {
            "elements": [{"textRun": {"content": text}}],
            "paragraphStyle": {"namedStyleType": "HEADING_2"},
        }
        if bullet:
            p["bullet"] = {"listId": "l1"}
        return {"paragraph": p}

    def para_explicit_not_bold(text, bullet=False):
        p = {
            "elements": [{"textRun": {"content": text, "textStyle": {"bold": False}}}],
            "paragraphStyle": {"namedStyleType": "HEADING_2"},
        }
        if bullet:
            p["bullet"] = {"listId": "l1"}
        return {"paragraph": p}

    row = {
        "tableCells": [
            _cell(_para("GPU Platform"), _para("A GPU driver project.")),
            _cell(
                para_no_override("Project roles"),  # label: no override, inherits bold
                para_explicit_not_bold("Software Engineer"),  # value: explicit opt-out
                para_no_override("Responsibilities"),
                para_explicit_not_bold("Shipped the thing", bullet=True),
            ),
        ]
    }

    block = extract_block(row, _schema(), inverted_defaults)

    assert "**Project roles:** Software Engineer" in block.body
    assert "**Responsibilities:**\n- Shipped the thing" in block.body
