from blocks import Block


def test_block_name_from_first_heading():
    b = Block(id="x", body="## Police Station\n\nBody text.\n")
    assert b.name == "Police Station"


def test_block_name_falls_back_to_id_without_heading():
    b = Block(id="fallback", body="no heading here")
    assert b.name == "fallback"
