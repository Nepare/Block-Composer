import json

import pytest

import compose as compose_module
import generate as generate_module
import mutate as mutate_module
from blocks import Block, BlockStore
from errors import BlockNotFoundError, BlockValidationError
from fakes import FakeLLMClient


def _seed_library(settings):
    store = BlockStore(settings.blocks_path)
    store.save(
        Block(id="", body="## School\n\nTeaches children.\n\n**Rooms:**\n- Classroom\n"),
        filename_stem="school",
    )
    store.save(
        Block(id="", body="## Police Station\n\nRegular station.\n\n**Rooms:**\n- Office\n"),
        filename_stem="police_station",
    )
    return store


def test_pinned_use_and_generate_bypass_the_planner_entirely(settings, fake_router):
    _seed_library(settings)
    client = FakeLLMClient(replies=["## Sawmill\n\nCuts logs.\n\n**Rooms:**\n- Saw room\n"])
    fake_router(compose_module, client)
    fake_router(generate_module, client)

    slots, result_path = compose_module.run_compose(
        "", settings=settings, use_ids=["school"], generate_criteria=["a sawmill"]
    )

    actions = {s.action: s.resolved_id for s in slots}
    assert actions["pinned_use"] == "school"
    assert actions["pinned_generate"] == "sawmill"
    content = result_path.read_text(encoding="utf-8")
    assert "## School" in content and "## Sawmill" in content
    assert client.call_count == 1  # no NL request -> no planning call, just the one generate


def test_planner_prefers_mutate_over_generate_for_a_partial_fit(settings, fake_router):
    _seed_library(settings)
    plan = json.dumps(
        {
            "steps": [
                {
                    "order": 1,
                    "action": "mutate",
                    "block_id": "police_station",
                    "criteria": "re-theme as sheriff",
                }
            ]
        }
    )
    mutate_reply = "===BODY===\n## Sheriff Station\n\nFrontier law.\n===LABEL===\nsheriff"
    client = FakeLLMClient(replies=[plan, mutate_reply])
    fake_router(compose_module, client)
    fake_router(mutate_module, client)

    slots, result_path = compose_module.run_compose("need law enforcement", settings=settings)

    assert slots[0].action == "mutate"
    assert slots[0].resolved_id == "police_station [sheriff]"
    assert "Sheriff Station" in result_path.read_text(encoding="utf-8")


def test_dry_run_makes_no_generate_or_mutate_calls(settings, fake_router):
    _seed_library(settings)
    plan = json.dumps(
        {"steps": [{"order": 1, "action": "generate", "block_id": None, "criteria": "a brand-new hospital"}]}
    )
    client = FakeLLMClient(replies=[plan])
    fake_router(compose_module, client)

    slots, result_path = compose_module.run_compose("need a hospital", settings=settings, dry_run=True)

    assert result_path is None
    assert slots[0].resolved_id is None  # generate was never actually run
    assert client.call_count == 1  # only the planning call


def test_max_generate_cap_is_enforced_before_any_gap_filling(settings, fake_router):
    _seed_library(settings)
    plan = json.dumps(
        {
            "steps": [
                {"order": i, "action": "generate", "block_id": None, "criteria": f"thing {i}"}
                for i in range(1, 4)
            ]
        }
    )
    fake_router(compose_module, FakeLLMClient(replies=[plan]))

    with pytest.raises(BlockValidationError):
        compose_module.run_compose("need three new things", settings=settings, max_generate=2)


def test_ordering_of_pinned_use_slots_is_respected_in_output(settings, fake_router):
    _seed_library(settings)

    slots, result_path = compose_module.run_compose(
        "", settings=settings, use_ids=["police_station", "school"]
    )

    content = result_path.read_text(encoding="utf-8")
    assert content.index("## Police Station") < content.index("## School")


def test_pinned_unknown_block_raises_before_any_llm_call(settings, fake_router):
    _seed_library(settings)
    client = FakeLLMClient()
    fake_router(compose_module, client)

    with pytest.raises(BlockNotFoundError):
        compose_module.run_compose("", settings=settings, use_ids=["does-not-exist"])
    assert client.call_count == 0


def test_explicit_out_path_is_used_verbatim(settings, fake_router, tmp_path):
    _seed_library(settings)
    out = tmp_path / "custom" / "myresult.md"

    _slots, result_path = compose_module.run_compose(
        "", settings=settings, use_ids=["school"], out_path=out
    )

    assert result_path == out
    assert out.exists()


def test_result_naming_reuses_the_same_file_for_identical_reruns(settings, fake_router):
    _seed_library(settings)

    _slots1, result_path1 = compose_module.run_compose("", settings=settings, use_ids=["school"])
    client = FakeLLMClient()  # must not be called: exact-match reuse needs no naming call
    fake_router(compose_module, client)
    _slots2, result_path2 = compose_module.run_compose("", settings=settings, use_ids=["school"])

    assert result_path2 == result_path1
    assert client.call_count == 0


def test_result_naming_bracket_variants_a_differing_rerun(settings, fake_router):
    _seed_library(settings)

    _slots1, result_path1 = compose_module.run_compose("", settings=settings, use_ids=["school"])
    naming_client = FakeLLMClient(replies=["variant"])
    fake_router(compose_module, naming_client)
    _slots2, result_path2 = compose_module.run_compose(
        "", settings=settings, use_ids=["police_station"]
    )

    assert result_path1 != result_path2
    assert result_path2.name == "result [variant].md"


def test_manifest_records_every_slot(settings, fake_router):
    _seed_library(settings)

    _slots, result_path = compose_module.run_compose("", settings=settings, use_ids=["school"])

    manifest_path = result_path.with_name(result_path.stem + "_manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["slots"] == [
        {
            "order": 1,
            "action": "pinned_use",
            "block_id": "school",
            "criteria": None,
            "resolved_id": "school",
        }
    ]
