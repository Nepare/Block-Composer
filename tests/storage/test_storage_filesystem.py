import pytest

from models.blocks import Block
from core.errors import BlockNotFoundError
from fakes import FakeLLMClient
from storage.base import Result
from storage.filesystem import FilesystemBlockStorage, FilesystemResultStorage


def test_save_syncs_id_to_filename_stem(tmp_path):
    store = FilesystemBlockStorage(tmp_path)
    b = Block(id="whatever", body="## Lumber\n\nA lumber yard.\n")
    stem = store.save(b, filename_stem="lumber")
    assert stem == "lumber"
    assert (tmp_path / "lumber.md").exists()
    assert b.id == "lumber"


def test_save_and_load_roundtrip(tmp_path):
    store = FilesystemBlockStorage(tmp_path)
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
    store = FilesystemBlockStorage(tmp_path)
    block = store.load("manual")
    assert block.id == "manual"
    assert block.tags == []
    assert block.created_by == "manual"
    assert block.source == "manual"
    assert "Just a body" in block.body


def test_load_missing_block_raises(tmp_path):
    store = FilesystemBlockStorage(tmp_path)
    with pytest.raises(BlockNotFoundError):
        store.load("nope")


def test_path_for_returns_the_expected_md_path(tmp_path):
    store = FilesystemBlockStorage(tmp_path)
    assert store.path_for("lumber") == tmp_path / "lumber.md"


def test_siblings_matches_base_and_variant_names_only(tmp_path):
    store = FilesystemBlockStorage(tmp_path)
    store.save(Block(id="", body="## Police Station\n\nA.\n"), filename_stem="police_station")
    store.save(Block(id="", body="## Police Station\n\nB.\n"), filename_stem="police_station_mut_jail")
    store.save(Block(id="", body="## Lumber\n\nC.\n"), filename_stem="lumber")

    siblings = store.siblings("police_station")
    assert {b.id for b in siblings} == {"police_station", "police_station_mut_jail"}


def test_search_by_tag_and_query(tmp_path):
    store = FilesystemBlockStorage(tmp_path)
    store.save(
        Block(id="", body="## Police Station\n\nKeeps order.\n", tags=["police_station"]),
        filename_stem="police_station",
    )
    store.save(Block(id="", body="## Lumber\n\nCuts wood.\n", tags=["lumber"]), filename_stem="lumber")

    assert [b.id for b in store.search(tags=["lumber"])] == ["lumber"]
    assert [b.id for b in store.search(query="order")] == ["police_station"]
    assert store.search(query="nonexistent-word") == []


def test_save_with_dedup_brand_new_then_variant_on_conflict(tmp_path):
    store = FilesystemBlockStorage(tmp_path)

    fake1 = FakeLLMClient()
    b1 = Block(id="", body="## Police Station\n\nA.\n", created_by="dissected")
    decision1, stem1 = store.save_with_dedup(b1, naming_client=fake1, naming_model="m")
    assert decision1.action == "save_plain"
    assert stem1 == "police_station"
    assert fake1.call_count == 0

    fake2 = FakeLLMClient(replies=["jail"])
    b2 = Block(id="", body="## Police Station\n\nHas a jail.\n", created_by="dissected")
    decision2, stem2 = store.save_with_dedup(b2, naming_client=fake2, naming_model="m")
    assert decision2.action == "save_variant"
    assert stem2 == "police_station_mut_jail"
    assert fake2.call_count == 1

    # the anchor file must be untouched by the variant write
    assert "A." in store.load("police_station").body
    assert "jail" not in store.load("police_station").body.lower()


def test_save_with_dedup_exact_repeat_is_skipped_and_writes_nothing(tmp_path):
    store = FilesystemBlockStorage(tmp_path)
    body = "## Police Station\n\nA.\n"

    store.save_with_dedup(
        Block(id="", body=body, created_by="dissected"), naming_client=FakeLLMClient(), naming_model="m"
    )
    decision, stem = store.save_with_dedup(
        Block(id="", body=body, created_by="dissected"), naming_client=FakeLLMClient(), naming_model="m"
    )

    assert decision.action == "skip_duplicate"
    assert stem is None
    assert len(list(tmp_path.glob("*.md"))) == 1


def test_save_with_dedup_forwards_naming_constraints_to_the_llm(tmp_path):
    store = FilesystemBlockStorage(tmp_path)
    store.save(Block(id="", body="## Police Station\n\nA.\n"), filename_stem="police_station")

    client = FakeLLMClient(replies=["jail"])
    store.save_with_dedup(
        Block(id="", body="## Police Station\n\nHas a jail.\n"),
        naming_client=client,
        naming_model="m",
        naming_constraints="Never use single letters.",
    )

    system_message = client.calls[0]["messages"][0]["content"]
    assert "Never use single letters." in system_message


def test_result_save_writes_plain_text_with_no_frontmatter(tmp_path):
    """The on-disk result format must stay exactly what it was before the storage
    Protocol existed -- raw content, no metadata header -- so this refactor changes zero
    on-disk bytes for filesystem-mode users."""
    store = FilesystemResultStorage(tmp_path)
    result = Result(content="## School\n\nTeaches children.\n", name="School Overview")

    stem = store.save(result, filename_stem="school_overview")

    assert stem == "school_overview"
    assert (tmp_path / "school_overview.md").read_text(encoding="utf-8") == "## School\n\nTeaches children.\n"


def test_result_save_with_dedup_reuses_an_identical_rerun(tmp_path):
    store = FilesystemResultStorage(tmp_path)
    content = "## School\n\nTeaches children.\n"

    decision1, stem1 = store.save_with_dedup(
        Result(content=content, name="School Overview"), naming_client=FakeLLMClient(), naming_model="m"
    )
    decision2, stem2 = store.save_with_dedup(
        Result(content=content, name="School Overview"), naming_client=FakeLLMClient(), naming_model="m"
    )

    assert decision1.action == "save_plain"
    assert stem1 == "school_overview"
    assert decision2.action == "skip_duplicate"
    assert stem2 is None
    assert decision2.duplicate_of == "school_overview"
    assert len(list(tmp_path.glob("*.md"))) == 1


def test_result_save_with_dedup_variant_on_conflicting_content(tmp_path):
    store = FilesystemResultStorage(tmp_path)

    store.save_with_dedup(
        Result(content="## School\n\nA.\n", name="School Overview"),
        naming_client=FakeLLMClient(),
        naming_model="m",
    )
    client = FakeLLMClient(replies=["variant"])
    decision, stem = store.save_with_dedup(
        Result(content="## School\n\nB.\n", name="School Overview"), naming_client=client, naming_model="m"
    )

    assert decision.action == "save_variant"
    assert stem == "school_overview_mut_variant"
    assert client.call_count == 1
