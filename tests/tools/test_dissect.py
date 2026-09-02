import json
from pathlib import Path

from tools import dissect as dissect_module
from tools import docs_api
from fakes import FakeLLMClient
from core.progress import ProgressEvent
from storage.filesystem import FilesystemBlockStorage

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "greentown_doc_response.json"


def _load_fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_run_dissect_extracts_both_blocks_with_zero_llm_calls(settings, fake_router, monkeypatch):
    document = _load_fixture()
    monkeypatch.setattr(docs_api, "get_document", lambda doc_id: document)

    client = FakeLLMClient()  # no replies queued -- must not be called at all
    fake_router(dissect_module, client)

    result = dissect_module.run_dissect(
        "https://docs.google.com/document/d/FAKEID/edit", settings=settings
    )

    assert len(result.saved) == 2
    assert {b.name for b, _ in result.saved} == {"Police Station", "Lumber"}
    assert result.skipped_duplicates == []
    assert result.variants == []
    assert client.call_count == 0

    store = FilesystemBlockStorage(settings.blocks_path)
    police = store.load("police_station")
    assert "**Environment:** 5 wood, 2 iron, 10 gold." in police.body
    assert police.body.count("**Environment:**") == 1
    assert police.source.startswith("FAKEID") or "FAKEID" in police.source


def test_run_dissect_second_pass_over_the_same_doc_is_all_duplicates(settings, fake_router, monkeypatch):
    document = _load_fixture()
    monkeypatch.setattr(docs_api, "get_document", lambda doc_id: document)
    fake_router(dissect_module, FakeLLMClient())

    dissect_module.run_dissect("doc1", settings=settings)
    result2 = dissect_module.run_dissect("doc1", settings=settings)

    assert result2.saved == []
    assert len(result2.skipped_duplicates) == 2


def test_run_dissect_fires_one_progress_event_per_row(settings, fake_router, monkeypatch):
    document = _load_fixture()
    monkeypatch.setattr(docs_api, "get_document", lambda doc_id: document)
    fake_router(dissect_module, FakeLLMClient())

    events: list[ProgressEvent] = []
    dissect_module.run_dissect(
        "https://docs.google.com/document/d/FAKEID/edit", settings=settings, on_progress=events.append
    )

    row_events = [e for e in events if e.kind == "dissect_row"]
    assert len(row_events) == 2
    assert row_events[0].step == 1 and row_events[0].total == 2
    assert row_events[1].step == 2 and row_events[1].total == 2


def test_run_dissect_resolves_url_to_doc_id(settings, fake_router, monkeypatch):
    document = _load_fixture()
    captured = {}

    def fake_get_document(doc_id):
        captured["doc_id"] = doc_id
        return document

    monkeypatch.setattr(docs_api, "get_document", fake_get_document)
    fake_router(dissect_module, FakeLLMClient())

    dissect_module.run_dissect(
        "https://docs.google.com/document/d/ABC123XYZ/edit?usp=sharing", settings=settings
    )

    assert captured["doc_id"] == "ABC123XYZ"
