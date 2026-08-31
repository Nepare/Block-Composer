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
    client = FakeLLMClient(
        replies=[
            "## Sawmill\n\nCuts logs.\n\n**Rooms:**\n- Saw room\n",  # the pinned generate
            "sawmill_overview",  # result naming
        ]
    )
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
    assert result_path.name == "sawmill_overview.md"
    # no NL request -> no planning call, just the one generate + one result-naming call
    assert client.call_count == 2


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
    # "Sheriff Station" reads as a different subject than "Police Station" -- per mutate's
    # own naming rule this becomes its own fresh entry, not a police_station_mut_x variant.
    mutate_reply = (
        "===BODY===\n## Sheriff Station\n\nFrontier law.\n\n**Rooms:**\n- Office\n"
        "===LABEL===\nSheriff Station"
    )
    client = FakeLLMClient(replies=[plan, mutate_reply, "law_enforcement_setup"])
    fake_router(compose_module, client)
    fake_router(mutate_module, client)

    slots, result_path = compose_module.run_compose("need law enforcement", settings=settings)

    assert slots[0].action == "mutate"
    assert slots[0].resolved_id == "sheriff_station"
    assert "Sheriff Station" in result_path.read_text(encoding="utf-8")
    assert result_path.name == "law_enforcement_setup.md"


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
    assert client.call_count == 1  # only the planning call -- dry-run skips result naming too


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
    fake_router(compose_module, FakeLLMClient(replies=["town_defense_and_school"]))

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


def test_empty_request_with_no_use_or_generate_is_rejected(settings, fake_router):
    _seed_library(settings)
    client = FakeLLMClient()
    fake_router(compose_module, client)

    with pytest.raises(BlockValidationError):
        compose_module.run_compose("", settings=settings)
    assert client.call_count == 0  # rejected before any LLM call, not a silent empty result


def test_explicit_out_path_is_used_verbatim(settings, fake_router, tmp_path):
    _seed_library(settings)
    out = tmp_path / "custom" / "myresult.md"

    # no fake_router needed: an explicit --out skips result-naming entirely (no LLM call)
    _slots, result_path = compose_module.run_compose(
        "", settings=settings, use_ids=["school"], out_path=out
    )

    assert result_path == out
    assert out.exists()


def test_result_naming_reuses_the_same_file_for_identical_reruns(settings, fake_router):
    _seed_library(settings)
    client = FakeLLMClient(replies=["school_overview", "school_overview"])
    fake_router(compose_module, client)

    _slots1, result_path1 = compose_module.run_compose("", settings=settings, use_ids=["school"])
    _slots2, result_path2 = compose_module.run_compose("", settings=settings, use_ids=["school"])

    assert result_path2 == result_path1
    assert result_path1.name == "school_overview.md"
    # one result-naming call per run; the second run's content is identical so
    # naming.decide() resolves it as an exact-match reuse with no further call
    assert client.call_count == 2


def test_result_naming_variant_on_a_conflicting_rerun(settings, fake_router):
    _seed_library(settings)
    # both runs' content-namer picks the same name; the second run's content differs, so
    # naming.decide() must ask for a distinguishing variant label as a third call
    client = FakeLLMClient(replies=["overview", "overview", "variant"])
    fake_router(compose_module, client)

    _slots1, result_path1 = compose_module.run_compose("", settings=settings, use_ids=["school"])
    _slots2, result_path2 = compose_module.run_compose(
        "", settings=settings, use_ids=["police_station"]
    )

    assert result_path1 != result_path2
    assert result_path1.name == "overview.md"
    assert result_path2.name == "overview_mut_variant.md"
    assert client.call_count == 3


def test_no_manifest_file_is_written(settings, fake_router, tmp_path):
    _seed_library(settings)
    fake_router(compose_module, FakeLLMClient(replies=["school_overview"]))

    _slots, result_path = compose_module.run_compose("", settings=settings, use_ids=["school"])

    assert not result_path.with_name(result_path.stem + "_manifest.json").exists()
    assert list(result_path.parent.glob("*.json")) == []


def test_planning_call_includes_constraints_file_in_the_system_prompt(settings, fake_router, tmp_path):
    _seed_library(settings)
    constraints_file = tmp_path / "COMPOSE_CONSTRAINTS.md"
    constraints_file.write_text("Prefer mutate over generate.", encoding="utf-8")
    settings.constraints.compose = str(constraints_file)

    plan = json.dumps({"steps": [{"order": 1, "action": "use", "block_id": "school", "criteria": None}]})
    client = FakeLLMClient(replies=[plan, "school_result"])
    fake_router(compose_module, client)

    compose_module.run_compose("need a school", settings=settings)

    planning_system_message = client.calls[0]["messages"][0]["content"]
    assert "Prefer mutate over generate." in planning_system_message
    # the result-naming call now shares the compose tier -- confirm it gets the same file too
    naming_system_message = client.calls[1]["messages"][0]["content"]
    assert "Prefer mutate over generate." in naming_system_message
