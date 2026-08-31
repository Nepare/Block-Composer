from pathlib import Path

import pytest

from errors import TemplateError
from templates import BlockSchema, KnownField, load_block_schema

PROJECT_TEMPLATES = Path(__file__).resolve().parent.parent / "templates.yaml"


def test_load_real_project_templates_yaml():
    schema = load_block_schema(PROJECT_TEMPLATES)
    assert schema.name == "project_entry"
    assert schema.section_marker == "Projects"
    assert schema.table_columns == 2
    assert schema.tag_fields == ["name"]
    assert any(kf.label == "Period" and kf.name == "time_period" for kf in schema.known_fields)


def test_missing_file_raises(tmp_path):
    with pytest.raises(TemplateError):
        load_block_schema(tmp_path / "nope.yaml")


def test_missing_block_schema_key_raises(tmp_path):
    p = tmp_path / "templates.yaml"
    p.write_text("something_else: 1\n", encoding="utf-8")
    with pytest.raises(TemplateError):
        load_block_schema(p)


def test_missing_section_marker_raises(tmp_path):
    p = tmp_path / "templates.yaml"
    p.write_text("block_schema:\n  name: x\n  table_columns: 2\n", encoding="utf-8")
    with pytest.raises(TemplateError):
        load_block_schema(p)


def test_table_columns_defaults_to_two(tmp_path):
    p = tmp_path / "templates.yaml"
    p.write_text("block_schema:\n  section_marker: Projects\n", encoding="utf-8")
    schema = load_block_schema(p)
    assert schema.table_columns == 2
    assert schema.name == "project_entry"
    assert schema.tag_fields == ["name"]


def test_canonical_name_uses_known_field_override_case_insensitively():
    schema = BlockSchema(
        name="s",
        section_marker="Projects",
        table_columns=2,
        known_fields=[KnownField(label="Period", name="time_period")],
    )
    assert schema.canonical_name("Period") == "time_period"
    assert schema.canonical_name("period") == "time_period"


def test_canonical_name_falls_back_to_slugify():
    schema = BlockSchema(name="s", section_marker="Projects", table_columns=2)
    assert schema.canonical_name("Author") == "author"
    assert schema.canonical_name("Used Resources!") == "used_resources"


def test_display_label_renames_known_field_and_titlecases_others():
    schema = BlockSchema(
        name="s",
        section_marker="Projects",
        table_columns=2,
        known_fields=[KnownField(label="Period", name="time_period")],
    )
    assert schema.display_label("Period") == "Time period"
    assert schema.display_label("author") == "Author"
