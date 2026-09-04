"""Regression tests proving SqliteBlockStorage/SqliteResultStorage's save_with_dedup()
BEGIN IMMEDIATE transaction genuinely serializes concurrent writers sharing one sqlite
file -- real threads, real separate connections, no mocks."""

import threading

from fakes import FakeLLMClient
from models.blocks import Block
from storage.base import Result
from storage.sqlite import SqliteBlockStorage, SqliteResultStorage


def _race(fn_a, fn_b):
    """Runs fn_a and fn_b on separate threads, released at nearly the same instant via
    a barrier, and re-raises any exception raised inside either thread."""
    barrier = threading.Barrier(2)
    errors = []
    results = {}

    def _wrap(key, fn):
        try:
            barrier.wait(timeout=15)
            results[key] = fn()
        except Exception as exc:  # noqa: BLE001 -- surfaced to the main thread below
            errors.append(exc)

    t_a = threading.Thread(target=_wrap, args=("a", fn_a))
    t_b = threading.Thread(target=_wrap, args=("b", fn_b))
    t_a.start()
    t_b.start()
    t_a.join(timeout=20)
    t_b.join(timeout=20)

    if errors:
        raise errors[0]
    return results["a"], results["b"]


def test_concurrent_save_with_dedup_same_name_different_content_loses_no_write(tmp_path):
    db_path = tmp_path / "cvdocs.db"

    block_a = Block(id="", body="## Widget\n\nFrom A.\n", created_by="dissected")
    block_b = Block(id="", body="## Widget\n\nFrom B.\n", created_by="dissected")
    fake_a = FakeLLMClient(replies=["variant"])
    fake_b = FakeLLMClient(replies=["variant"])

    def _save_a():
        # each store's own connection must be created on the thread that uses it --
        # this is what actually simulates two separate OS processes sharing one file
        store = SqliteBlockStorage(db_path)
        return store.save_with_dedup(block_a, naming_client=fake_a, naming_model="m")

    def _save_b():
        store = SqliteBlockStorage(db_path)
        return store.save_with_dedup(block_b, naming_client=fake_b, naming_model="m")

    (decision_a, stem_a), (decision_b, stem_b) = _race(_save_a, _save_b)

    store_a = SqliteBlockStorage(db_path)
    siblings = store_a.siblings("widget")
    assert {b.id for b in siblings} == {stem_a, stem_b}
    assert stem_a != stem_b
    assert len(siblings) == 2

    actions = {decision_a.action, decision_b.action}
    assert actions == {"save_plain", "save_variant"}

    bodies = {store_a.load(stem_a).body, store_a.load(stem_b).body}
    assert bodies == {"## Widget\n\nFrom A.\n", "## Widget\n\nFrom B.\n"}


def test_concurrent_save_with_dedup_repeated_races_lose_no_writes(tmp_path):
    db_path = tmp_path / "cvdocs.db"

    for i in range(20):
        base = f"widget-{i}"
        base_slug = base.replace("-", "_")
        block_a = Block(id="", body=f"## {base}\n\nFrom A {i}.\n", created_by="dissected")
        block_b = Block(id="", body=f"## {base}\n\nFrom B {i}.\n", created_by="dissected")
        fake_a = FakeLLMClient(replies=["variant"])
        fake_b = FakeLLMClient(replies=["variant"])

        def _save_a(ba=block_a, fa=fake_a):
            store = SqliteBlockStorage(db_path)
            return store.save_with_dedup(ba, naming_client=fa, naming_model="m")

        def _save_b(bb=block_b, fb=fake_b):
            store = SqliteBlockStorage(db_path)
            return store.save_with_dedup(bb, naming_client=fb, naming_model="m")

        (decision_a, stem_a), (decision_b, stem_b) = _race(_save_a, _save_b)

        store_a = SqliteBlockStorage(db_path)
        siblings = store_a.siblings(base_slug)
        assert len(siblings) == 2, f"iteration {i}: lost a write, siblings={[s.id for s in siblings]}"
        assert {b.id for b in siblings} == {stem_a, stem_b}
        assert stem_a != stem_b
        assert {decision_a.action, decision_b.action} == {"save_plain", "save_variant"}

        bodies = {store_a.load(stem_a).body, store_a.load(stem_b).body}
        assert bodies == {f"## {base}\n\nFrom A {i}.\n", f"## {base}\n\nFrom B {i}.\n"}


def test_concurrent_save_with_dedup_same_explicit_base_numbers_both(tmp_path):
    db_path = tmp_path / "cvdocs.db"

    block_a = Block(id="", body="## Widget Mut Local\n\nFrom A.\n", created_by="dissected")
    block_b = Block(id="", body="## Widget Mut Local\n\nFrom B.\n", created_by="dissected")

    def _save_a():
        store = SqliteBlockStorage(db_path)
        return store.save_with_dedup(block_a, explicit_base="widget_mut_local")

    def _save_b():
        store = SqliteBlockStorage(db_path)
        return store.save_with_dedup(block_b, explicit_base="widget_mut_local")

    (decision_a, stem_a), (decision_b, stem_b) = _race(_save_a, _save_b)

    assert {stem_a, stem_b} == {"widget_mut_local", "widget_mut_local_2"}
    assert {decision_a.action, decision_b.action} == {"save_plain", "save_variant"}

    store_a = SqliteBlockStorage(db_path)
    assert store_a.exists("widget_mut_local")
    assert store_a.exists("widget_mut_local_2")
    bodies = {store_a.load("widget_mut_local").body, store_a.load("widget_mut_local_2").body}
    assert bodies == {"## Widget Mut Local\n\nFrom A.\n", "## Widget Mut Local\n\nFrom B.\n"}


def test_concurrent_result_save_with_dedup_same_name_different_content_loses_no_write(tmp_path):
    db_path = tmp_path / "cvdocs.db"

    result_a = Result(content="## School\n\nFrom A.\n", name="School Overview")
    result_b = Result(content="## School\n\nFrom B.\n", name="School Overview")
    fake_a = FakeLLMClient(replies=["variant"])
    fake_b = FakeLLMClient(replies=["variant"])

    def _save_a():
        store = SqliteResultStorage(db_path)
        return store.save_with_dedup(result_a, naming_client=fake_a, naming_model="m")

    def _save_b():
        store = SqliteResultStorage(db_path)
        return store.save_with_dedup(result_b, naming_client=fake_b, naming_model="m")

    (decision_a, stem_a), (decision_b, stem_b) = _race(_save_a, _save_b)

    store_a = SqliteResultStorage(db_path)
    siblings = store_a.siblings("school_overview")
    assert {r.id for r in siblings} == {stem_a, stem_b}
    assert stem_a != stem_b
    assert len(siblings) == 2
    assert {decision_a.action, decision_b.action} == {"save_plain", "save_variant"}

    contents = {store_a.load(stem_a).content, store_a.load(stem_b).content}
    assert contents == {"## School\n\nFrom A.\n", "## School\n\nFrom B.\n"}
