from core import naming
from fakes import FakeLLMClient


def test_slugify_basic():
    assert naming.slugify("Police Station") == "police_station"
    assert naming.slugify("  W/o Jail!! ") == "w_o_jail"
    assert naming.slugify("") == "item"


def test_unique_stem_no_collision():
    assert naming.unique_stem("foo", exists=lambda s: False) == "foo"


def test_unique_stem_collision_appends_counter():
    taken = {"foo", "foo_2"}
    assert naming.unique_stem("foo", exists=lambda s: s in taken) == "foo_3"


def test_decide_brand_new_saves_plain_with_no_llm_call():
    client = FakeLLMClient()
    candidate = naming.Candidate(name="Police Station", full_text="## Police Station\nBody")

    decision = naming.decide(
        candidate, existing=[], exists=lambda s: False, naming_client=client, naming_model="m"
    )

    assert decision.action == "save_plain"
    assert decision.stem == "police_station"
    assert client.call_count == 0


def test_decide_exact_duplicate_is_skipped_with_no_llm_call():
    client = FakeLLMClient()
    text = "## Police Station\n\nSame body.\n"
    candidate = naming.Candidate(name="Police Station", full_text=text)
    existing = [("police_station", naming.Candidate(name="Police Station", full_text=text))]

    decision = naming.decide(
        candidate, existing, exists=lambda s: True, naming_client=client, naming_model="m"
    )

    assert decision.action == "skip_duplicate"
    assert decision.duplicate_of == "police_station"
    assert client.call_count == 0


def test_decide_exact_duplicate_ignores_incidental_whitespace_case():
    client = FakeLLMClient()
    candidate = naming.Candidate(name="  police station  ", full_text="##  Police  Station\n\nBODY.\n")
    existing = [("police_station", naming.Candidate(name="Police Station", full_text="## Police Station\n\nbody.\n"))]

    decision = naming.decide(
        candidate, existing, exists=lambda s: True, naming_client=client, naming_model="m"
    )

    assert decision.action == "skip_duplicate"
    assert client.call_count == 0


def test_decide_partial_match_asks_cheap_model_for_a_bracket_label():
    client = FakeLLMClient(replies=["jail"])
    candidate = naming.Candidate(name="Police Station", full_text="## Police Station\n\nHas a jail.\n")
    existing = [
        ("police_station", naming.Candidate(name="Police Station", full_text="## Police Station\n\nNo jail.\n"))
    ]

    decision = naming.decide(
        candidate,
        existing,
        exists=lambda s: s == "police_station",
        naming_client=client,
        naming_model="m",
    )

    assert decision.action == "save_variant"
    assert decision.stem == "police_station_mut_jail"
    assert decision.label == "jail"
    assert decision.called_llm is True
    assert client.call_count == 1


def test_decide_variant_stem_collision_appends_counter():
    client = FakeLLMClient(replies=["jail"])
    candidate = naming.Candidate(name="Police Station", full_text="new content")
    existing = [("police_station", naming.Candidate(name="Police Station", full_text="old content"))]
    taken = {"police_station_mut_jail"}

    decision = naming.decide(
        candidate,
        existing,
        exists=lambda s: s in taken,
        naming_client=client,
        naming_model="m",
    )

    assert decision.stem == "police_station_mut_jail_2"


def test_decide_checks_every_sibling_for_an_exact_match_not_just_the_first():
    client = FakeLLMClient()
    candidate = naming.Candidate(name="Police Station", full_text="## Police Station\n\nHas a jail.\n")
    existing = [
        ("police_station", naming.Candidate(name="Police Station", full_text="## Police Station\n\nNo jail.\n")),
        (
            "police_station_mut_jail",
            naming.Candidate(name="Police Station", full_text="## Police Station\n\nHas a jail.\n"),
        ),
    ]

    decision = naming.decide(
        candidate, existing, exists=lambda s: True, naming_client=client, naming_model="m"
    )

    assert decision.action == "skip_duplicate"
    assert decision.duplicate_of == "police_station_mut_jail"
    assert client.call_count == 0


def test_propose_label_strips_brackets_and_whitespace():
    client = FakeLLMClient(replies=["  [sheriff]  "])
    a = naming.Candidate(name="x", full_text="a")
    b = naming.Candidate(name="x", full_text="b")
    assert naming._propose_label(a, b, client, "m") == "sheriff"


def test_propose_label_falls_back_when_model_replies_empty():
    client = FakeLLMClient(replies=["   "])
    a = naming.Candidate(name="x", full_text="a")
    b = naming.Candidate(name="x", full_text="b")
    assert naming._propose_label(a, b, client, "m") == "variant"


def test_propose_label_includes_constraints_in_the_system_prompt():
    client = FakeLLMClient(replies=["jail"])
    a = naming.Candidate(name="x", full_text="a")
    b = naming.Candidate(name="x", full_text="b")

    naming._propose_label(a, b, client, "m", constraints="Never use single letters.")

    system_message = client.calls[0]["messages"][0]["content"]
    assert "Never use single letters." in system_message


def test_decide_passes_constraints_through_to_propose_label():
    client = FakeLLMClient(replies=["jail"])
    candidate = naming.Candidate(name="X", full_text="## X\n\nnew")
    existing = [("x", naming.Candidate(name="X", full_text="## X\n\nold"))]

    naming.decide(
        candidate,
        existing,
        exists=lambda s: False,
        naming_client=client,
        naming_model="m",
        constraints="Never use single letters.",
    )

    system_message = client.calls[0]["messages"][0]["content"]
    assert "Never use single letters." in system_message
