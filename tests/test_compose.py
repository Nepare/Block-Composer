import json

import pytest

import compose as compose_module
import generate as generate_module
import mutate as mutate_module
from blocks import Block
from errors import BlockNotFoundError, BlockValidationError
from fakes import FakeLLMClient
from progress import ProgressEvent
from storage.filesystem import FilesystemBlockStorage


def _seed_library(settings):
    store = FilesystemBlockStorage(settings.blocks_path)
    store.save(
        Block(id="", body="## School\n\nTeaches children.\n\n**Rooms:**\n- Classroom\n"),
        filename_stem="school",
    )
    store.save(
        Block(id="", body="## Police Station\n\nRegular station.\n\n**Rooms:**\n- Office\n"),
        filename_stem="police_station",
    )
    return store


def _seed_large_library(settings, count=5):
    """At/above settings.compose.keyword_search_min_blocks (5 by default) so the
    keyword-search narrowing path actually engages."""
    store = FilesystemBlockStorage(settings.blocks_path)
    for i in range(count):
        store.save(
            Block(id="", body=f"## Block {i}\n\nGeneric entry {i}.\n\n**Environment:** Jira\n"),
            filename_stem=f"block_{i}",
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
    client = FakeLLMClient(replies=["NONE", plan, mutate_reply, "law_enforcement_setup"])
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
    client = FakeLLMClient(replies=["NONE", plan])
    fake_router(compose_module, client)

    slots, result_path = compose_module.run_compose("need a hospital", settings=settings, dry_run=True)

    assert result_path is None
    assert slots[0].resolved_id is None  # generate was never actually run
    assert client.call_count == 2  # target-count detection + planning call -- dry-run skips result naming too


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
    fake_router(compose_module, FakeLLMClient(replies=["NONE", plan]))

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
    client = FakeLLMClient(replies=["NONE", plan, "school_result"])
    fake_router(compose_module, client)

    compose_module.run_compose("need a school", settings=settings)

    # the target-count-detection call loads the same compose_constraints and reuses them
    detection_system_message = client.calls[0]["messages"][0]["content"]
    assert "Prefer mutate over generate." in detection_system_message
    planning_system_message = client.calls[1]["messages"][0]["content"]
    assert "Prefer mutate over generate." in planning_system_message
    # the result-naming call now shares the compose tier -- confirm it gets the same file too
    naming_system_message = client.calls[2]["messages"][0]["content"]
    assert "Prefer mutate over generate." in naming_system_message


def test_on_progress_fires_after_plan_and_around_each_mutate_and_generate(settings, fake_router):
    _seed_library(settings)
    plan = json.dumps(
        {
            "steps": [
                {"order": 1, "action": "mutate", "block_id": "police_station", "criteria": "adapt"},
                {"order": 2, "action": "generate", "block_id": None, "criteria": "a sawmill"},
            ]
        }
    )
    mutate_reply = "===BODY===\n## Sheriff Station\n\nAdapted.\n\n**Rooms:**\n- Office\n===LABEL===\nsheriff"
    generate_reply = "## Sawmill\n\nCuts logs.\n\n**Rooms:**\n- Saw room\n"
    client = FakeLLMClient(replies=["NONE", plan, mutate_reply, generate_reply, "town_result"])
    fake_router(compose_module, client)
    fake_router(mutate_module, client)
    fake_router(generate_module, client)

    events: list[ProgressEvent] = []
    compose_module.run_compose(
        "need law enforcement and lumber", settings=settings, on_progress=events.append
    )

    messages = [e.message for e in events]
    joined = "\n".join(messages)
    assert "Plan built: 2 step(s)" in joined
    assert any("mutating police_station" in m for m in messages)
    assert any(m.startswith("[1/2] mutated ->") for m in messages)
    assert any("generating new block" in m for m in messages)
    assert any(m.startswith("[2/2] generated ->") for m in messages)
    assert "Naming result…" in messages
    # compose's own bracketed slot narrative and the callees' internal narrative
    # (mutate_start/generate_start fired from inside run_mutate/run_generate) coexist
    assert any(e.kind == "mutate_start" and e.block_id == "police_station" for e in events)
    assert any(e.kind == "generate_start" for e in events)
    # every LLM call along the way emits its own diagnostic pair, invisible to RichConsoleSink
    # but present in the raw event stream for a log sink to persist
    assert sum(1 for e in events if e.kind == "llm_call_start") == client.call_count
    assert sum(1 for e in events if e.kind == "llm_call_done") == client.call_count


def test_on_progress_is_optional_and_defaults_to_silent(settings, fake_router):
    _seed_library(settings)
    fake_router(compose_module, FakeLLMClient(replies=["school_overview"]))

    # must not raise just because no on_progress was given
    compose_module.run_compose("", settings=settings, use_ids=["school"])


def test_cancel_check_stops_before_any_slot_executes(settings, fake_router):
    _seed_library(settings)
    plan = json.dumps(
        {"steps": [{"order": 1, "action": "generate", "block_id": None, "criteria": "a hospital"}]}
    )
    client = FakeLLMClient(replies=["NONE", plan])
    fake_router(compose_module, client)

    events: list[ProgressEvent] = []
    slots, result_path = compose_module.run_compose(
        "need a hospital", settings=settings, on_progress=events.append, cancel_check=lambda: True
    )

    assert result_path is None
    assert slots[0].resolved_id is None
    assert client.call_count == 2  # target-count detection + the planning call -- the generate slot never runs
    assert any(e.kind == "cancelled" for e in events)


def test_cancel_check_mid_plan_keeps_earlier_slots_resolved(settings, fake_router):
    _seed_library(settings)
    plan = json.dumps(
        {
            "steps": [
                {"order": 1, "action": "mutate", "block_id": "police_station", "criteria": "adapt"},
                {"order": 2, "action": "generate", "block_id": None, "criteria": "a sawmill"},
            ]
        }
    )
    mutate_reply = "===BODY===\n## Sheriff Station\n\nAdapted.\n\n**Rooms:**\n- Office\n===LABEL===\nsheriff"
    client = FakeLLMClient(replies=["NONE", plan, mutate_reply])
    fake_router(compose_module, client)
    fake_router(mutate_module, client)

    calls = {"n": 0}

    def cancel_after_first_slot():
        calls["n"] += 1
        return calls["n"] > 1  # False before slot 1, True before slot 2

    slots, result_path = compose_module.run_compose(
        "need law enforcement and lumber", settings=settings, cancel_check=cancel_after_first_slot
    )

    assert result_path is None  # cancelled before the combined result could be saved
    assert slots[0].resolved_id == "sheriff_station"  # slot 1 completed and stays saved
    assert slots[1].resolved_id is None  # slot 2 never ran


def test_below_threshold_library_still_attempts_target_count_detection_but_skips_keyword_extraction(
    settings, fake_router
):
    _seed_library(settings)  # 2 blocks, below the default keyword_search_min_blocks (5)
    plan = json.dumps({"steps": [{"order": 1, "action": "use", "block_id": "school", "criteria": None}]})
    client = FakeLLMClient(replies=["NONE", plan, "school_result"])
    fake_router(compose_module, client)

    events: list[ProgressEvent] = []
    compose_module.run_compose("need a school", settings=settings, on_progress=events.append)

    joined = "\n".join(e.message for e in events)
    assert "Extracting search keywords" not in joined
    assert "Planning against 2 block(s)" in joined
    # target-count detection + the planning call + the result-naming call -- detection is
    # independent of the narrowing gate, so it still fires even though keyword extraction doesn't
    assert client.call_count == 3


def test_at_threshold_library_extracts_keywords_and_narrows_the_catalog(settings, fake_router):
    _seed_large_library(settings, count=5)
    keywords_reply = "ROLE: \nENVIRONMENT: Jira\nRESPONSIBILITIES: \nDOMAIN: \n"
    plan = json.dumps({"steps": [{"order": 1, "action": "use", "block_id": "block_0", "criteria": None}]})
    client = FakeLLMClient(replies=["NONE", keywords_reply, plan, "result"])
    fake_router(compose_module, client)

    events: list[ProgressEvent] = []
    compose_module.run_compose("need something in Jira", settings=settings, on_progress=events.append)

    joined = "\n".join(e.message for e in events)
    assert "Extracting search keywords" in joined
    assert "Narrowed to 5 of 5 block(s)" in joined  # all 5 share the matched keyword
    # target-count detection + keyword-extraction call + planning call + result-naming call
    assert client.call_count == 4
    # the planning call's catalog must carry each block's full body, not a truncated preview
    planning_user_message = client.calls[2]["messages"][1]["content"]
    assert "**Environment:** Jira" in planning_user_message


def test_narrowing_top_n_is_identical_regardless_of_a_number_in_the_request(settings, fake_router):
    _seed_large_library(settings, count=6)
    keywords_reply = "ROLE: \nENVIRONMENT: Jira\nRESPONSIBILITIES: \nDOMAIN: \n"
    # two "use" steps so it satisfies required_count=2 for the "with number" run (target-count
    # detection fires ahead of planning, before keyword extraction) with no corrective retry
    plan = json.dumps(
        {
            "steps": [
                {"order": 1, "action": "use", "block_id": "block_0", "criteria": None},
                {"order": 2, "action": "use", "block_id": "block_1", "criteria": None},
            ]
        }
    )

    client_with_number = FakeLLMClient(replies=["2", keywords_reply, plan, "result"])
    fake_router(compose_module, client_with_number)
    events_with_number: list[ProgressEvent] = []
    compose_module.run_compose(
        "give me 2 projects that use Jira", settings=settings, on_progress=events_with_number.append
    )

    client_without_number = FakeLLMClient(replies=["NONE", keywords_reply, plan, "result"])
    fake_router(compose_module, client_without_number)
    events_without_number: list[ProgressEvent] = []
    compose_module.run_compose(
        "give me projects that use Jira", settings=settings, on_progress=events_without_number.append
    )

    narrowed_with = next(e.message for e in events_with_number if e.kind == "narrowing" and "Narrowed to" in e.message)
    narrowed_without = next(
        e.message for e in events_without_number if e.kind == "narrowing" and "Narrowed to" in e.message
    )
    assert narrowed_with == narrowed_without
    assert "Narrowed to 6 of 6 block(s)" in narrowed_with


def test_degenerate_keyword_reply_falls_back_to_the_full_catalog(settings, fake_router):
    _seed_large_library(settings, count=5)
    unparseable_keywords_reply = "I cannot help with that."
    plan = json.dumps({"steps": [{"order": 1, "action": "use", "block_id": "block_0", "criteria": None}]})
    client = FakeLLMClient(replies=["NONE", unparseable_keywords_reply, plan, "result"])
    fake_router(compose_module, client)

    events: list[ProgressEvent] = []
    compose_module.run_compose("need something", settings=settings, on_progress=events.append)

    joined = "\n".join(e.message for e in events)
    assert "No usable keywords extracted" in joined
    assert "Planning against 5 block(s)" in joined  # fell back to the full, unnarrowed catalog


def test_pinned_slots_are_unaffected_by_a_large_library(settings, fake_router):
    _seed_large_library(settings, count=5)
    client = FakeLLMClient(replies=["result_name"])
    fake_router(compose_module, client)

    # no NL request -> _plan_with_llm never runs, so keyword extraction never fires
    # regardless of library size
    slots, result_path = compose_module.run_compose("", settings=settings, use_ids=["block_0"])

    assert slots[0].resolved_id == "block_0"
    assert client.call_count == 1  # just the result-naming call


def test_compose_works_against_fake_block_and_result_storage(settings, fake_router, fake_storage):
    """Proves the BlockStorage/ResultStorage Protocols are complete: run_compose works
    unmodified against in-memory fakes, not just the filesystem implementations."""
    from fakes import FakeBlockStorage, FakeResultStorage

    fake_blocks = FakeBlockStorage()
    fake_blocks.save(
        Block(id="", body="## School\n\nTeaches children.\n\n**Rooms:**\n- Classroom\n"),
        filename_stem="school",
    )
    fake_results = FakeResultStorage()
    fake_storage(compose_module, block_store=fake_blocks, result_store=fake_results)
    fake_router(compose_module, FakeLLMClient(replies=["school_overview"]))

    slots, result_path = compose_module.run_compose("", settings=settings, use_ids=["school"])

    assert slots[0].resolved_id == "school"
    # a fake (like a future DB backend) has no filesystem path -- None is the correct,
    # honest result here, not a made-up path
    assert result_path is None
    saved = fake_results.load("school_overview")
    assert "## School" in saved.content


def test_dry_run_still_reports_the_plan_built_progress_line(settings, fake_router):
    _seed_library(settings)
    plan = json.dumps(
        {"steps": [{"order": 1, "action": "generate", "block_id": None, "criteria": "a hospital"}]}
    )
    fake_router(compose_module, FakeLLMClient(replies=["NONE", plan]))

    events: list[ProgressEvent] = []
    compose_module.run_compose(
        "need a hospital", settings=settings, dry_run=True, on_progress=events.append
    )

    assert any("Plan built: 1 step(s)" in e.message for e in events)
    # dry-run must not execute the generate step
    assert not any("generating new block" in e.message for e in events)


def test_count_with_no_pins_produces_exactly_that_many_slots(settings, fake_router):
    _seed_large_library(settings, count=3)  # below keyword_search_min_blocks -- no narrowing call
    plan = json.dumps(
        {
            "steps": [
                {"order": 1, "action": "use", "block_id": "block_0", "criteria": None},
                {"order": 2, "action": "use", "block_id": "block_1", "criteria": None},
                {"order": 3, "action": "use", "block_id": "block_2", "criteria": None},
            ]
        }
    )
    client = FakeLLMClient(replies=[plan, "result_name"])
    fake_router(compose_module, client)

    slots, result_path = compose_module.run_compose("need some projects", settings=settings, count=3)

    assert len(slots) == 3
    # plan call + result-naming call only -- count skips target-count-detection entirely
    assert client.call_count == 2


def test_count_combined_with_pins_only_plans_the_remainder(settings, fake_router):
    _seed_library(settings)
    plan = json.dumps({"steps": [{"order": 1, "action": "use", "block_id": "police_station", "criteria": None}]})
    client = FakeLLMClient(replies=[plan, "result_name"])
    fake_router(compose_module, client)

    slots, result_path = compose_module.run_compose("", settings=settings, use_ids=["school"], count=2)

    assert len(slots) == 2


def test_count_at_or_below_pinned_total_skips_the_planner_and_keeps_all_pins(settings, fake_router):
    _seed_library(settings)
    client = FakeLLMClient(replies=["result_name"])
    fake_router(compose_module, client)

    slots, result_path = compose_module.run_compose(
        "", settings=settings, use_ids=["school", "police_station"], count=1
    )

    assert len(slots) == 2
    assert {s.resolved_id for s in slots} == {"school", "police_station"}
    # only the result-naming call -- the planner is never invoked
    assert client.call_count == 1


def test_count_with_empty_request_still_invokes_the_planner_above_pinned_total(settings, fake_router):
    _seed_large_library(settings, count=3)  # below keyword_search_min_blocks -- no narrowing call
    plan = json.dumps(
        {
            "steps": [
                {"order": 1, "action": "use", "block_id": "block_1", "criteria": None},
                {"order": 2, "action": "use", "block_id": "block_2", "criteria": None},
            ]
        }
    )
    client = FakeLLMClient(replies=[plan, "result_name"])
    fake_router(compose_module, client)

    slots, result_path = compose_module.run_compose("", settings=settings, use_ids=["block_0"], count=3)

    assert len(slots) == 3


def test_zero_or_negative_count_is_rejected_before_any_llm_call(settings, fake_router):
    _seed_library(settings)
    client = FakeLLMClient()
    fake_router(compose_module, client)

    with pytest.raises(BlockValidationError):
        compose_module.run_compose("x", settings=settings, count=0)
    assert client.call_count == 0

    with pytest.raises(BlockValidationError):
        compose_module.run_compose("x", settings=settings, count=-1)
    assert client.call_count == 0


def test_corrective_retry_fixes_a_wrong_step_count(settings, fake_router):
    _seed_library(settings)
    wrong_plan = json.dumps({"steps": [{"order": 1, "action": "use", "block_id": "school", "criteria": None}]})
    fixed_plan = json.dumps(
        {
            "steps": [
                {"order": 1, "action": "use", "block_id": "school", "criteria": None},
                {"order": 2, "action": "use", "block_id": "police_station", "criteria": None},
            ]
        }
    )
    client = FakeLLMClient(replies=[wrong_plan, fixed_plan, "result_name"])
    fake_router(compose_module, client)

    slots, result_path = compose_module.run_compose("need two projects", settings=settings, count=2)

    assert len(slots) == 2
    assert client.call_count == 3


def test_deterministic_padding_when_retry_still_has_the_wrong_count(settings, fake_router):
    _seed_library(settings)
    wrong_plan = json.dumps({"steps": [{"order": 1, "action": "use", "block_id": "school", "criteria": None}]})
    # the two padded "generate" slots each execute for real -- script their bodies too
    generated_body_1 = "## Extra One\n\nFiller entry.\n\n**Rooms:**\n- Room\n"
    generated_body_2 = "## Extra Two\n\nFiller entry.\n\n**Rooms:**\n- Room\n"
    client = FakeLLMClient(replies=[wrong_plan, wrong_plan, generated_body_1, generated_body_2, "result_name"])
    fake_router(compose_module, client)
    fake_router(generate_module, client)

    slots, result_path = compose_module.run_compose("need three projects", settings=settings, count=3)

    assert len(slots) == 3
    padded = [s for s in slots if s.action == "generate" and s.criteria == "need three projects"]
    assert len(padded) == 2
    assert client.call_count == 5


def test_deterministic_truncation_when_retry_still_has_too_many(settings, fake_router):
    _seed_library(settings)
    over_plan = json.dumps(
        {
            "steps": [
                {"order": 1, "action": "use", "block_id": "school", "criteria": None},
                {"order": 2, "action": "use", "block_id": "police_station", "criteria": None},
            ]
        }
    )
    client = FakeLLMClient(replies=[over_plan, over_plan, "result_name"])
    fake_router(compose_module, client)

    slots, result_path = compose_module.run_compose("need one project", settings=settings, count=1)

    assert len(slots) == 1


def test_padding_still_respects_the_max_generate_cap(settings, fake_router):
    _seed_library(settings)
    plan = json.dumps({"steps": [{"order": 1, "action": "use", "block_id": "school", "criteria": None}]})
    client = FakeLLMClient(replies=[plan, plan])
    fake_router(compose_module, client)

    with pytest.raises(BlockValidationError):
        compose_module.run_compose("need three projects", settings=settings, count=3, max_generate=1)


def test_a_request_stated_count_is_honored_exactly(settings, fake_router):
    _seed_library(settings)
    plan = json.dumps(
        {
            "steps": [
                {"order": 1, "action": "use", "block_id": "school", "criteria": None},
                {"order": 2, "action": "use", "block_id": "police_station", "criteria": None},
            ]
        }
    )
    client = FakeLLMClient(replies=["2", plan, "result_name"])
    fake_router(compose_module, client)

    slots, result_path = compose_module.run_compose("need exactly 2 projects for a small town", settings=settings)

    assert len(slots) == 2
    assert client.call_count == 3


def test_a_hallucinated_request_count_falls_back_to_free_planning(settings, fake_router):
    _seed_library(settings)
    plan = json.dumps({"steps": [{"order": 1, "action": "use", "block_id": "school", "criteria": None}]})
    # the model claims "5" but the request never states any number -- the anti-hallucination
    # backstop must reject it, so no target count is forced and the planner is free to return
    # any number of steps; only 1 plan reply is scripted, so if the count were wrongly forced
    # to 5, the retry/pad logic would consume a reply that doesn't exist and this test would
    # fail with "ran out of scripted replies" instead of the assertion below
    client = FakeLLMClient(replies=["5", plan, "result_name"])
    fake_router(compose_module, client)

    slots, result_path = compose_module.run_compose("need projects for a small town", settings=settings)

    assert len(slots) == 1
    assert client.call_count == 3


def test_no_stated_count_falls_back_to_free_planning_exactly_as_before(settings, fake_router):
    _seed_library(settings)
    plan = json.dumps({"steps": [{"order": 1, "action": "use", "block_id": "school", "criteria": None}]})
    client = FakeLLMClient(replies=["NONE", plan, "result_name"])
    fake_router(compose_module, client)

    slots, result_path = compose_module.run_compose("need projects for a small town", settings=settings)

    assert len(slots) == 1
    assert client.call_count == 3
