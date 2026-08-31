from llm.prompts import compose_prompt, generate_prompt, mutate_prompt, result_name_prompt


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
    messages = compose_prompt("a request", [], "", constraints="Prefer mutate over generate.")
    assert "Prefer mutate over generate." in messages[0]["content"]


def test_result_name_prompt_appends_constraints_to_system_message():
    messages = result_name_prompt("some content", constraints="No superlatives.")
    assert "No superlatives." in messages[0]["content"]
