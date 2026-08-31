import pytest

import generate as generate_module
from blocks import Block, BlockStore
from errors import BlockValidationError
from fakes import FakeLLMClient


def test_run_generate_saves_valid_reply(settings, fake_router):
    client = FakeLLMClient(replies=["## Sheriff Outpost\n\nA frontier outpost.\n\n**Author:** nobody\n"])
    fake_router(generate_module, client)

    block, decision, path = generate_module.run_generate("a sheriff outpost", settings=settings)

    assert decision.action == "save_plain"
    assert path.name == "sheriff_outpost.md"
    assert block.created_by == "generated"
    assert block.generation_criteria == "a sheriff outpost"
    assert client.call_count == 1


def test_run_generate_retries_once_on_invalid_reply(settings, fake_router):
    client = FakeLLMClient(
        replies=[
            "no heading, no fields",
            "## Sheriff Outpost\n\nA frontier outpost.\n\n**Author:** nobody\n",
        ]
    )
    fake_router(generate_module, client)

    _block, decision, _path = generate_module.run_generate("a sheriff outpost", settings=settings)

    assert decision.action == "save_plain"
    assert client.call_count == 2


def test_run_generate_raises_after_second_invalid_reply(settings, fake_router):
    client = FakeLLMClient(replies=["still no heading", "still no heading"])
    fake_router(generate_module, client)

    with pytest.raises(BlockValidationError):
        generate_module.run_generate("a sheriff outpost", settings=settings)


def test_run_generate_falls_back_to_shipped_samples_when_library_is_empty(settings, fake_router):
    client = FakeLLMClient(replies=["## Sheriff Outpost\n\nA frontier outpost.\n\n**Author:** nobody\n"])
    fake_router(generate_module, client)

    generate_module.run_generate("a sheriff outpost", settings=settings)

    sent = client.calls[0]["messages"]
    combined = " ".join(m["content"] for m in sent)
    assert "Sample Project One" in combined or "Sample Project Two" in combined


def test_run_generate_prefers_explicit_style_from_over_library(settings, fake_router):
    store = BlockStore(settings.blocks_path)
    store.save(Block(id="", body="## Unrelated\n\nNoise.\n"), filename_stem="unrelated")
    exemplar = Block(id="exemplar", body="## Custom Exemplar\n\nUse my shape.\n")

    client = FakeLLMClient(replies=["## Sheriff Outpost\n\nA frontier outpost.\n\n**Author:** nobody\n"])
    fake_router(generate_module, client)

    generate_module.run_generate("a sheriff outpost", settings=settings, style_from=[exemplar])

    combined = " ".join(m["content"] for m in client.calls[0]["messages"])
    assert "Custom Exemplar" in combined
    assert "Unrelated" not in combined


def test_run_generate_dedups_against_existing_library(settings, fake_router):
    store = BlockStore(settings.blocks_path)
    store.save(Block(id="", body="## Sheriff Outpost\n\nAlready here.\n"), filename_stem="sheriff_outpost")

    client = FakeLLMClient(
        replies=[
            "## Sheriff Outpost\n\nDifferent content this time.\n\n**Author:** someone else\n",
            "variant",
        ]
    )
    fake_router(generate_module, client)

    _block, decision, path = generate_module.run_generate("a sheriff outpost", settings=settings)

    assert decision.action == "save_variant"
    assert path.name == "sheriff_outpost_mut_variant.md"


def test_run_generate_includes_constraints_file_in_the_system_prompt(settings, fake_router, tmp_path):
    constraints_file = tmp_path / "GENERATE_CONSTRAINTS.md"
    constraints_file.write_text("Don't invent specific dates.", encoding="utf-8")
    settings.constraints.generate = str(constraints_file)

    client = FakeLLMClient(replies=["## Thing\n\nBody.\n\n**Author:** someone\n"])
    fake_router(generate_module, client)

    generate_module.run_generate("a thing", settings=settings)

    system_message = client.calls[0]["messages"][0]["content"]
    assert "Don't invent specific dates." in system_message
