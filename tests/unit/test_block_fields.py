from models.block_fields import parse_block_body


def test_parses_canonical_shape():
    body = (
        "## Halthera Prime\n\n"
        "A temperate world.\n\n"
        "**Role:** Cartography Division\n\n"
        "**Time period:** Surveyed 03.2147 – 11.2147\n\n"
        "**Environment:** Atmospheric sensors, Orbital survey array, A long-range probe\n"
    )
    fields = parse_block_body(body)

    assert fields.name == "Halthera Prime"
    assert fields.description == "A temperate world."
    assert fields.role == "Cartography Division"
    assert fields.time_period == "Surveyed 03.2147 – 11.2147"
    assert fields.environment == ["Atmospheric sensors", "Orbital survey array", "A long-range probe"]


def test_bulleted_field_lands_in_other_fields_by_slugified_label():
    body = "## X\n\nDesc.\n\n**Responsibilities:**\n- Did a thing\n- Did another thing\n"
    fields = parse_block_body(body)

    assert fields.other_fields["responsibilities"] == ["Did a thing", "Did another thing"]


def test_multiple_nonstandard_fields_stay_distinct():
    body = (
        "## X\n\nDesc.\n\n"
        "**Characteristics:**\n- Atmosphere: breathable\n- Gravity: 0.96\n\n"
        "**Settlements:** City A, City B\n"
    )
    fields = parse_block_body(body)

    assert fields.other_fields["characteristics"] == ["Atmosphere: breathable", "Gravity: 0.96"]
    assert fields.other_fields["settlements"] == "City A, City B"


def test_project_roles_and_author_are_both_legal_aliases_for_role():
    role = parse_block_body("## X\n\n**Role:** Backend Developer\n")
    project_roles = parse_block_body("## X\n\n**Project roles:** Backend Developer\n")
    author = parse_block_body("## X\n\n**Author:** Backend Developer\n")

    assert role.role == "Backend Developer"
    assert project_roles.role == "Backend Developer"
    assert author.role == "Backend Developer"


def test_period_and_time_period_both_map_to_time_period():
    a = parse_block_body("## X\n\n**Period:** 2020\n")
    b = parse_block_body("## X\n\n**Time period:** 2020\n")

    assert a.time_period == "2020"
    assert b.time_period == "2020"


def test_nested_table_style_environment_field_still_splits_on_commas():
    body = "## X\n\n**Environment:** 5 wood, 2 iron, 10 gold.\n"
    fields = parse_block_body(body)

    assert fields.environment == ["5 wood", "2 iron", "10 gold."]


def test_missing_sections_degrade_gracefully_without_raising():
    fields = parse_block_body("## Just A Name\n")

    assert fields.name == "Just A Name"
    assert fields.description == ""
    assert fields.role is None
    assert fields.time_period is None
    assert fields.environment == []
    assert fields.other_fields == {}


def test_completely_empty_body_does_not_raise():
    fields = parse_block_body("")

    assert fields.name == ""
    assert fields.role is None
