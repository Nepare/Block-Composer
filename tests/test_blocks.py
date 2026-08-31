import pytest

from blocks import Block, BlockStore
from errors import BlockNotFoundError
from fakes import FakeLLMClient


def test_block_name_from_first_heading():
    b = Block(id="x", body="## Police Station\n\nBody text.\n")
    assert b.name == "Police Station"


def test_block_name_falls_back_to_id_without_heading():
    b = Block(id="fallback", body="no heading here")
    assert b.name == "fallback"


def test_save_syncs_id_to_filename_stem(tmp_path):
    store = BlockStore(tmp_path)
    b = Block(id="whatever", body="## Lumber\n\nA lumber yard.\n")
    path = store.save(b, filename_stem="lumber")
    assert path.name == "lumber.md"
    assert b.id == "lumber"


def test_save_and_load_roundtrip(tmp_path):
    store = BlockStore(tmp_path)
    b = Block(
        id="",
        body="## Lumber\n\nA lumber yard.\n",
        schema="project_entry",
        tags=["lumber"],
        created_by="dissected",
        source="doc123",
    )
    store.save(b, filename_stem="lumber")

    loaded = store.load("lumber")
    assert loaded.name == "Lumber"
    assert loaded.schema == "project_entry"
    assert loaded.tags == ["lumber"]
    assert loaded.created_by == "dissected"
    assert loaded.source == "doc123"
    assert "A lumber yard." in loaded.body


def test_hand_authored_block_gets_sane_defaults(tmp_path):
    (tmp_path / "manual.md").write_text(
        "---\nschema: project_entry\n---\n\n## Hand Written\n\nJust a body, minimal frontmatter.\n",
        encoding="utf-8",
    )
    store = BlockStore(tmp_path)
    block = store.load("manual")
    assert block.id == "manual"
    assert block.tags == []
    assert block.created_by == "manual"
    assert block.source == "manual"
    assert "Just a body" in block.body


def test_load_missing_block_raises(tmp_path):
    store = BlockStore(tmp_path)
    with pytest.raises(BlockNotFoundError):
        store.load("nope")


def test_siblings_matches_base_and_bracketed_variants_only(tmp_path):
    store = BlockStore(tmp_path)
    store.save(Block(id="", body="## Police Station\n\nA.\n"), filename_stem="police_station")
    store.save(Block(id="", body="## Police Station\n\nB.\n"), filename_stem="police_station [jail]")
    store.save(Block(id="", body="## Lumber\n\nC.\n"), filename_stem="lumber")

    siblings = store.siblings("police_station")
    assert {b.id for b in siblings} == {"police_station", "police_station [jail]"}


def test_search_by_tag_and_query(tmp_path):
    store = BlockStore(tmp_path)
    store.save(
        Block(id="", body="## Police Station\n\nKeeps order.\n", tags=["police_station"]),
        filename_stem="police_station",
    )
    store.save(Block(id="", body="## Lumber\n\nCuts wood.\n", tags=["lumber"]), filename_stem="lumber")

    assert [b.id for b in store.search(tags=["lumber"])] == ["lumber"]
    assert [b.id for b in store.search(query="order")] == ["police_station"]
    assert store.search(query="nonexistent-word") == []


def test_save_with_dedup_brand_new_then_variant_on_conflict(tmp_path):
    store = BlockStore(tmp_path)

    fake1 = FakeLLMClient()
    b1 = Block(id="", body="## Police Station\n\nA.\n", created_by="dissected")
    decision1, path1 = store.save_with_dedup(b1, naming_client=fake1, naming_model="m")
    assert decision1.action == "save_plain"
    assert path1.name == "police_station.md"
    assert fake1.call_count == 0

    fake2 = FakeLLMClient(replies=["jail"])
    b2 = Block(id="", body="## Police Station\n\nHas a jail.\n", created_by="dissected")
    decision2, path2 = store.save_with_dedup(b2, naming_client=fake2, naming_model="m")
    assert decision2.action == "save_variant"
    assert path2.name == "police_station [jail].md"
    assert fake2.call_count == 1

    # the anchor file must be untouched by the variant write
    assert "A." in store.load("police_station").body
    assert "jail" not in store.load("police_station").body.lower()


def test_save_with_dedup_exact_repeat_is_skipped_and_writes_nothing(tmp_path):
    store = BlockStore(tmp_path)
    body = "## Police Station\n\nA.\n"

    store.save_with_dedup(
        Block(id="", body=body, created_by="dissected"), naming_client=FakeLLMClient(), naming_model="m"
    )
    decision, path = store.save_with_dedup(
        Block(id="", body=body, created_by="dissected"), naming_client=FakeLLMClient(), naming_model="m"
    )

    assert decision.action == "skip_duplicate"
    assert path is None
    assert len(list(tmp_path.glob("*.md"))) == 1
