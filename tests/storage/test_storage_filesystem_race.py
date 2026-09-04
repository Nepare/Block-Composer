"""Regression tests for the .naming.lock guard around save_with_dedup: real threads racing
real, separate storage instances against one tmp_path root, proving concurrent saves that
resolve to the same base name no longer clobber each other."""

import threading

from core import naming
from fakes import FakeLLMClient
from models.blocks import Block
from storage.base import Result
from storage.filesystem import FilesystemBlockStorage, FilesystemResultStorage


def _race(fn_a, fn_b):
    """Runs fn_a/fn_b on separate threads, released together via a barrier to maximize
    interleaving, and re-raises any thread exception on the calling thread."""
    barrier = threading.Barrier(2)
    results = {}
    errors = {}

    def _wrap(key, fn):
        def _run():
            try:
                barrier.wait(timeout=10)
                results[key] = fn()
            except BaseException as exc:  # noqa: BLE001 - surfaced on the main thread below
                errors[key] = exc

        return _run

    t_a = threading.Thread(target=_wrap("a", fn_a))
    t_b = threading.Thread(target=_wrap("b", fn_b))
    t_a.start()
    t_b.start()
    t_a.join(timeout=10)
    t_b.join(timeout=10)

    for key, exc in errors.items():
        raise AssertionError(f"racing thread {key!r} raised") from exc

    return results["a"], results["b"]


def test_concurrent_saves_same_name_different_content_both_survive(tmp_path):
    for i in range(20):
        name = f"Widget {i}"
        body_a = f"## {name}\n\nContent A for iteration {i}.\n"
        body_b = f"## {name}\n\nContent B for iteration {i}.\n"

        # two separate instances pointed at the same root -- simulates two processes,
        # not two threads sharing one Python object
        store_a = FilesystemBlockStorage(tmp_path)
        store_b = FilesystemBlockStorage(tmp_path)
        block_a = Block(id="", body=body_a, created_by="dissected")
        block_b = Block(id="", body=body_b, created_by="dissected")

        def _save_a():
            return store_a.save_with_dedup(
                block_a, naming_client=FakeLLMClient(replies=["variant"]), naming_model="m"
            )

        def _save_b():
            return store_b.save_with_dedup(
                block_b, naming_client=FakeLLMClient(replies=["variant"]), naming_model="m"
            )

        result_a, result_b = _race(_save_a, _save_b)
        decision_a, stem_a = result_a
        decision_b, stem_b = result_b

        assert stem_a is not None, f"iteration {i}: thread a lost its save ({decision_a})"
        assert stem_b is not None, f"iteration {i}: thread b lost its save ({decision_b})"
        assert stem_a != stem_b, f"iteration {i}: both threads landed on the same stem"

        base_slug = naming.slugify(name)
        matches = sorted(tmp_path.glob(f"{base_slug}*.md"))
        assert len(matches) == 2, (
            f"iteration {i}: expected 2 files for {base_slug!r}, found {[p.name for p in matches]}"
        )

        assert f"Content A for iteration {i}." in store_a.load(stem_a).body
        assert f"Content B for iteration {i}." in store_a.load(stem_b).body


def test_concurrent_saves_same_explicit_base_get_distinct_numbered_stems(tmp_path):
    store_a = FilesystemBlockStorage(tmp_path)
    store_b = FilesystemBlockStorage(tmp_path)
    block_a = Block(id="", body="## Widget Mut\n\nA.\n", created_by="dissected")
    block_b = Block(id="", body="## Widget Mut\n\nB.\n", created_by="dissected")

    def _save_a():
        return store_a.save_with_dedup(block_a, explicit_base="widget_mut_local")

    def _save_b():
        return store_b.save_with_dedup(block_b, explicit_base="widget_mut_local")

    result_a, result_b = _race(_save_a, _save_b)
    _, stem_a = result_a
    _, stem_b = result_b

    assert {stem_a, stem_b} == {"widget_mut_local", "widget_mut_local_2"}
    assert (tmp_path / "widget_mut_local.md").exists()
    assert (tmp_path / "widget_mut_local_2.md").exists()
    assert "A." in store_a.load(stem_a).body
    assert "B." in store_a.load(stem_b).body


def test_concurrent_result_saves_same_name_different_content_both_survive(tmp_path):
    store_a = FilesystemResultStorage(tmp_path)
    store_b = FilesystemResultStorage(tmp_path)
    result_a = Result(content="## Report\n\nContent A.\n", name="Report")
    result_b = Result(content="## Report\n\nContent B.\n", name="Report")

    def _save_a():
        return store_a.save_with_dedup(
            result_a, naming_client=FakeLLMClient(replies=["variant"]), naming_model="m"
        )

    def _save_b():
        return store_b.save_with_dedup(
            result_b, naming_client=FakeLLMClient(replies=["variant"]), naming_model="m"
        )

    outcome_a, outcome_b = _race(_save_a, _save_b)
    _, stem_a = outcome_a
    _, stem_b = outcome_b

    assert stem_a is not None
    assert stem_b is not None
    assert stem_a != stem_b

    matches = sorted(tmp_path.glob("report*.md"))
    assert len(matches) == 2, f"expected 2 files, found {[p.name for p in matches]}"

    assert "Content A." in store_a.load(stem_a).content
    assert "Content B." in store_a.load(stem_b).content
