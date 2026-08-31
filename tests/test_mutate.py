import pytest

import mutate as mutate_module
from blocks import Block, BlockStore
from errors import BlockNotFoundError
from fakes import FakeLLMClient


def _seed(settings, stem="police_station", body="## Police Station\n\nRegular.\n\n**Rooms:**\n- Office\n"):
    store = BlockStore(settings.blocks_path)
    store.save(Block(id="", body=body, created_by="dissected"), filename_stem=stem)
    return store


def test_run_mutate_single_call_produces_body_and_bracket_label(settings, fake_router):
    _seed(settings)
    reply = (
        "===BODY===\n## Police Station\n\nSheriff-run now.\n\n**Rooms:**\n- Office\n- Cells\n"
        "===LABEL===\nsheriff"
    )
    client = FakeLLMClient(replies=[reply])
    fake_router(mutate_module, client)

    block, path = mutate_module.run_mutate("police_station", "make it sheriff-themed", settings=settings)

    assert path.name == "police_station [sheriff].md"
    assert block.mutated_from == "police_station"
    assert block.created_by == "mutated"
    assert client.call_count == 1


def test_run_mutate_leaves_original_untouched(settings, fake_router):
    store = _seed(settings)
    before = store.load("police_station").body
    reply = "===BODY===\n## Police Station\n\nSheriff.\n===LABEL===\nsheriff"
    fake_router(mutate_module, FakeLLMClient(replies=[reply]))

    mutate_module.run_mutate("police_station", "re-theme", settings=settings)

    after = store.load("police_station").body
    assert before == after


def test_run_mutate_in_place_overwrites_the_same_file(settings, fake_router):
    store = _seed(settings)
    reply = "===BODY===\n## Police Station\n\nUpdated in place.\n===LABEL===\nignored"
    fake_router(mutate_module, FakeLLMClient(replies=[reply]))

    _block, path = mutate_module.run_mutate("police_station", "update", settings=settings, in_place=True)

    assert path.name == "police_station.md"
    assert "Updated in place." in store.load("police_station").body


def test_run_mutate_retries_once_on_malformed_reply(settings, fake_router):
    _seed(settings)
    client = FakeLLMClient(
        replies=[
            "not in the required format at all",
            "===BODY===\n## Police Station\n\nFixed.\n===LABEL===\nsheriff",
        ]
    )
    fake_router(mutate_module, client)

    _block, path = mutate_module.run_mutate("police_station", "fix", settings=settings)

    assert path.name == "police_station [sheriff].md"
    assert client.call_count == 2


def test_run_mutate_unknown_block_raises(settings, fake_router):
    fake_router(mutate_module, FakeLLMClient())

    with pytest.raises(BlockNotFoundError):
        mutate_module.run_mutate("does_not_exist", "x", settings=settings)


def test_run_mutate_second_variant_gets_a_distinct_filename(settings, fake_router):
    _seed(settings)
    first_reply = "===BODY===\n## Police Station\n\nSheriff v1.\n===LABEL===\nsheriff"
    fake_router(mutate_module, FakeLLMClient(replies=[first_reply]))
    mutate_module.run_mutate("police_station", "sheriff", settings=settings)

    second_reply = "===BODY===\n## Police Station\n\nSheriff v2.\n===LABEL===\nsheriff"
    fake_router(mutate_module, FakeLLMClient(replies=[second_reply]))
    _block, path2 = mutate_module.run_mutate("police_station", "sheriff again", settings=settings)

    assert path2.name == "police_station [sheriff] 2.md"
