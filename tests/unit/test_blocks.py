from models.blocks import Block


def test_block_name_from_first_heading():
    b = Block(id="x", body="## Police Station\n\nBody text.\n")
    assert b.name == "Police Station"


def test_block_name_falls_back_to_id_without_heading():
    b = Block(id="fallback", body="no heading here")
    assert b.name == "fallback"


def test_tag_signature_sorts_tags_regardless_of_input_order():
    b = Block(id="x", body="", tags=["b", "a"])
    assert b.tag_signature == ("a", "b")


def test_tag_signature_equal_for_same_tags_in_different_order():
    b1 = Block(id="x", body="", tags=["b", "a"])
    b2 = Block(id="y", body="", tags=["a", "b"])
    assert b1.tag_signature == b2.tag_signature


def test_tag_signature_falls_back_to_id_without_tags():
    b = Block(id="untagged", body="", tags=[])
    assert b.tag_signature == (f"__id__:{b.id}",)
