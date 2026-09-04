import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from models.blocks import Block
from core.errors import BlockNotFoundError
from fakes import FakeLLMClient
from storage.base import ClearResult, Result
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


def test_save_then_delete_block(db_path):
    store = SqliteBlockStorage(db_path)
    store.save(Block(id="", body="## Lumber\n\nA lumber yard.\n"), filename_stem="lumber")

    store.delete("lumber")

    assert store.exists("lumber") is False
    with pytest.raises(BlockNotFoundError):
        store.load("lumber")


def test_delete_missing_block_raises(db_path):
    store = SqliteBlockStorage(db_path)
    with pytest.raises(BlockNotFoundError):
        store.delete("nope")


def test_delete_removes_the_row_from_the_blocks_table(db_path):
    store = SqliteBlockStorage(db_path)
    store.save(Block(id="", body="## Lumber\n\nA lumber yard.\n"), filename_stem="lumber")

    store.delete("lumber")

    count = store._conn.execute("SELECT COUNT(*) FROM blocks WHERE id = ?", ("lumber",)).fetchone()[0]
    assert count == 0


def test_siblings_matches_base_and_variant_names_only(db_path):
    store = SqliteBlockStorage(db_path)
    store.save(Block(id="", body="## Police Station\n\nA.\n"), filename_stem="police_station")
    store.save(Block(id="", body="## Police Station\n\nB.\n"), filename_stem="police_station_mut_jail")
    store.save(Block(id="", body="## Lumber\n\nC.\n"), filename_stem="lumber")

    siblings = store.siblings("police_station")
    assert {b.id for b in siblings} == {"police_station", "police_station_mut_jail"}


def test_delete_base_block_does_not_cascade_to_variant_sibling(db_path):
    store = SqliteBlockStorage(db_path)
    store.save(Block(id="", body="## Police Station\n\nA.\n"), filename_stem="police_station")
    store.save(Block(id="", body="## Police Station\n\nB.\n"), filename_stem="police_station_mut_jail")

    store.delete("police_station")

    assert store.exists("police_station_mut_jail") is True
    assert store.load("police_station_mut_jail").body.strip().endswith("B.")


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


def test_save_with_dedup_explicit_base_saves_under_it_with_no_llm_call(db_path):
    store = SqliteBlockStorage(db_path)
    decision, stem = store.save_with_dedup(
        Block(id="", body="## Widget\n\nA.\n"), explicit_base="widget"
    )
    assert stem == "widget"
    assert decision.action == "save_plain"
    assert store.exists("widget")


def test_save_with_dedup_explicit_base_numbers_on_collision(db_path):
    store = SqliteBlockStorage(db_path)
    store.save_with_dedup(Block(id="", body="## Widget\n\nA.\n"), explicit_base="widget")
    decision, stem = store.save_with_dedup(
        Block(id="", body="## Widget\n\nA.\n"), explicit_base="widget"
    )
    # even though content is byte-identical to the first entry, explicit_base must NOT
    # dedup-skip — it always creates a new, separately numbered entry
    assert stem == "widget_2"
    assert decision.action == "save_variant"


def test_reopening_the_same_db_file_sees_prior_writes(db_path):
    """A fresh connection to the same file sees an earlier connection's writes."""
    store1 = SqliteBlockStorage(db_path)
    store1.save(Block(id="", body="## Lumber\n\nA lumber yard.\n"), filename_stem="lumber")

    store2 = SqliteBlockStorage(db_path)
    assert store2.load("lumber").name == "Lumber"


def test_result_save_persists_the_full_result_not_just_content(db_path):
    """The SQLite backend persists the full Result, not just its content."""
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


def test_result_save_with_dedup_explicit_base_numbers_on_collision(db_path):
    store = SqliteResultStorage(db_path)
    store.save_with_dedup(Result(content="## X\n\nA.\n", name="X"), explicit_base="x")
    decision, stem = store.save_with_dedup(Result(content="## X\n\nA.\n", name="X"), explicit_base="x")
    assert stem == "x_2"
    assert decision.action == "save_variant"


def test_result_path_for_is_always_none(db_path):
    store = SqliteResultStorage(db_path)
    assert store.path_for("school_overview") is None


def test_save_then_delete_result(db_path):
    store = SqliteResultStorage(db_path)
    store.save(
        Result(content="## School\n\nTeaches children.\n", name="School Overview"),
        filename_stem="school_overview",
    )

    store.delete("school_overview")

    assert store.exists("school_overview") is False
    with pytest.raises(BlockNotFoundError):
        store.load("school_overview")


def test_delete_missing_result_raises(db_path):
    store = SqliteResultStorage(db_path)
    with pytest.raises(BlockNotFoundError):
        store.delete("nope")


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


def test_set_preserved_marks_a_fresh_block_preserved(db_path):
    store = SqliteBlockStorage(db_path)
    store.save(Block(id="", body="## Lumber\n\nA lumber yard.\n"), filename_stem="lumber")

    store.set_preserved("lumber", True)

    assert store.load("lumber").preserved is True


def test_set_preserved_true_twice_is_idempotent(db_path):
    store = SqliteBlockStorage(db_path)
    store.save(Block(id="", body="## Lumber\n\nA lumber yard.\n"), filename_stem="lumber")

    store.set_preserved("lumber", True)
    store.set_preserved("lumber", True)

    assert store.load("lumber").preserved is True


def test_set_preserved_false_unpreserves_and_is_idempotent(db_path):
    store = SqliteBlockStorage(db_path)
    store.save(Block(id="", body="## Lumber\n\nA lumber yard.\n"), filename_stem="lumber")
    store.set_preserved("lumber", True)

    store.set_preserved("lumber", False)
    store.set_preserved("lumber", False)

    assert store.load("lumber").preserved is False


def test_set_preserved_on_unknown_block_raises(db_path):
    store = SqliteBlockStorage(db_path)
    with pytest.raises(BlockNotFoundError):
        store.set_preserved("nope", True)


def test_clear_deletes_unpreserved_blocks_and_keeps_preserved(db_path):
    store = SqliteBlockStorage(db_path)
    store.save(Block(id="", body="## Lumber\n\nA.\n"), filename_stem="lumber")
    store.save(Block(id="", body="## Police Station\n\nB.\n"), filename_stem="police_station")
    store.save(Block(id="", body="## School\n\nC.\n"), filename_stem="school")
    store.set_preserved("school", True)

    result = store.clear()

    assert result == ClearResult(deleted=2, skipped_preserved=1)
    assert {b.id for b in store.all()} == {"school"}


def test_clear_again_on_all_preserved_blocks_deletes_nothing(db_path):
    store = SqliteBlockStorage(db_path)
    store.save(Block(id="", body="## School\n\nC.\n"), filename_stem="school")
    store.set_preserved("school", True)

    result = store.clear()

    assert result == ClearResult(deleted=0, skipped_preserved=1)
    assert store.exists("school") is True


def test_clear_after_unpreserving_last_block_deletes_it(db_path):
    store = SqliteBlockStorage(db_path)
    store.save(Block(id="", body="## School\n\nC.\n"), filename_stem="school")
    store.set_preserved("school", True)
    store.set_preserved("school", False)

    result = store.clear()

    assert result == ClearResult(deleted=1, skipped_preserved=0)
    assert store.all() == []


def test_clear_on_empty_block_store_is_a_noop(db_path):
    store = SqliteBlockStorage(db_path)
    result = store.clear()
    assert result == ClearResult(deleted=0, skipped_preserved=0)


def test_clearing_block_store_does_not_touch_result_store(tmp_path):
    block_store = SqliteBlockStorage(tmp_path / "blocks.db")
    result_store = SqliteResultStorage(tmp_path / "results.db")
    block_store.save(Block(id="", body="## Lumber\n\nA.\n"), filename_stem="lumber")
    result_store.save(Result(content="## School\n\nB.\n", name="School"), filename_stem="school")

    block_store.clear()

    assert block_store.all() == []
    assert {r.id for r in result_store.all()} == {"school"}


def test_clearing_result_store_does_not_touch_block_store(tmp_path):
    block_store = SqliteBlockStorage(tmp_path / "blocks.db")
    result_store = SqliteResultStorage(tmp_path / "results.db")
    block_store.save(Block(id="", body="## Lumber\n\nA.\n"), filename_stem="lumber")
    result_store.save(Result(content="## School\n\nB.\n", name="School"), filename_stem="school")

    result_store.clear()

    assert result_store.all() == []
    assert {b.id for b in block_store.all()} == {"lumber"}


def test_set_preserved_marks_a_fresh_result_preserved(db_path):
    store = SqliteResultStorage(db_path)
    store.save(Result(content="## School\n\nA.\n", name="School"), filename_stem="school")

    store.set_preserved("school", True)

    assert store.load("school").preserved is True


def test_set_preserved_true_twice_on_result_is_idempotent(db_path):
    store = SqliteResultStorage(db_path)
    store.save(Result(content="## School\n\nA.\n", name="School"), filename_stem="school")

    store.set_preserved("school", True)
    store.set_preserved("school", True)

    assert store.load("school").preserved is True


def test_set_preserved_false_unpreserves_result_and_is_idempotent(db_path):
    store = SqliteResultStorage(db_path)
    store.save(Result(content="## School\n\nA.\n", name="School"), filename_stem="school")
    store.set_preserved("school", True)

    store.set_preserved("school", False)
    store.set_preserved("school", False)

    assert store.load("school").preserved is False


def test_set_preserved_on_unknown_result_raises(db_path):
    store = SqliteResultStorage(db_path)
    with pytest.raises(BlockNotFoundError):
        store.set_preserved("nope", True)


def test_clear_deletes_unpreserved_results_and_keeps_preserved(db_path):
    store = SqliteResultStorage(db_path)
    store.save(Result(content="## School\n\nA.\n", name="School"), filename_stem="school")
    store.save(Result(content="## Lumber\n\nB.\n", name="Lumber"), filename_stem="lumber")
    store.save(Result(content="## Police\n\nC.\n", name="Police"), filename_stem="police")
    store.set_preserved("police", True)

    result = store.clear()

    assert result == ClearResult(deleted=2, skipped_preserved=1)
    assert {r.id for r in store.all()} == {"police"}


def test_clear_again_on_all_preserved_results_deletes_nothing(db_path):
    store = SqliteResultStorage(db_path)
    store.save(Result(content="## Police\n\nC.\n", name="Police"), filename_stem="police")
    store.set_preserved("police", True)

    result = store.clear()

    assert result == ClearResult(deleted=0, skipped_preserved=1)
    assert store.exists("police") is True


def test_clear_after_unpreserving_last_result_deletes_it(db_path):
    store = SqliteResultStorage(db_path)
    store.save(Result(content="## Police\n\nC.\n", name="Police"), filename_stem="police")
    store.set_preserved("police", True)
    store.set_preserved("police", False)

    result = store.clear()

    assert result == ClearResult(deleted=1, skipped_preserved=0)
    assert store.all() == []


def test_clear_on_empty_result_store_is_a_noop(db_path):
    store = SqliteResultStorage(db_path)
    result = store.clear()
    assert result == ClearResult(deleted=0, skipped_preserved=0)


def test_sqlite_migration_adds_preserved_column_to_pre_existing_db(db_path):
    """A database created before this feature (no `preserved` column) must be upgraded
    in place on next open, keeping any pre-existing rows readable."""
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE blocks (
            id TEXT PRIMARY KEY,
            body TEXT NOT NULL,
            schema TEXT,
            tags TEXT NOT NULL DEFAULT '[]',
            source TEXT NOT NULL DEFAULT 'manual',
            created_by TEXT NOT NULL DEFAULT 'manual',
            created_at TEXT,
            generation_criteria TEXT,
            mutated_from TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO blocks (id, body, schema, tags, source, created_by, created_at, "
        "generation_criteria, mutated_from) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("lumber", "## Lumber\n\nA lumber yard.\n", None, "[]", "manual", "manual", None, None, None),
    )
    conn.commit()
    conn.close()

    store = SqliteBlockStorage(db_path)

    cols = [row["name"] for row in store._conn.execute("PRAGMA table_info(blocks)").fetchall()]
    assert "preserved" in cols
    loaded = store.load("lumber")
    assert loaded.preserved is False
    assert "A lumber yard." in loaded.body
