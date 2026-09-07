import json

import pytest

from tools import compose as compose_module
from tools import generate as generate_module
from tools import mutate as mutate_module
from models.blocks import Block
from core.errors import BlockNotFoundError, BlockValidationError, InputError
from fakes import FakeLLMClient
from core.progress import ProgressEvent
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
    """A block library large enough to exercise keyword-search narrowing meaningfully."""
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

    outcome = compose_module.run_compose(
        "", settings=settings, use_ids=["school"], generate_criteria=["a sawmill"]
    )

    actions = {s.action: s.resolved_id for s in outcome.slots}
    assert actions["pinned_use"] == "school"
    assert actions["pinned_generate"] == "sawmill"
    content = outcome.result_path.read_text(encoding="utf-8")
    assert "## School" in content and "## Sawmill" in content
    assert outcome.result_path.name == "sawmill_overview.md"
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
    # a different subject than "Police Station" -> mutate's naming rule gives it a fresh entry
    mutate_reply = (
        "===BODY===\n## Sheriff Station\n\nFrontier law.\n\n**Rooms:**\n- Office\n"
        "===LABEL===\nSheriff Station"
    )
    unparseable_keywords_reply = "I cannot help with that."
    client = FakeLLMClient(replies=["NONE", unparseable_keywords_reply, plan, mutate_reply, "law_enforcement_setup"])
    fake_router(compose_module, client)
    fake_router(mutate_module, client)

    outcome = compose_module.run_compose("need law enforcement", settings=settings)

    assert outcome.slots[0].action == "mutate"
    assert outcome.slots[0].resolved_id == "sheriff_station"
    assert "Sheriff Station" in outcome.result_path.read_text(encoding="utf-8")
    assert outcome.result_path.name == "law_enforcement_setup.md"


def test_dry_run_makes_no_generate_or_mutate_calls(settings, fake_router):
    _seed_library(settings)
    plan = json.dumps(
        {"steps": [{"order": 1, "action": "generate", "block_id": None, "criteria": "a brand-new hospital"}]}
    )
    unparseable_keywords_reply = "I cannot help with that."
    client = FakeLLMClient(replies=["NONE", unparseable_keywords_reply, plan])
    fake_router(compose_module, client)

    outcome = compose_module.run_compose("need a hospital", settings=settings, dry_run=True)

    assert outcome.result_path is None
    assert outcome.slots[0].resolved_id is None  # generate was never actually run
    # target-count detection + keyword-extraction + planning call -- dry-run skips result naming too
    assert client.call_count == 3


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
    unparseable_keywords_reply = "I cannot help with that."
    fake_router(compose_module, FakeLLMClient(replies=["NONE", unparseable_keywords_reply, plan]))

    with pytest.raises(BlockValidationError):
        compose_module.run_compose("need three new things", settings=settings, max_generate=2)


def test_ordering_of_pinned_use_slots_is_respected_in_output(settings, fake_router):
    _seed_library(settings)
    fake_router(compose_module, FakeLLMClient(replies=["town_defense_and_school"]))

    outcome = compose_module.run_compose(
        "", settings=settings, use_ids=["police_station", "school"]
    )

    content = outcome.result_path.read_text(encoding="utf-8")
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
    outcome = compose_module.run_compose(
        "", settings=settings, use_ids=["school"], out_path=out
    )

    assert outcome.result_path == out
    assert out.exists()


def test_result_naming_reuses_the_same_file_for_identical_reruns(settings, fake_router):
    _seed_library(settings)
    client = FakeLLMClient(replies=["school_overview", "school_overview"])
    fake_router(compose_module, client)

    outcome1 = compose_module.run_compose("", settings=settings, use_ids=["school"])
    outcome2 = compose_module.run_compose("", settings=settings, use_ids=["school"])

    assert outcome2.result_path == outcome1.result_path
    assert outcome1.result_path.name == "school_overview.md"
    # one result-naming call per run; the second run's content is identical so
    # naming.decide() resolves it as an exact-match reuse with no further call
    assert client.call_count == 2


def test_result_naming_variant_on_a_conflicting_rerun(settings, fake_router):
    _seed_library(settings)
    # both runs' content-namer picks the same name; the second run's content differs, so
    # naming.decide() must ask for a distinguishing variant label as a third call
    client = FakeLLMClient(replies=["overview", "overview", "variant"])
    fake_router(compose_module, client)

    outcome1 = compose_module.run_compose("", settings=settings, use_ids=["school"])
    outcome2 = compose_module.run_compose(
        "", settings=settings, use_ids=["police_station"]
    )

    assert outcome1.result_path != outcome2.result_path
    assert outcome1.result_path.name == "overview.md"
    assert outcome2.result_path.name == "overview_mut_variant.md"
    assert client.call_count == 3


def test_no_manifest_file_is_written(settings, fake_router, tmp_path):
    _seed_library(settings)
    fake_router(compose_module, FakeLLMClient(replies=["school_overview"]))

    outcome = compose_module.run_compose("", settings=settings, use_ids=["school"])

    assert not outcome.result_path.with_name(outcome.result_path.stem + "_manifest.json").exists()
    assert list(outcome.result_path.parent.glob("*.json")) == []


def test_planning_call_includes_constraints_file_in_the_system_prompt(settings, fake_router, tmp_path):
    _seed_library(settings)
    constraints_file = tmp_path / "COMPOSE_CONSTRAINTS.md"
    constraints_file.write_text("Prefer mutate over generate.", encoding="utf-8")
    settings.path.constraints.compose = str(constraints_file)

    plan = json.dumps({"steps": [{"order": 1, "action": "use", "block_id": "school", "criteria": None}]})
    unparseable_keywords_reply = "I cannot help with that."
    client = FakeLLMClient(replies=["NONE", unparseable_keywords_reply, plan, "school_result"])
    fake_router(compose_module, client)

    compose_module.run_compose("need a school", settings=settings)

    planning_system_message = client.calls[2]["messages"][0]["content"]
    assert "Prefer mutate over generate." in planning_system_message
    # the result-naming call shares the compose tier's constraints file too
    naming_system_message = client.calls[3]["messages"][0]["content"]
    assert "Prefer mutate over generate." in naming_system_message


def test_target_count_detection_call_never_receives_compose_constraints(settings, fake_router, tmp_path):
    _seed_library(settings)
    constraints_file = tmp_path / "COMPOSE_CONSTRAINTS.md"
    constraints_file.write_text("Prefer mutate over generate.", encoding="utf-8")
    settings.path.constraints.compose = str(constraints_file)

    plan = json.dumps({"steps": [{"order": 1, "action": "use", "block_id": "school", "criteria": None}]})
    unparseable_keywords_reply = "I cannot help with that."
    client = FakeLLMClient(replies=["NONE", unparseable_keywords_reply, plan, "school_result"])
    fake_router(compose_module, client)

    compose_module.run_compose("need a school", settings=settings)

    detection_system_message = client.calls[0]["messages"][0]["content"]
    assert "Prefer mutate over generate." not in detection_system_message
    assert "<task>" in detection_system_message


def test_keyword_extraction_call_includes_the_keywords_tier_constraints_file(settings, fake_router, tmp_path):
    _seed_library(settings)
    settings.behavior.compose.keyword_search_top_n = 1  # force narrowing to run, not skip
    compose_constraints_file = tmp_path / "COMPOSE_CONSTRAINTS.md"
    compose_constraints_file.write_text("Prefer mutate over generate.", encoding="utf-8")
    settings.path.constraints.compose = str(compose_constraints_file)
    keywords_constraints_file = tmp_path / "KEYWORDS_CONSTRAINTS.md"
    keywords_constraints_file.write_text("Never invent a keyword the request doesn't imply.", encoding="utf-8")
    settings.path.constraints.keywords = str(keywords_constraints_file)

    plan = json.dumps({"steps": [{"order": 1, "action": "use", "block_id": "school", "criteria": None}]})
    unparseable_keywords_reply = "I cannot help with that."
    client = FakeLLMClient(replies=["NONE", unparseable_keywords_reply, plan, "school_result"])
    fake_router(compose_module, client)

    compose_module.run_compose("need a school", settings=settings)

    keyword_system_message = client.calls[1]["messages"][0]["content"]
    assert "Never invent a keyword the request doesn't imply." in keyword_system_message
    assert "Prefer mutate over generate." not in keyword_system_message


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
    unparseable_keywords_reply = "I cannot help with that."
    client = FakeLLMClient(
        replies=["NONE", unparseable_keywords_reply, plan, mutate_reply, generate_reply, "town_result"]
    )
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
    unparseable_keywords_reply = "I cannot help with that."
    client = FakeLLMClient(replies=["NONE", unparseable_keywords_reply, plan])
    fake_router(compose_module, client)

    events: list[ProgressEvent] = []
    outcome = compose_module.run_compose(
        "need a hospital", settings=settings, on_progress=events.append, cancel_check=lambda: True
    )

    assert outcome.result_path is None
    assert outcome.slots[0].resolved_id is None
    # target-count detection + keyword-extraction + the planning call -- the generate slot never runs
    assert client.call_count == 3
    assert any(e.kind == "cancelled" for e in events)
    assert outcome.cancelled is True
    assert outcome.result_id is None
    assert outcome.content is None


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
    unparseable_keywords_reply = "I cannot help with that."
    client = FakeLLMClient(replies=["NONE", unparseable_keywords_reply, plan, mutate_reply])
    fake_router(compose_module, client)
    fake_router(mutate_module, client)

    calls = {"n": 0}

    def cancel_after_first_slot():
        calls["n"] += 1
        return calls["n"] > 1  # False before slot 1, True before slot 2

    outcome = compose_module.run_compose(
        "need law enforcement and lumber", settings=settings, cancel_check=cancel_after_first_slot
    )

    assert outcome.result_path is None  # cancelled before the combined result could be saved
    assert outcome.slots[0].resolved_id == "sheriff_station"  # slot 1 completed and stays saved
    assert outcome.slots[1].resolved_id is None  # slot 2 never ran
    assert outcome.cancelled is True
    assert outcome.result_id is None
    assert outcome.content is None


def test_small_library_skips_narrowing_and_still_composes(settings, fake_router):
    _seed_library(settings)  # 2 blocks, well within the default top_n -- narrowing is skipped
    plan = json.dumps({"steps": [{"order": 1, "action": "use", "block_id": "school", "criteria": None}]})
    client = FakeLLMClient(replies=["NONE", plan, "school_result"])
    fake_router(compose_module, client)

    events: list[ProgressEvent] = []
    compose_module.run_compose("need a school", settings=settings, on_progress=events.append)

    joined = "\n".join(e.message for e in events)
    assert "Extracting search keywords" not in joined
    assert "All 2 candidate(s) already fit within the window" in joined
    assert "Planning against 2 block(s)" in joined
    assert any(e.kind == "narrowing_skipped" for e in events)
    # target-count detection + planning call + result-naming call -- no keyword-extraction call
    assert client.call_count == 3


def test_keyword_extraction_narrows_the_catalog(settings, fake_router):
    settings.llm.models.naming = "fakeprov:naming-model"
    settings.llm.models.keywords = "fakeprov:keywords-model"
    settings.behavior.compose.keyword_search_top_n = 4  # below library size -- forces narrowing, not skip
    _seed_large_library(settings, count=5)
    keywords_reply = "ROLE: \nENVIRONMENT: Jira\nRESPONSIBILITIES: \nDOMAIN: \n"
    plan = json.dumps({"steps": [{"order": 1, "action": "use", "block_id": "block_0", "criteria": None}]})
    client = FakeLLMClient(replies=["NONE", keywords_reply, plan, "result"])
    fake_router(compose_module, client)

    events: list[ProgressEvent] = []
    compose_module.run_compose("need something in Jira", settings=settings, on_progress=events.append)

    joined = "\n".join(e.message for e in events)
    assert "Extracting search keywords" in joined
    assert "Narrowed to 4 of 5 block(s)" in joined  # top_n=4 caps the 5 equally-matched blocks
    # target-count detection + keyword-extraction call + planning call + result-naming call
    assert client.call_count == 4
    # the planning call's catalog must carry each block's full body, not a truncated preview
    planning_user_message = client.calls[2]["messages"][1]["content"]
    assert "**Environment:** Jira" in planning_user_message
    # target-count detection (call 0) still dispatches against the naming model...
    assert client.calls[0]["model"] == "naming-model"
    # ...while keyword extraction (call 1) dispatches against the distinct keywords model
    assert client.calls[1]["model"] == "keywords-model"


def test_naming_collision_and_target_count_stay_on_the_naming_model(settings, fake_router):
    settings.llm.models.naming = "fakeprov:naming-model"
    settings.llm.models.keywords = "fakeprov:keywords-model"
    _seed_library(settings)
    unparseable_keywords_reply = "I cannot help with that."
    plan = json.dumps({"steps": [{"order": 1, "action": "use", "block_id": "school", "criteria": None}]})
    client = FakeLLMClient(replies=["NONE", unparseable_keywords_reply, plan, "result_name"])
    fake_router(compose_module, client)

    compose_module.run_compose("need a school", settings=settings)

    # target-count extraction (call 0) is unaffected by the distinct keywords setting
    assert client.calls[0]["model"] == "naming-model"

    # both runs' content-namer picks the same name; the second run's content differs, so
    # naming.decide() must ask for a distinguishing variant label as a third call
    variant_client = FakeLLMClient(replies=["overview", "overview", "variant"])
    fake_router(compose_module, variant_client)

    compose_module.run_compose("", settings=settings, use_ids=["school"])
    compose_module.run_compose("", settings=settings, use_ids=["police_station"])

    # the naming-collision decision (save_with_dedup's naming_model) also stays on naming
    assert variant_client.calls[-1]["model"] == "naming-model"


def test_narrowing_top_n_is_identical_regardless_of_a_number_in_the_request(settings, fake_router):
    settings.behavior.compose.keyword_search_top_n = 3  # below library size -- forces narrowing, not skip
    _seed_large_library(settings, count=6)
    keywords_reply = "ROLE: \nENVIRONMENT: Jira\nRESPONSIBILITIES: \nDOMAIN: \n"
    # two "use" steps so the "with number" run's required_count=2 needs no corrective retry
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

    narrowed_with = next(
        e.message for e in events_with_number if e.kind == "narrowing_done" and "Narrowed to" in e.message
    )
    narrowed_without = next(
        e.message for e in events_without_number if e.kind == "narrowing_done" and "Narrowed to" in e.message
    )
    assert narrowed_with == narrowed_without
    assert "Narrowed to 3 of 6 block(s)" in narrowed_with


def test_degenerate_keyword_reply_falls_back_to_the_full_catalog(settings, fake_router):
    settings.behavior.compose.keyword_search_top_n = 4  # below library size -- forces narrowing, not skip
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
    outcome = compose_module.run_compose("", settings=settings, use_ids=["block_0"])

    assert outcome.slots[0].resolved_id == "block_0"
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

    outcome = compose_module.run_compose("", settings=settings, use_ids=["school"])

    assert outcome.slots[0].resolved_id == "school"
    # a fake has no filesystem path -- None is the correct, honest result here
    assert outcome.result_path is None
    saved = fake_results.load("school_overview")
    assert "## School" in saved.content


def test_run_compose_returns_result_id_and_content_even_when_path_for_returns_none(
    settings, fake_router, fake_storage
):
    """Regression test: SqliteResultStorage.path_for() always returns None, even on a
    successful run -- FakeResultStorage mirrors that here. run_compose must still hand back
    result_id/name/content directly rather than depending on a real filesystem path."""
    from fakes import FakeBlockStorage, FakeResultStorage

    fake_blocks = FakeBlockStorage()
    fake_blocks.save(
        Block(id="", body="## School\n\nTeaches children.\n\n**Rooms:**\n- Classroom\n"),
        filename_stem="school",
    )
    fake_results = FakeResultStorage()
    fake_storage(compose_module, block_store=fake_blocks, result_store=fake_results)
    fake_router(compose_module, FakeLLMClient(replies=["school_overview"]))

    outcome = compose_module.run_compose("", settings=settings, use_ids=["school"])

    assert outcome.result_id is not None
    assert outcome.name is not None
    assert outcome.content is not None
    assert outcome.result_path is None


def test_dry_run_still_reports_the_plan_built_progress_line(settings, fake_router):
    _seed_library(settings)
    plan = json.dumps(
        {"steps": [{"order": 1, "action": "generate", "block_id": None, "criteria": "a hospital"}]}
    )
    unparseable_keywords_reply = "I cannot help with that."
    fake_router(compose_module, FakeLLMClient(replies=["NONE", unparseable_keywords_reply, plan]))

    events: list[ProgressEvent] = []
    compose_module.run_compose(
        "need a hospital", settings=settings, dry_run=True, on_progress=events.append
    )

    assert any("Plan built: 1 step(s)" in e.message for e in events)
    # dry-run must not execute the generate step
    assert not any("generating new block" in e.message for e in events)


def test_count_with_no_pins_produces_exactly_that_many_slots(settings, fake_router):
    _seed_large_library(settings, count=3)  # small library -- narrowing still runs
    unparseable_keywords_reply = "I cannot help with that."
    plan = json.dumps(
        {
            "steps": [
                {"order": 1, "action": "use", "block_id": "block_0", "criteria": None},
                {"order": 2, "action": "use", "block_id": "block_1", "criteria": None},
                {"order": 3, "action": "use", "block_id": "block_2", "criteria": None},
            ]
        }
    )
    client = FakeLLMClient(replies=[unparseable_keywords_reply, plan, "result_name"])
    fake_router(compose_module, client)

    outcome = compose_module.run_compose("need some projects", settings=settings, count=3)

    assert len(outcome.slots) == 3
    # keyword-extraction call + plan call + result-naming call -- count skips
    # target-count-detection entirely, but narrowing still runs
    assert client.call_count == 3


def test_count_combined_with_pins_only_plans_the_remainder(settings, fake_router):
    _seed_library(settings)
    unparseable_keywords_reply = "I cannot help with that."
    plan = json.dumps({"steps": [{"order": 1, "action": "use", "block_id": "police_station", "criteria": None}]})
    client = FakeLLMClient(replies=[unparseable_keywords_reply, plan, "result_name"])
    fake_router(compose_module, client)

    outcome = compose_module.run_compose("", settings=settings, use_ids=["school"], count=2)

    assert len(outcome.slots) == 2


def test_count_at_or_below_pinned_total_skips_the_planner_and_keeps_all_pins(settings, fake_router):
    _seed_library(settings)
    client = FakeLLMClient(replies=["result_name"])
    fake_router(compose_module, client)

    outcome = compose_module.run_compose(
        "", settings=settings, use_ids=["school", "police_station"], count=1
    )

    assert len(outcome.slots) == 2
    assert {s.resolved_id for s in outcome.slots} == {"school", "police_station"}
    # only the result-naming call -- the planner is never invoked
    assert client.call_count == 1


def test_count_with_empty_request_still_invokes_the_planner_above_pinned_total(settings, fake_router):
    _seed_large_library(settings, count=3)  # small library -- narrowing still runs
    unparseable_keywords_reply = "I cannot help with that."
    plan = json.dumps(
        {
            "steps": [
                {"order": 1, "action": "use", "block_id": "block_1", "criteria": None},
                {"order": 2, "action": "use", "block_id": "block_2", "criteria": None},
            ]
        }
    )
    client = FakeLLMClient(replies=[unparseable_keywords_reply, plan, "result_name"])
    fake_router(compose_module, client)

    outcome = compose_module.run_compose("", settings=settings, use_ids=["block_0"], count=3)

    assert len(outcome.slots) == 3


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
    unparseable_keywords_reply = "I cannot help with that."
    client = FakeLLMClient(replies=[unparseable_keywords_reply, wrong_plan, fixed_plan, "result_name"])
    fake_router(compose_module, client)

    outcome = compose_module.run_compose("need two projects", settings=settings, count=2)

    assert len(outcome.slots) == 2
    assert client.call_count == 4


def test_deterministic_padding_when_retry_still_has_the_wrong_count(settings, fake_router):
    _seed_library(settings)
    wrong_plan = json.dumps({"steps": [{"order": 1, "action": "use", "block_id": "school", "criteria": None}]})
    # the two padded "generate" slots each execute for real -- script their bodies too
    generated_body_1 = "## Extra One\n\nFiller entry.\n\n**Rooms:**\n- Room\n"
    generated_body_2 = "## Extra Two\n\nFiller entry.\n\n**Rooms:**\n- Room\n"
    unparseable_keywords_reply = "I cannot help with that."
    client = FakeLLMClient(
        replies=[unparseable_keywords_reply, wrong_plan, wrong_plan, generated_body_1, generated_body_2, "result_name"]
    )
    fake_router(compose_module, client)
    fake_router(generate_module, client)

    outcome = compose_module.run_compose("need three projects", settings=settings, count=3)

    assert len(outcome.slots) == 3
    padded = [s for s in outcome.slots if s.action == "generate" and s.criteria == "need three projects"]
    assert len(padded) == 2
    assert client.call_count == 6


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
    unparseable_keywords_reply = "I cannot help with that."
    client = FakeLLMClient(replies=[unparseable_keywords_reply, over_plan, over_plan, "result_name"])
    fake_router(compose_module, client)

    outcome = compose_module.run_compose("need one project", settings=settings, count=1)

    assert len(outcome.slots) == 1


def test_padding_still_respects_the_max_generate_cap(settings, fake_router):
    _seed_library(settings)
    plan = json.dumps({"steps": [{"order": 1, "action": "use", "block_id": "school", "criteria": None}]})
    unparseable_keywords_reply = "I cannot help with that."
    client = FakeLLMClient(replies=[unparseable_keywords_reply, plan, plan])
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
    unparseable_keywords_reply = "I cannot help with that."
    client = FakeLLMClient(replies=["2", unparseable_keywords_reply, plan, "result_name"])
    fake_router(compose_module, client)

    outcome = compose_module.run_compose("need exactly 2 projects for a small town", settings=settings)

    assert len(outcome.slots) == 2
    assert client.call_count == 4


def test_a_hallucinated_request_count_falls_back_to_free_planning(settings, fake_router):
    _seed_library(settings)
    plan = json.dumps({"steps": [{"order": 1, "action": "use", "block_id": "school", "criteria": None}]})
    # a claimed count not stated in the request must be rejected, not forced onto the plan
    unparseable_keywords_reply = "I cannot help with that."
    client = FakeLLMClient(replies=["5", unparseable_keywords_reply, plan, "result_name"])
    fake_router(compose_module, client)

    outcome = compose_module.run_compose("need projects for a small town", settings=settings)

    assert len(outcome.slots) == 1
    assert client.call_count == 4


def test_no_stated_count_falls_back_to_free_planning_exactly_as_before(settings, fake_router):
    _seed_library(settings)
    plan = json.dumps({"steps": [{"order": 1, "action": "use", "block_id": "school", "criteria": None}]})
    unparseable_keywords_reply = "I cannot help with that."
    client = FakeLLMClient(replies=["NONE", unparseable_keywords_reply, plan, "result_name"])
    fake_router(compose_module, client)

    outcome = compose_module.run_compose("need projects for a small town", settings=settings)

    assert len(outcome.slots) == 1
    assert client.call_count == 4


def test_plan_event_carries_structured_step_list_before_execution(settings, fake_router):
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
    unparseable_keywords_reply = "I cannot help with that."
    client = FakeLLMClient(
        replies=["NONE", unparseable_keywords_reply, plan, mutate_reply, generate_reply, "town_result"]
    )
    fake_router(compose_module, client)
    fake_router(mutate_module, client)
    fake_router(generate_module, client)

    events: list[ProgressEvent] = []
    compose_module.run_compose(
        "need law enforcement and lumber", settings=settings, on_progress=events.append
    )

    plan_events = [e for e in events if e.kind == "plan"]
    assert len(plan_events) == 1
    steps = plan_events[0].data["steps"]
    assert steps == [
        {"order": 1, "action": "mutate", "block_id": "police_station", "criteria": "adapt"},
        {"order": 2, "action": "generate", "block_id": None, "criteria": "a sawmill"},
    ]
    for step in steps:
        assert set(step.keys()) == {"order", "action", "block_id", "criteria"}
        assert "resolved_id" not in step

    plan_done_index = next(i for i, e in enumerate(events) if e.kind == "plan_done")
    plan_index = next(i for i, e in enumerate(events) if e.kind == "plan")
    first_step_index = next(i for i, e in enumerate(events) if e.kind in ("use", "mutate_start", "generate_start"))
    assert plan_done_index < plan_index < first_step_index

    plan_done_index = next(i for i, e in enumerate(events) if e.kind == "plan_done")
    plan_index = next(i for i, e in enumerate(events) if e.kind == "plan")
    first_step_index = next(i for i, e in enumerate(events) if e.kind in ("mutate_start", "generate_start"))
    assert plan_done_index < plan_index < first_step_index


def test_explicit_name_bypasses_result_naming_and_preserves_raw_text(settings, fake_router):
    _seed_library(settings)
    client = FakeLLMClient()  # no scripted replies -- any chat() call is a test failure
    fake_router(compose_module, client)

    outcome = compose_module.run_compose(
        "", settings=settings, use_ids=["school"], name="My Result"
    )

    assert outcome.result_path.name == "my_result.md"
    assert outcome.name == "My Result"
    assert client.call_count == 0  # no result-title-generation call, no naming-tier call either

    from storage.filesystem import FilesystemResultStorage

    saved = FilesystemResultStorage(settings.path.results_dir).load("my_result")
    assert saved.name == "My Result"  # stored as-is, never slugified


def test_explicit_name_collision_gets_numbered_not_deduped(settings, fake_router):
    _seed_library(settings)
    client = FakeLLMClient()
    fake_router(compose_module, client)

    outcome1 = compose_module.run_compose(
        "", settings=settings, use_ids=["school"], name="My Result"
    )
    outcome2 = compose_module.run_compose(
        "", settings=settings, use_ids=["police_station"], name="My Result"
    )

    assert outcome1.result_path.name == "my_result.md"
    # same explicit name -> numbered variant, not a content-based dedup skip, even though
    # this second run's content differs from the first
    assert outcome2.result_path.name == "my_result_2.md"
    assert client.call_count == 0


def test_explicit_name_collision_still_numbers_when_content_is_identical(settings, fake_router):
    _seed_library(settings)
    client = FakeLLMClient()
    fake_router(compose_module, client)

    outcome1 = compose_module.run_compose(
        "", settings=settings, use_ids=["school"], name="My Result"
    )
    outcome2 = compose_module.run_compose(
        "", settings=settings, use_ids=["school"], name="My Result"
    )

    assert outcome1.result_path.name == "my_result.md"
    assert outcome2.result_path.name == "my_result_2.md"
    assert client.call_count == 0


def test_invalid_explicit_name_is_rejected_before_any_work(settings, fake_router):
    _seed_library(settings)
    client = FakeLLMClient()
    fake_router(compose_module, client)

    with pytest.raises(InputError):
        compose_module.run_compose(
            "need a school",
            settings=settings,
            use_ids=["does-not-exist"],
            generate_criteria=["a sawmill"],
            name="!!!",
        )
    # rejected before even the pinned-use existence check (BlockNotFoundError never raised)
    # or any generate/mutate/planning/naming LLM call
    assert client.call_count == 0


def test_restrict_generate_corrects_planner_generate_to_use(settings, fake_router):
    _seed_library(settings)
    illegal_plan = json.dumps(
        {"steps": [{"order": 1, "action": "generate", "block_id": None, "criteria": "a filler entry"}]}
    )
    unparseable_keywords_reply = "I cannot help with that."
    client = FakeLLMClient(replies=[unparseable_keywords_reply, illegal_plan, illegal_plan, "result_name"])
    fake_router(compose_module, client)

    outcome = compose_module.run_compose(
        "need a filler entry", settings=settings, count=1, restrict_generate=True
    )

    assert len(outcome.slots) == 1
    slot = outcome.slots[0]
    assert slot.action == "use"
    assert slot.block_id in ("school", "police_station")
    assert client.call_count == 4


def test_restrict_generate_pads_shortfall_with_use_not_generate(settings, fake_router):
    _seed_library(settings)
    wrong_plan = json.dumps({"steps": [{"order": 1, "action": "use", "block_id": "school", "criteria": None}]})
    unparseable_keywords_reply = "I cannot help with that."
    client = FakeLLMClient(replies=[unparseable_keywords_reply, wrong_plan, wrong_plan, "result_name"])
    fake_router(compose_module, client)

    outcome = compose_module.run_compose(
        "need two projects", settings=settings, count=2, restrict_generate=True
    )

    assert len(outcome.slots) == 2
    assert all(s.action == "use" for s in outcome.slots)
    assert {s.block_id for s in outcome.slots} == {"school", "police_station"}
    assert client.call_count == 4


def test_restrict_mutate_corrects_planner_mutate_to_use_same_block(settings, fake_router):
    _seed_library(settings)
    illegal_plan = json.dumps(
        {"steps": [{"order": 1, "action": "mutate", "block_id": "school", "criteria": "re-theme"}]}
    )
    unparseable_keywords_reply = "I cannot help with that."
    client = FakeLLMClient(replies=[unparseable_keywords_reply, illegal_plan, illegal_plan, "result_name"])
    fake_router(compose_module, client)

    outcome = compose_module.run_compose(
        "adapt the school", settings=settings, count=1, restrict_mutate=True
    )

    assert len(outcome.slots) == 1
    slot = outcome.slots[0]
    assert slot.action == "use"
    assert slot.block_id == "school"
    assert slot.criteria is None
    assert client.call_count == 4


def test_restrict_mutate_falls_back_when_block_id_already_claimed(settings, fake_router):
    _seed_library(settings)
    plan = json.dumps(
        {
            "steps": [
                {"order": 1, "action": "use", "block_id": "school", "criteria": None},
                {"order": 2, "action": "mutate", "block_id": "school", "criteria": "re-theme"},
            ]
        }
    )
    unparseable_keywords_reply = "I cannot help with that."
    client = FakeLLMClient(replies=[unparseable_keywords_reply, plan, plan, "result_name"])
    fake_router(compose_module, client)

    outcome = compose_module.run_compose(
        "need two related entries", settings=settings, count=2, restrict_mutate=True
    )

    assert len(outcome.slots) == 2
    assert all(s.action == "use" for s in outcome.slots)
    assert {s.block_id for s in outcome.slots} == {"school", "police_station"}


def test_both_restrictions_together_produce_use_only_plan(settings, fake_router):
    _seed_library(settings)
    plan = json.dumps(
        {
            "steps": [
                {"order": 1, "action": "generate", "block_id": None, "criteria": "brand new"},
                {"order": 2, "action": "mutate", "block_id": "school", "criteria": "re-theme"},
            ]
        }
    )
    unparseable_keywords_reply = "I cannot help with that."
    client = FakeLLMClient(replies=[unparseable_keywords_reply, plan, plan, "result_name"])
    fake_router(compose_module, client)

    outcome = compose_module.run_compose(
        "need two entries", settings=settings, count=2, restrict_generate=True, restrict_mutate=True
    )

    assert len(outcome.slots) == 2
    assert all(s.action == "use" for s in outcome.slots)
    assert {s.block_id for s in outcome.slots} == {"school", "police_station"}


def test_restrict_generate_conflicts_with_pinned_generate(settings, fake_router):
    _seed_library(settings)
    with pytest.raises(BlockValidationError):
        compose_module.run_compose(
            "", settings=settings, generate_criteria=["a sawmill"], restrict_generate=True
        )


def test_from_block_ids_restricts_the_candidate_pool_and_catalog(settings, fake_router):
    _seed_large_library(settings, count=5)
    plan = json.dumps({"steps": [{"order": 1, "action": "use", "block_id": "block_0", "criteria": None}]})
    unparseable_keywords_reply = "I cannot help with that."
    client = FakeLLMClient(replies=[unparseable_keywords_reply, plan, "result_name"])
    fake_router(compose_module, client)

    outcome = compose_module.run_compose(
        "need one project", settings=settings, count=1, from_block_ids=["block_0", "block_1"]
    )

    assert outcome.slots[-1].block_id == "block_0"
    planning_message = client.calls[1]["messages"][1]["content"]
    assert "block_0" in planning_message and "block_1" in planning_message
    assert "block_2" not in planning_message
    assert "block_3" not in planning_message
    assert "block_4" not in planning_message


def test_from_block_ids_unresolvable_id_raises_before_any_llm_call(settings, fake_router):
    _seed_library(settings)
    client = FakeLLMClient()
    fake_router(compose_module, client)

    with pytest.raises(BlockNotFoundError):
        compose_module.run_compose(
            "need one project", settings=settings, count=1, from_block_ids=["does-not-exist"]
        )
    assert client.call_count == 0


def test_from_block_ids_empty_list_is_rejected_before_any_llm_call(settings, fake_router):
    _seed_library(settings)
    client = FakeLLMClient()
    fake_router(compose_module, client)

    with pytest.raises(BlockValidationError):
        compose_module.run_compose("need one project", settings=settings, count=1, from_block_ids=[])
    assert client.call_count == 0


def test_from_block_ids_still_permits_mutation_when_not_restricted(settings, fake_router):
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
    mutate_reply = (
        "===BODY===\n## Sheriff Station\n\nFrontier law.\n\n**Rooms:**\n- Office\n"
        "===LABEL===\nSheriff Station"
    )
    unparseable_keywords_reply = "I cannot help with that."
    client = FakeLLMClient(replies=[unparseable_keywords_reply, plan, mutate_reply, "law_enforcement_setup"])
    fake_router(compose_module, client)
    fake_router(mutate_module, client)

    outcome = compose_module.run_compose(
        "need law enforcement", settings=settings, count=1, from_block_ids=["school", "police_station"]
    )

    assert outcome.slots[0].action == "mutate"
    assert outcome.slots[0].resolved_id == "sheriff_station"


def test_use_id_within_from_block_ids_composes_with_it_pinned(settings, fake_router):
    _seed_library(settings)
    client = FakeLLMClient(replies=["result_name"])
    fake_router(compose_module, client)

    outcome = compose_module.run_compose(
        "", settings=settings, use_ids=["school"], from_block_ids=["school", "police_station"]
    )

    assert outcome.slots[0].action == "pinned_use"
    assert outcome.slots[0].block_id == "school"


def test_use_id_outside_from_block_ids_is_rejected_before_any_work(settings, fake_router):
    store = _seed_library(settings)
    store.save(
        Block(id="", body="## Hospital\n\nTreats patients.\n\n**Rooms:**\n- Ward\n"),
        filename_stem="hospital",
    )
    client = FakeLLMClient()
    fake_router(compose_module, client)

    with pytest.raises(BlockValidationError):
        compose_module.run_compose(
            "", settings=settings, use_ids=["hospital"], from_block_ids=["school", "police_station"]
        )
    assert client.call_count == 0


def test_use_id_validation_unchanged_without_from_block_ids(settings, fake_router):
    _seed_library(settings)
    client = FakeLLMClient(replies=["result_name"])
    fake_router(compose_module, client)

    outcome = compose_module.run_compose("", settings=settings, use_ids=["school"])

    assert outcome.slots[0].action == "pinned_use"
    assert outcome.slots[0].block_id == "school"


def test_hard_rejection_when_target_exceeds_raw_library_size(settings, fake_router):
    _seed_large_library(settings, count=3)
    client = FakeLLMClient(replies=[])
    fake_router(compose_module, client)

    with pytest.raises(BlockValidationError):
        compose_module.run_compose(
            "need many projects", settings=settings, count=5, restrict_generate=True
        )
    assert client.call_count == 0


def test_hard_rejection_ignores_pinned_count_and_uses_raw_total(settings, fake_router):
    _seed_large_library(settings, count=4)
    client = FakeLLMClient(replies=[])
    fake_router(compose_module, client)

    with pytest.raises(BlockValidationError):
        compose_module.run_compose(
            "", settings=settings, use_ids=["block_0"], count=5, restrict_generate=True
        )
    assert client.call_count == 0


def test_hard_rejection_does_not_fire_when_generation_is_unrestricted(settings, fake_router):
    _seed_large_library(settings, count=3)
    plan = json.dumps(
        {
            "steps": [
                {"order": 1, "action": "use", "block_id": "block_0", "criteria": None},
                {"order": 2, "action": "use", "block_id": "block_1", "criteria": None},
                {"order": 3, "action": "use", "block_id": "block_2", "criteria": None},
                {"order": 4, "action": "generate", "block_id": None, "criteria": "extra one"},
                {"order": 5, "action": "generate", "block_id": None, "criteria": "extra two"},
            ]
        }
    )
    unparseable_keywords_reply = "I cannot help with that."
    client = FakeLLMClient(replies=[unparseable_keywords_reply, plan])
    fake_router(compose_module, client)

    outcome = compose_module.run_compose(
        "need five projects", settings=settings, count=5, restrict_generate=False, dry_run=True
    )

    assert len(outcome.slots) == 5


def test_hard_rejection_does_not_fire_when_count_fits_the_library(settings, fake_router):
    _seed_large_library(settings, count=3)
    plan = json.dumps(
        {
            "steps": [
                {"order": 1, "action": "use", "block_id": "block_0", "criteria": None},
                {"order": 2, "action": "use", "block_id": "block_1", "criteria": None},
                {"order": 3, "action": "use", "block_id": "block_2", "criteria": None},
            ]
        }
    )
    unparseable_keywords_reply = "I cannot help with that."
    client = FakeLLMClient(replies=[unparseable_keywords_reply, plan])
    fake_router(compose_module, client)

    outcome = compose_module.run_compose(
        "need three projects", settings=settings, count=3, restrict_generate=True, dry_run=True
    )

    assert len(outcome.slots) == 3


def test_warning_widens_narrowing_window_when_configured_top_n_is_too_small(settings, fake_router):
    settings.behavior.compose.keyword_search_top_n = 2
    _seed_large_library(settings, count=5)
    keywords_reply = "ROLE: \nENVIRONMENT: Jira\nRESPONSIBILITIES: \nDOMAIN: \n"
    plan = json.dumps(
        {
            "steps": [
                {"order": 1, "action": "use", "block_id": "block_0", "criteria": None},
                {"order": 2, "action": "use", "block_id": "block_1", "criteria": None},
                {"order": 3, "action": "use", "block_id": "block_2", "criteria": None},
                {"order": 4, "action": "use", "block_id": "block_3", "criteria": None},
            ]
        }
    )
    client = FakeLLMClient(replies=[keywords_reply, plan])
    fake_router(compose_module, client)
    events: list[ProgressEvent] = []

    outcome = compose_module.run_compose(
        "need four projects",
        settings=settings,
        count=4,
        restrict_generate=True,
        dry_run=True,
        on_progress=events.append,
    )

    assert len(outcome.slots) == 4
    assert any(e.kind == "warning" for e in events)


def test_no_warning_when_configured_top_n_already_suffices(settings, fake_router):
    _seed_large_library(settings, count=5)
    keywords_reply = "ROLE: \nENVIRONMENT: Jira\nRESPONSIBILITIES: \nDOMAIN: \n"
    plan = json.dumps(
        {
            "steps": [
                {"order": 1, "action": "use", "block_id": "block_0", "criteria": None},
                {"order": 2, "action": "use", "block_id": "block_1", "criteria": None},
                {"order": 3, "action": "use", "block_id": "block_2", "criteria": None},
                {"order": 4, "action": "use", "block_id": "block_3", "criteria": None},
            ]
        }
    )
    client = FakeLLMClient(replies=[keywords_reply, plan])
    fake_router(compose_module, client)
    events: list[ProgressEvent] = []

    outcome = compose_module.run_compose(
        "need four projects",
        settings=settings,
        count=4,
        restrict_generate=True,
        dry_run=True,
        on_progress=events.append,
    )

    assert len(outcome.slots) == 4
    assert not any(e.kind == "warning" for e in events)


def test_hard_rejection_when_target_exceeds_designated_set_size(settings, fake_router):
    _seed_large_library(settings, count=5)
    client = FakeLLMClient(replies=[])
    fake_router(compose_module, client)

    with pytest.raises(BlockValidationError):
        compose_module.run_compose(
            "",
            settings=settings,
            use_ids=["block_0"],
            count=3,
            from_block_ids=["block_0", "block_1"],
        )
    assert client.call_count == 0


def test_hard_rejection_does_not_fire_without_from_block_ids_when_unrestricted(settings, fake_router):
    _seed_large_library(settings, count=3)
    plan = json.dumps(
        {
            "steps": [
                {"order": 1, "action": "use", "block_id": "block_0", "criteria": None},
                {"order": 2, "action": "generate", "block_id": None, "criteria": "extra one"},
                {"order": 3, "action": "generate", "block_id": None, "criteria": "extra two"},
                {"order": 4, "action": "generate", "block_id": None, "criteria": "extra three"},
                {"order": 5, "action": "generate", "block_id": None, "criteria": "extra four"},
            ]
        }
    )
    unparseable_keywords_reply = "I cannot help with that."
    client = FakeLLMClient(replies=[unparseable_keywords_reply, plan])
    fake_router(compose_module, client)

    outcome = compose_module.run_compose(
        "need five projects", settings=settings, count=5, from_block_ids=None, dry_run=True
    )

    assert len(outcome.slots) == 5


def test_warning_widens_narrowing_window_scoped_to_designated_set(settings, fake_router):
    settings.behavior.compose.keyword_search_top_n = 2
    _seed_large_library(settings, count=5)
    keywords_reply = "ROLE: \nENVIRONMENT: Jira\nRESPONSIBILITIES: \nDOMAIN: \n"
    plan = json.dumps(
        {
            "steps": [
                {"order": 1, "action": "use", "block_id": "block_0", "criteria": None},
                {"order": 2, "action": "use", "block_id": "block_1", "criteria": None},
                {"order": 3, "action": "use", "block_id": "block_2", "criteria": None},
                {"order": 4, "action": "use", "block_id": "block_3", "criteria": None},
            ]
        }
    )
    client = FakeLLMClient(replies=[keywords_reply, plan])
    fake_router(compose_module, client)
    events: list[ProgressEvent] = []

    outcome = compose_module.run_compose(
        "need four projects",
        settings=settings,
        count=4,
        # designated set (5) exceeds max(top_n, required_count)=4, so narrowing runs (not skipped)
        from_block_ids=["block_0", "block_1", "block_2", "block_3", "block_4"],
        dry_run=True,
        on_progress=events.append,
    )

    assert len(outcome.slots) == 4
    warnings = [e for e in events if e.kind == "warning"]
    assert warnings
    assert "designated set" in warnings[0].message


def test_from_block_ids_small_set_skips_narrowing(settings, fake_router):
    _seed_large_library(settings, count=5)
    plan = json.dumps(
        {
            "steps": [
                {"order": 1, "action": "use", "block_id": "block_0", "criteria": None},
                {"order": 2, "action": "use", "block_id": "block_1", "criteria": None},
            ]
        }
    )
    client = FakeLLMClient(replies=[plan])
    fake_router(compose_module, client)
    events: list[ProgressEvent] = []

    outcome = compose_module.run_compose(
        "need two projects",
        settings=settings,
        count=2,
        from_block_ids=["block_0", "block_1"],
        dry_run=True,
        on_progress=events.append,
    )

    assert len(outcome.slots) == 2
    assert client.call_count == 1  # only the planning call -- no keyword-extraction call
    assert any(e.kind == "narrowing_skipped" for e in events)
    assert "Extracting search keywords" not in "\n".join(e.message for e in events)


def test_required_count_alone_triggers_skip_when_it_covers_the_pool(settings, fake_router):
    """Pool (4) exceeds top_n (1) but the still-required count (4) alone makes it fit --
    the skip threshold is max(top_n, required_count), not top_n alone."""
    settings.behavior.compose.keyword_search_top_n = 1
    _seed_large_library(settings, count=4)
    plan = json.dumps(
        {
            "steps": [
                {"order": 1, "action": "use", "block_id": "block_0", "criteria": None},
                {"order": 2, "action": "use", "block_id": "block_1", "criteria": None},
                {"order": 3, "action": "use", "block_id": "block_2", "criteria": None},
                {"order": 4, "action": "use", "block_id": "block_3", "criteria": None},
            ]
        }
    )
    client = FakeLLMClient(replies=[plan])
    fake_router(compose_module, client)
    events: list[ProgressEvent] = []

    outcome = compose_module.run_compose(
        "need four projects", settings=settings, count=4, dry_run=True, on_progress=events.append
    )

    assert len(outcome.slots) == 4
    assert client.call_count == 1  # no keyword-extraction call
    assert any(e.kind == "narrowing_skipped" for e in events)


def test_required_count_alone_insufficient_when_pool_exceeds_it(settings, fake_router):
    """Pool (6) exceeds max(top_n=1, required_count=4)=4 -- narrowing runs (not skipped) and
    then widens+warns exactly as it would without the from_block_ids/skip features."""
    settings.behavior.compose.keyword_search_top_n = 1
    _seed_large_library(settings, count=6)
    keywords_reply = "ROLE: \nENVIRONMENT: Jira\nRESPONSIBILITIES: \nDOMAIN: \n"
    plan = json.dumps(
        {
            "steps": [
                {"order": 1, "action": "use", "block_id": "block_0", "criteria": None},
                {"order": 2, "action": "use", "block_id": "block_1", "criteria": None},
                {"order": 3, "action": "use", "block_id": "block_2", "criteria": None},
                {"order": 4, "action": "use", "block_id": "block_3", "criteria": None},
            ]
        }
    )
    client = FakeLLMClient(replies=[keywords_reply, plan])
    fake_router(compose_module, client)
    events: list[ProgressEvent] = []

    outcome = compose_module.run_compose(
        "need four projects",
        settings=settings,
        count=4,
        restrict_generate=True,
        dry_run=True,
        on_progress=events.append,
    )

    assert len(outcome.slots) == 4
    assert not any(e.kind == "narrowing_skipped" for e in events)
    assert any(e.kind == "warning" for e in events)
