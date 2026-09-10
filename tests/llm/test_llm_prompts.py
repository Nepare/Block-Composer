from llm.prompts import (
    _compose_system,
    compose_prompt,
    generate_prompt,
    keyword_extraction_prompt,
    mutate_prompt,
    result_name_prompt,
    target_count_prompt,
)


def test_generate_prompt_omits_constraints_section_when_empty():
    messages = generate_prompt("a thing", [], constraints="")
    assert "User constraints" not in messages[0]["content"]


def test_generate_prompt_appends_constraints_to_system_message():
    messages = generate_prompt("a thing", [], constraints="Don't invent dates.")
    system = messages[0]["content"]
    assert "User constraints" in system
    assert "Don't invent dates." in system


def test_mutate_prompt_appends_constraints_to_system_message():
    messages = mutate_prompt("## X\n\nbody", "change it", constraints="Keep the tone formal.")
    assert "Keep the tone formal." in messages[0]["content"]


def test_compose_prompt_appends_constraints_to_system_message():
    messages = compose_prompt("a request", [], constraints="Prefer mutate over generate.")
    assert "Prefer mutate over generate." in messages[0]["content"]


def test_compose_prompt_warns_against_reusing_a_project_by_tags():
    for allow_mutate in (True, False):
        for allow_generate in (True, False):
            messages = compose_prompt(
                "a request", [], allow_mutate=allow_mutate, allow_generate=allow_generate
            )
            system = messages[0]["content"]
            assert "same `tags` list" in system
            assert "claim at most one block from that group" in system


def test_compose_system_includes_detailed_criteria_instruction_block():
    system = _compose_system(True, True)
    assert "identify which specific part" in system
    assert "MUST carry that specific detail forward" in system
    assert "Never reference or pull in another piece's content" in system


def test_compose_system_includes_relevant_excerpts_on_mutate_and_generate_examples_only():
    system = _compose_system(True, True)
    assert '"relevant_excerpts"' in system
    use_example, mutate_example, generate_example = (
        line for line in system.split("\n") if '"action": "use"' in line
        or '"action": "mutate"' in line
        or '"action": "generate"' in line
    )
    assert '"relevant_excerpts"' not in use_example
    assert '"relevant_excerpts"' in mutate_example
    assert '"relevant_excerpts"' in generate_example


def test_mutate_prompt_relevant_excerpts_none_or_empty_are_byte_identical():
    baseline = mutate_prompt("## X\n\nbody", "change it")
    assert mutate_prompt("## X\n\nbody", "change it", relevant_excerpts=None) == baseline
    assert mutate_prompt("## X\n\nbody", "change it", relevant_excerpts=[]) == baseline


def test_mutate_prompt_appends_one_labeled_excerpts_block_to_final_user_message():
    messages = mutate_prompt("## X\n\nbody", "change it", relevant_excerpts=["quote one", "quote two"])
    assert "quote one" not in messages[0]["content"]
    assert "quote two" not in messages[0]["content"]
    final_content = messages[-1]["content"]
    assert final_content.count("Grounding") == 1
    assert "quote one" in final_content
    assert "quote two" in final_content


def test_generate_prompt_relevant_excerpts_none_or_empty_are_byte_identical():
    baseline = generate_prompt("a thing", [])
    assert generate_prompt("a thing", [], relevant_excerpts=None) == baseline
    assert generate_prompt("a thing", [], relevant_excerpts=[]) == baseline


def test_generate_prompt_appends_one_labeled_excerpts_block_to_final_user_message():
    messages = generate_prompt("a thing", ["example body"], relevant_excerpts=["quote one"])
    assert "quote one" not in messages[0]["content"]
    final_content = messages[-1]["content"]
    assert final_content.count("Grounding") == 1
    assert "quote one" in final_content


def test_result_name_prompt_appends_constraints_to_system_message():
    messages = result_name_prompt("some content", constraints="No superlatives.")
    assert "No superlatives." in messages[0]["content"]


def test_keyword_extraction_prompt_appends_constraints_to_system_message():
    messages = keyword_extraction_prompt("a request", constraints="Never invent a keyword.")
    assert "Never invent a keyword." in messages[0]["content"]


def test_target_count_prompt_takes_no_constraints_and_wraps_the_request_in_xml():
    messages = target_count_prompt("give me 3 projects")
    assert "<task>" in messages[0]["content"]
    assert messages[1]["content"] == "<request>give me 3 projects</request>"
