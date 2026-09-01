import pytest

import mutate as mutate_module
from blocks import Block
from errors import BlockNotFoundError, OperationCancelled
from fakes import FakeLLMClient
from progress import ProgressEvent
from storage.filesystem import FilesystemBlockStorage


def _seed(settings, stem="police_station", body="## Police Station\n\nRegular.\n\n**Rooms:**\n- Office\n", tags=None):
    store = FilesystemBlockStorage(settings.blocks_path)
    store.save(Block(id="", body=body, tags=tags or [], created_by="dissected"), filename_stem=stem)
    return store


def test_run_mutate_single_call_produces_body_and_bracket_label(settings, fake_router):
    _seed(settings)
    reply = (
        "===BODY===\n## Police Station\n\nSheriff-run now.\n\n**Rooms:**\n- Office\n- Cells\n"
        "===LABEL===\nsheriff"
    )
    client = FakeLLMClient(replies=[reply])
    fake_router(mutate_module, client)

    block, stem = mutate_module.run_mutate("police_station", "make it sheriff-themed", settings=settings)

    assert stem == "police_station_mut_sheriff"
    assert block.mutated_from == "police_station"
    assert block.created_by == "mutated"
    assert client.call_count == 1


def test_run_mutate_inherits_tags_from_the_original(settings, fake_router):
    _seed(settings, tags=["police_station", "law"])
    reply = "===BODY===\n## Police Station\n\nSheriff-run now.\n\n**Rooms:**\n- Office\n===LABEL===\nsheriff"
    fake_router(mutate_module, FakeLLMClient(replies=[reply]))

    block, _stem = mutate_module.run_mutate("police_station", "re-theme", settings=settings)

    assert block.tags == ["police_station", "law"]


def test_run_mutate_that_changes_the_subject_gets_its_own_fresh_name(settings, fake_router):
    """If the mutation is drastic enough that the result isn't recognizably the same
    thing any more (a lumber camp re-themed into a stone quarry), it must NOT be forced
    under the original's bracket -- it's a new entry with its own name."""
    _seed(settings, stem="lumber", body="## Lumber\n\nA lumber camp.\n\n**Rooms:**\n- Saw room\n")
    reply = (
        "===BODY===\n## Stone Quarry\n\nA working stone quarry.\n\n**Rooms:**\n- Pit\n"
        "===LABEL===\nStone Quarry"
    )
    client = FakeLLMClient(replies=[reply])
    fake_router(mutate_module, client)

    block, stem = mutate_module.run_mutate(
        "lumber", "re-theme as a stone quarry instead of a lumber camp", settings=settings
    )

    assert stem == "stone_quarry"
    assert block.name == "Stone Quarry"
    assert client.call_count == 1  # brand-new name, no collision -> no second naming call


def test_run_mutate_renamed_result_that_collides_gets_bracket_named_under_its_new_name(
    settings, fake_router
):
    _seed(settings, stem="lumber", body="## Lumber\n\nA lumber camp.\n\n**Rooms:**\n- Saw room\n")
    _seed(
        settings,
        stem="stone_quarry",
        body="## Stone Quarry\n\nAn older, different quarry.\n\n**Rooms:**\n- Pit\n",
    )

    reply = (
        "===BODY===\n## Stone Quarry\n\nA freshly re-themed quarry.\n\n**Rooms:**\n- Pit\n"
        "===LABEL===\nStone Quarry"
    )
    client = FakeLLMClient(replies=[reply, "reopened"])  # second call: naming conflict label
    fake_router(mutate_module, client)

    _block, stem = mutate_module.run_mutate(
        "lumber", "re-theme as a stone quarry", settings=settings
    )

    assert stem == "stone_quarry_mut_reopened"
    assert client.call_count == 2


def test_run_mutate_leaves_original_untouched(settings, fake_router):
    store = _seed(settings)
    before = store.load("police_station").body
    reply = "===BODY===\n## Police Station\n\nSheriff.\n\n**Rooms:**\n- Office\n===LABEL===\nsheriff"
    fake_router(mutate_module, FakeLLMClient(replies=[reply]))

    mutate_module.run_mutate("police_station", "re-theme", settings=settings)

    after = store.load("police_station").body
    assert before == after


def test_run_mutate_in_place_overwrites_the_same_file(settings, fake_router):
    store = _seed(settings)
    reply = "===BODY===\n## Police Station\n\nUpdated in place.\n\n**Rooms:**\n- Office\n===LABEL===\nignored"
    fake_router(mutate_module, FakeLLMClient(replies=[reply]))

    _block, stem = mutate_module.run_mutate("police_station", "update", settings=settings, in_place=True)

    assert stem == "police_station"
    assert "Updated in place." in store.load("police_station").body


def test_run_mutate_retries_once_on_malformed_reply(settings, fake_router):
    _seed(settings)
    client = FakeLLMClient(
        replies=[
            "not in the required format at all",
            "===BODY===\n## Police Station\n\nFixed.\n\n**Rooms:**\n- Office\n===LABEL===\nsheriff",
        ]
    )
    fake_router(mutate_module, client)

    _block, stem = mutate_module.run_mutate("police_station", "fix", settings=settings)

    assert stem == "police_station_mut_sheriff"
    assert client.call_count == 2


def test_run_mutate_unknown_block_raises(settings, fake_router):
    fake_router(mutate_module, FakeLLMClient())

    with pytest.raises(BlockNotFoundError):
        mutate_module.run_mutate("does_not_exist", "x", settings=settings)


def test_run_mutate_second_variant_gets_a_distinct_filename(settings, fake_router):
    _seed(settings)
    first_reply = "===BODY===\n## Police Station\n\nSheriff v1.\n\n**Rooms:**\n- Office\n===LABEL===\nsheriff"
    fake_router(mutate_module, FakeLLMClient(replies=[first_reply]))
    mutate_module.run_mutate("police_station", "sheriff", settings=settings)

    second_reply = "===BODY===\n## Police Station\n\nSheriff v2.\n\n**Rooms:**\n- Office\n===LABEL===\nsheriff"
    fake_router(mutate_module, FakeLLMClient(replies=[second_reply]))
    _block, stem2 = mutate_module.run_mutate("police_station", "sheriff again", settings=settings)

    assert stem2 == "police_station_mut_sheriff_2"


def test_run_mutate_fires_progress_events_around_the_call(settings, fake_router):
    _seed(settings)
    reply = (
        "===BODY===\n## Police Station\n\nSheriff-run now.\n\n**Rooms:**\n- Office\n- Cells\n"
        "===LABEL===\nsheriff"
    )
    client = FakeLLMClient(replies=[reply])
    fake_router(mutate_module, client)

    events: list[ProgressEvent] = []
    mutate_module.run_mutate("police_station", "make it sheriff-themed", settings=settings, on_progress=events.append)

    kinds = [e.kind for e in events]
    assert kinds[0] == "mutate_start"
    assert kinds[-1] == "mutate_done"


def test_run_mutate_is_silent_by_default_with_no_on_progress(settings, fake_router):
    _seed(settings)
    reply = "===BODY===\n## Police Station\n\nSheriff-run now.\n\n**Rooms:**\n- Office\n===LABEL===\nsheriff"
    fake_router(mutate_module, FakeLLMClient(replies=[reply]))

    # must not raise just because no on_progress was given
    mutate_module.run_mutate("police_station", "re-theme", settings=settings)


def test_run_mutate_raises_operation_cancelled_before_the_retry(settings, fake_router):
    _seed(settings)
    client = FakeLLMClient(
        replies=[
            "not in the required format at all",
            "===BODY===\n## Police Station\n\nFixed.\n\n**Rooms:**\n- Office\n===LABEL===\nsheriff",
        ]
    )
    fake_router(mutate_module, client)

    with pytest.raises(OperationCancelled):
        mutate_module.run_mutate("police_station", "fix", settings=settings, cancel_check=lambda: True)
    assert client.call_count == 1


def test_run_mutate_includes_constraints_file_in_the_system_prompt(settings, fake_router, tmp_path):
    _seed(settings)
    constraints_file = tmp_path / "MUTATE_CONSTRAINTS.md"
    constraints_file.write_text("Keep the tone formal.", encoding="utf-8")
    settings.constraints.mutate = str(constraints_file)

    reply = "===BODY===\n## Police Station\n\nAdapted.\n\n**Rooms:**\n- Office\n===LABEL===\nsheriff"
    client = FakeLLMClient(replies=[reply])
    fake_router(mutate_module, client)

    mutate_module.run_mutate("police_station", "adapt it", settings=settings)

    system_message = client.calls[0]["messages"][0]["content"]
    assert "Keep the tone formal." in system_message
