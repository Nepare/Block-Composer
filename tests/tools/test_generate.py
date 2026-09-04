import pytest

from tools import generate as generate_module
from models.blocks import Block
from core.errors import BlockValidationError, InputError, OperationCancelled
from fakes import FakeBlockStorage, FakeLLMClient
from core.progress import ProgressEvent
from storage.filesystem import FilesystemBlockStorage


def test_run_generate_saves_valid_reply(settings, fake_router):
    client = FakeLLMClient(replies=["## Sheriff Outpost\n\nA frontier outpost.\n\n**Role:** nobody\n"])
    fake_router(generate_module, client)

    block, decision, stem = generate_module.run_generate("a sheriff outpost", settings=settings)

    assert decision.action == "save_plain"
    assert stem == "sheriff_outpost"
    assert block.created_by == "generated"
    assert block.generation_criteria == "a sheriff outpost"
    assert client.call_count == 1


def test_run_generate_retries_once_on_invalid_reply(settings, fake_router):
    client = FakeLLMClient(
        replies=[
            "no heading, no fields",
            "## Sheriff Outpost\n\nA frontier outpost.\n\n**Role:** nobody\n",
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
    client = FakeLLMClient(replies=["## Sheriff Outpost\n\nA frontier outpost.\n\n**Role:** nobody\n"])
    fake_router(generate_module, client)

    generate_module.run_generate("a sheriff outpost", settings=settings)

    sent = client.calls[0]["messages"]
    combined = " ".join(m["content"] for m in sent)
    assert "Sample Project One" in combined or "Sample Project Two" in combined


def test_run_generate_prefers_explicit_style_from_over_library(settings, fake_router):
    store = FilesystemBlockStorage(settings.blocks_path)
    store.save(Block(id="", body="## Unrelated\n\nNoise.\n"), filename_stem="unrelated")
    exemplar = Block(id="exemplar", body="## Custom Exemplar\n\nUse my shape.\n")

    client = FakeLLMClient(replies=["## Sheriff Outpost\n\nA frontier outpost.\n\n**Role:** nobody\n"])
    fake_router(generate_module, client)

    generate_module.run_generate("a sheriff outpost", settings=settings, style_from=[exemplar])

    combined = " ".join(m["content"] for m in client.calls[0]["messages"])
    assert "Custom Exemplar" in combined
    assert "Unrelated" not in combined


def test_run_generate_dedups_against_existing_library(settings, fake_router):
    store = FilesystemBlockStorage(settings.blocks_path)
    store.save(Block(id="", body="## Sheriff Outpost\n\nAlready here.\n"), filename_stem="sheriff_outpost")

    client = FakeLLMClient(
        replies=[
            "## Sheriff Outpost\n\nDifferent content this time.\n\n**Role:** someone else\n",
            "variant",
        ]
    )
    fake_router(generate_module, client)

    _block, decision, stem = generate_module.run_generate("a sheriff outpost", settings=settings)

    assert decision.action == "save_variant"
    assert stem == "sheriff_outpost_mut_variant"


def test_run_generate_fires_progress_events_around_the_call_and_naming(settings, fake_router):
    client = FakeLLMClient(replies=["## Sheriff Outpost\n\nA frontier outpost.\n\n**Role:** nobody\n"])
    fake_router(generate_module, client)

    events: list[ProgressEvent] = []
    generate_module.run_generate("a sheriff outpost", settings=settings, on_progress=events.append)

    kinds = [e.kind for e in events]
    assert kinds[0] == "generate_start"
    assert "naming" in kinds
    assert kinds[-1] == "generate_done"


def test_run_generate_is_silent_by_default_with_no_on_progress(settings, fake_router):
    client = FakeLLMClient(replies=["## Sheriff Outpost\n\nA frontier outpost.\n\n**Role:** nobody\n"])
    fake_router(generate_module, client)

    # must not raise just because no on_progress was given
    generate_module.run_generate("a sheriff outpost", settings=settings)


def test_run_generate_raises_operation_cancelled_before_the_retry(settings, fake_router):
    client = FakeLLMClient(
        replies=["no heading, no fields", "## Sheriff Outpost\n\nA frontier outpost.\n\n**Role:** nobody\n"]
    )
    fake_router(generate_module, client)

    with pytest.raises(OperationCancelled):
        generate_module.run_generate("a sheriff outpost", settings=settings, cancel_check=lambda: True)
    # only the first (failed) attempt was made -- the retry never fires once cancelled
    assert client.call_count == 1


def test_run_generate_works_against_a_fake_block_storage(settings, fake_router, fake_storage):
    """Proves the BlockStorage Protocol is complete: run_generate works unmodified
    against an in-memory fake, not just FilesystemBlockStorage."""
    from fakes import FakeBlockStorage

    fake_block_store = FakeBlockStorage()
    fake_storage(generate_module, block_store=fake_block_store)
    client = FakeLLMClient(replies=["## Sheriff Outpost\n\nA frontier outpost.\n\n**Role:** nobody\n"])
    fake_router(generate_module, client)

    block, decision, stem = generate_module.run_generate("a sheriff outpost", settings=settings)

    assert decision.action == "save_plain"
    assert stem == "sheriff_outpost"
    assert fake_block_store.load("sheriff_outpost") is block


def test_run_generate_includes_constraints_file_in_the_system_prompt(settings, fake_router, tmp_path):
    constraints_file = tmp_path / "GENERATE_CONSTRAINTS.md"
    constraints_file.write_text("Don't invent specific dates.", encoding="utf-8")
    settings.path.constraints.generate = str(constraints_file)

    client = FakeLLMClient(replies=["## Thing\n\nBody.\n\n**Role:** someone\n"])
    fake_router(generate_module, client)

    generate_module.run_generate("a thing", settings=settings)

    system_message = client.calls[0]["messages"][0]["content"]
    assert "Don't invent specific dates." in system_message


def test_run_generate_with_explicit_name_saves_under_that_stem_and_skips_naming_llm(
    settings, fake_router, fake_storage
):
    fake_block_store = FakeBlockStorage()
    fake_storage(generate_module, block_store=fake_block_store)
    # only one reply scripted: if the naming LLM were consulted (e.g. for a variant
    # label), the fake would raise from running out of replies -- proving it never fires
    client = FakeLLMClient(replies=["## Sheriff Outpost\n\nA frontier outpost.\n\n**Role:** nobody\n"])
    fake_router(generate_module, client)

    block, decision, stem = generate_module.run_generate("a widget", settings=settings, name="Widget")

    assert stem == "widget"
    assert decision.action == "save_plain"
    assert fake_block_store.load("widget") is block
    assert client.call_count == 1


def test_run_generate_with_explicit_name_numbers_on_collision(settings, fake_router, fake_storage):
    fake_block_store = FakeBlockStorage()
    fake_block_store.save(Block(id="", body="## Widget\n\nExisting.\n"), filename_stem="widget")
    fake_storage(generate_module, block_store=fake_block_store)
    client = FakeLLMClient(replies=["## Widget\n\nSomething new.\n\n**Role:** someone\n"])
    fake_router(generate_module, client)

    _block, decision, stem = generate_module.run_generate("a widget", settings=settings, name="Widget")

    assert stem == "widget_2"
    assert decision.action == "save_variant"


def test_run_generate_with_degenerate_name_raises_before_any_llm_call(settings, fake_router):
    client = FakeLLMClient(replies=["## Widget\n\nBody.\n\n**Role:** someone\n"])
    fake_router(generate_module, client)

    with pytest.raises(InputError):
        generate_module.run_generate("a widget", settings=settings, name="!!!")

    assert client.call_count == 0
