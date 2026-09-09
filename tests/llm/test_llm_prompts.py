from llm.prompts import (
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
