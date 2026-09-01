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
    client = FakeLLMClient(replies=[plan, mutate_reply, generate_reply, "town_result"])
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
    client = FakeLLMClient(replies=[plan])
    fake_router(compose_module, client)

    events: list[ProgressEvent] = []
    slots, result_path = compose_module.run_compose(
        "need a hospital", settings=settings, on_progress=events.append, cancel_check=lambda: True
    )

    assert result_path is None
    assert slots[0].resolved_id is None
    assert client.call_count == 1  # just the planning call -- the generate slot never runs
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
    client = FakeLLMClient(replies=[plan, mutate_reply])
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


def test_below_threshold_library_skips_keyword_extraction(settings, fake_router):
    _seed_library(settings)  # 2 blocks, below the default keyword_search_min_blocks (5)
    plan = json.dumps({"steps": [{"order": 1, "action": "use", "block_id": "school", "criteria": None}]})
    client = FakeLLMClient(replies=[plan, "school_result"])
    fake_router(compose_module, client)

    events: list[ProgressEvent] = []
    compose_module.run_compose("need a school", settings=settings, on_progress=events.append)

    joined = "\n".join(e.message for e in events)
    assert "Extracting search keywords" not in joined
    assert "Planning against 2 block(s)" in joined
    # just the planning call + the result-naming call -- no extra keyword-extraction call
    assert client.call_count == 2


def test_at_threshold_library_extracts_keywords_and_narrows_the_catalog(settings, fake_router):
    _seed_large_library(settings, count=5)
    keywords_reply = "ROLE: \nENVIRONMENT: Jira\nRESPONSIBILITIES: \nDOMAIN: \n"
    plan = json.dumps({"steps": [{"order": 1, "action": "use", "block_id": "block_0", "criteria": None}]})
    client = FakeLLMClient(replies=[keywords_reply, plan, "result"])
    fake_router(compose_module, client)

    events: list[ProgressEvent] = []
    compose_module.run_compose("need something in Jira", settings=settings, on_progress=events.append)

    joined = "\n".join(e.message for e in events)
    assert "Extracting search keywords" in joined
    assert "Narrowed to 5 of 5 block(s)" in joined  # all 5 share the matched keyword
    # keyword-extraction call + planning call + result-naming call
    assert client.call_count == 3
    # the planning call's catalog must carry each block's full body, not a truncated preview
    planning_user_message = client.calls[1]["messages"][1]["content"]
    assert "**Environment:** Jira" in planning_user_message


def test_request_specified_project_count_overrides_the_configured_top_n(settings, fake_router):
    _seed_large_library(settings, count=6)
    keywords_reply = "ROLE: \nENVIRONMENT: Jira\nRESPONSIBILITIES: \nDOMAIN: \nPROJECT_COUNT: 2\n"
    plan = json.dumps({"steps": [{"order": 1, "action": "use", "block_id": "block_0", "criteria": None}]})
    client = FakeLLMClient(replies=[keywords_reply, plan, "result"])
    fake_router(compose_module, client)

    events: list[ProgressEvent] = []
    compose_module.run_compose(
        "give me 2 projects that use Jira", settings=settings, on_progress=events.append
    )

    joined = "\n".join(e.message for e in events)
    assert "Request specifies 2 project(s)" in joined
    assert "Narrowed to 2 of 6 block(s)" in joined


def test_degenerate_project_count_falls_back_to_the_configured_top_n(settings, fake_router):
    _seed_large_library(settings, count=6)
    # all 6 match, but PROJECT_COUNT is unparseable -- narrowing must fall back to the
    # configured default (12), which exceeds the library size, so nothing gets truncated
    keywords_reply = "ROLE: \nENVIRONMENT: Jira\nRESPONSIBILITIES: \nDOMAIN: \nPROJECT_COUNT: a few\n"
    plan = json.dumps({"steps": [{"order": 1, "action": "use", "block_id": "block_0", "criteria": None}]})
    client = FakeLLMClient(replies=[keywords_reply, plan, "result"])
    fake_router(compose_module, client)

    events: list[ProgressEvent] = []
    compose_module.run_compose(
        "give me projects that use Jira", settings=settings, on_progress=events.append
    )

    joined = "\n".join(e.message for e in events)
    assert "Request specifies" not in joined
    assert "Narrowed to 6 of 6 block(s)" in joined


def test_degenerate_keyword_reply_falls_back_to_the_full_catalog(settings, fake_router):
    _seed_large_library(settings, count=5)
    unparseable_keywords_reply = "I cannot help with that."
    plan = json.dumps({"steps": [{"order": 1, "action": "use", "block_id": "block_0", "criteria": None}]})
    client = FakeLLMClient(replies=[unparseable_keywords_reply, plan, "result"])
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
    fake_router(compose_module, FakeLLMClient(replies=[plan]))

    events: list[ProgressEvent] = []
    compose_module.run_compose(
        "need a hospital", settings=settings, dry_run=True, on_progress=events.append
    )

    assert any("Plan built: 1 step(s)" in e.message for e in events)
    # dry-run must not execute the generate step
    assert not any("generating new block" in e.message for e in events)
