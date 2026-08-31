import json
from pathlib import Path

import dissect as dissect_module
import docs_api
from blocks import BlockStore
from fakes import FakeLLMClient

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "greentown_doc_response.json"


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

    store = BlockStore(settings.blocks_path)
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
