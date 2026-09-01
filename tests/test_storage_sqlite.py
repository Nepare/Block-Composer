from datetime import datetime, timedelta, timezone

import pytest

from blocks import Block
from errors import BlockNotFoundError
from fakes import FakeLLMClient
from storage.base import Result
from storage.sqlite import SqliteBlockStorage, SqlitePendingSignInStore, SqliteResultStorage


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "cvdocs.db"


def test_save_syncs_id_to_filename_stem(db_path):
    store = SqliteBlockStorage(db_path)
    b = Block(id="whatever", body="## Lumber\n\nA lumber yard.\n")
    stem = store.save(b, filename_stem="lumber")
    assert stem == "lumber"
    assert b.id == "lumber"
    assert store.exists("lumber")


def test_save_and_load_roundtrip(db_path):
    store = SqliteBlockStorage(db_path)
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


def test_load_missing_block_raises(db_path):
    store = SqliteBlockStorage(db_path)
    with pytest.raises(BlockNotFoundError):
        store.load("nope")


def test_path_for_is_always_none(db_path):
    store = SqliteBlockStorage(db_path)
    assert store.path_for("lumber") is None


def test_siblings_matches_base_and_variant_names_only(db_path):
    store = SqliteBlockStorage(db_path)
    store.save(Block(id="", body="## Police Station\n\nA.\n"), filename_stem="police_station")
    store.save(Block(id="", body="## Police Station\n\nB.\n"), filename_stem="police_station_mut_jail")
    store.save(Block(id="", body="## Lumber\n\nC.\n"), filename_stem="lumber")

    siblings = store.siblings("police_station")
    assert {b.id for b in siblings} == {"police_station", "police_station_mut_jail"}


def test_search_by_tag_and_query(db_path):
    store = SqliteBlockStorage(db_path)
    store.save(
        Block(id="", body="## Police Station\n\nKeeps order.\n", tags=["police_station"]),
        filename_stem="police_station",
    )
    store.save(Block(id="", body="## Lumber\n\nCuts wood.\n", tags=["lumber"]), filename_stem="lumber")

    assert [b.id for b in store.search(tags=["lumber"])] == ["lumber"]
    assert [b.id for b in store.search(query="order")] == ["police_station"]
    assert store.search(query="nonexistent-word") == []


def test_save_with_dedup_brand_new_then_variant_on_conflict(db_path):
    store = SqliteBlockStorage(db_path)

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

    # the anchor row must be untouched by the variant write
    assert "A." in store.load("police_station").body
    assert "jail" not in store.load("police_station").body.lower()


def test_save_with_dedup_exact_repeat_is_skipped_and_writes_nothing(db_path):
    store = SqliteBlockStorage(db_path)
    body = "## Police Station\n\nA.\n"

    store.save_with_dedup(
        Block(id="", body=body, created_by="dissected"), naming_client=FakeLLMClient(), naming_model="m"
    )
    decision, stem = store.save_with_dedup(
        Block(id="", body=body, created_by="dissected"), naming_client=FakeLLMClient(), naming_model="m"
    )

    assert decision.action == "skip_duplicate"
    assert stem is None
    assert len(store.all()) == 1


def test_save_with_dedup_forwards_naming_constraints_to_the_llm(db_path):
    store = SqliteBlockStorage(db_path)
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


def test_reopening_the_same_db_file_sees_prior_writes(db_path):
    """Confirms the schema/connection actually persists to the file, not just in-memory
    for the lifetime of one instance -- a real reconnect (a fresh process, or a fresh
    get_block_storage(settings) call) must see what an earlier one wrote."""
    store1 = SqliteBlockStorage(db_path)
    store1.save(Block(id="", body="## Lumber\n\nA lumber yard.\n"), filename_stem="lumber")

    store2 = SqliteBlockStorage(db_path)
    assert store2.load("lumber").name == "Lumber"


def test_result_save_persists_the_full_result_not_just_content(db_path):
    """Unlike FilesystemResultStorage, the SQLite backend actually persists the richer
    Result metadata -- this is the whole point of a real DB backend."""
    store = SqliteResultStorage(db_path)
    result = Result(
        content="## School\n\nTeaches children.\n",
        name="School Overview",
        request="need a school",
        use_ids=["school"],
        generate_criteria=[],
        slots=[{"order": 1, "action": "use", "block_id": "school", "criteria": None, "resolved_id": "school"}],
    )

    stem = store.save(result, filename_stem="school_overview")

    loaded = store.load(stem)
    assert loaded.content == "## School\n\nTeaches children.\n"
    assert loaded.request == "need a school"
    assert loaded.use_ids == ["school"]
    assert loaded.slots == [
        {"order": 1, "action": "use", "block_id": "school", "criteria": None, "resolved_id": "school"}
    ]


def test_result_save_with_dedup_reuses_an_identical_rerun(db_path):
    store = SqliteResultStorage(db_path)
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
    assert len(store.all()) == 1


def test_result_save_with_dedup_variant_on_conflicting_content(db_path):
    store = SqliteResultStorage(db_path)

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


def test_result_path_for_is_always_none(db_path):
    store = SqliteResultStorage(db_path)
    assert store.path_for("school_overview") is None


def test_pending_sign_in_start_then_verify_and_consume(db_path):
    store = SqlitePendingSignInStore(db_path)
    state, code_verifier = store.start()
    assert store.verify_and_consume(state) == code_verifier


def test_pending_sign_in_verify_and_consume_rejects_wrong_state(db_path):
    store = SqlitePendingSignInStore(db_path)
    store.start()
    assert store.verify_and_consume("wrong-state") is None


def test_pending_sign_in_verify_and_consume_rejects_stale_attempt(db_path):
    store = SqlitePendingSignInStore(db_path)
    state, _ = store.start()
    stale = (datetime.now(timezone.utc) - timedelta(minutes=11)).isoformat()
    store._conn.execute("UPDATE sign_in_attempts SET created_at = ?", (stale,))

    assert store.verify_and_consume(state) is None


def test_pending_sign_in_start_supersedes_prior_pending_attempt(db_path):
    store = SqlitePendingSignInStore(db_path)
    state1, _ = store.start()
    state2, code_verifier2 = store.start()

    assert store.verify_and_consume(state1) is None
    assert store.verify_and_consume(state2) == code_verifier2


def test_pending_sign_in_verify_and_consume_is_single_use(db_path):
    store = SqlitePendingSignInStore(db_path)
    state, code_verifier = store.start()

    assert store.verify_and_consume(state) == code_verifier
    assert store.verify_and_consume(state) is None
