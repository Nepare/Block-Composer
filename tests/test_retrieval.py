from blocks import Block
from fakes import FakeLLMClient
from retrieval import CategorizedKeywords, extract_retrieval_signals, rank_blocks, score_block


def test_extract_keywords_parses_all_four_categories():
    reply = (
        "ROLE: veterinary technician\n"
        "ENVIRONMENT: Jira, autoclave\n"
        "RESPONSIBILITIES: surgery prep, inventory management\n"
        "DOMAIN: veterinary, animal care"
    )
    client = FakeLLMClient(replies=[reply])

    signals = extract_retrieval_signals("need a vet tech project", client, "m")

    assert signals.keywords.role == ["veterinary technician"]
    assert signals.keywords.environment == ["Jira", "autoclave"]
    assert signals.keywords.responsibilities == ["surgery prep", "inventory management"]
    assert signals.keywords.domain == ["veterinary", "animal care"]
    assert signals.requested_count is None
    assert client.call_count == 1


def test_extract_keywords_missing_category_line_yields_empty_list():
    reply = "ROLE: engineer\nENVIRONMENT: \nRESPONSIBILITIES: shipped features\nDOMAIN: \n"
    client = FakeLLMClient(replies=[reply])

    signals = extract_retrieval_signals("x", client, "m")

    assert signals.keywords.role == ["engineer"]
    assert signals.keywords.environment == []
    assert signals.keywords.domain == []


def test_extract_keywords_unparseable_reply_yields_all_empty_without_raising():
    client = FakeLLMClient(replies=["I cannot help with that request."])

    signals = extract_retrieval_signals("x", client, "m")

    assert signals.keywords.is_empty()
    assert signals.requested_count is None


def test_extract_keywords_swallows_client_exceptions():
    class BrokenClient:
        def chat(self, *a, **kw):
            raise RuntimeError("network down")

    signals = extract_retrieval_signals("x", BrokenClient(), "m")

    assert signals.keywords.is_empty()
    assert signals.requested_count is None


def test_score_block_weights_environment_and_role_higher():
    keywords = CategorizedKeywords(role=["engineer"], responsibilities=["shipped features"])
    block = Block(id="x", body="## Engineer Project\n\nDid stuff.\n\n**Responsibilities:**\n- shipped features\n")

    scored = score_block(block, keywords)

    assert scored.score == 1.5 + 1.0  # role (1.5) + responsibilities (1.0)
    assert scored.matched["role"] == ["engineer"]
    assert scored.matched["responsibilities"] == ["shipped features"]


def test_score_block_zero_when_nothing_matches():
    keywords = CategorizedKeywords(role=["veterinarian"])
    block = Block(id="x", body="## Something Else\n\nUnrelated.\n")

    scored = score_block(block, keywords)

    assert scored.score == 0.0
    assert scored.matched == {}


def test_score_block_domain_also_checks_tags():
    keywords = CategorizedKeywords(domain=["finance"])
    block = Block(id="x", body="## Generic Title\n\nGeneric description.\n", tags=["finance"])

    scored = score_block(block, keywords)

    assert scored.matched["domain"] == ["finance"]


def test_rank_blocks_puts_highest_scoring_first():
    keywords = CategorizedKeywords(environment=["Jira"])
    strong = Block(id="strong", body="## A\n\n**Environment:** Jira\n")
    weak = Block(id="weak", body="## B\n\nNothing relevant.\n")

    ranked = rank_blocks([weak, strong], keywords, top_n=5)

    assert ranked[0].id == "strong"


def test_rank_blocks_truncates_matched_blocks_to_top_n():
    keywords = CategorizedKeywords(environment=["Jira"])
    # all 10 blocks match equally -- nothing left over for the unmatched reserve
    blocks = [Block(id=f"b{i}", body=f"## B{i}\n\n**Environment:** Jira\n") for i in range(10)]

    ranked = rank_blocks(blocks, keywords, top_n=3)

    assert len(ranked) == 3


def test_rank_blocks_includes_a_fixed_reserve_of_unmatched_blocks():
    keywords = CategorizedKeywords(environment=["Jira"])
    matched = Block(id="matched", body="## A\n\n**Environment:** Jira\n")
    unmatched = [Block(id=f"u{i}", body=f"## U{i}\n\nNo overlap.\n") for i in range(10)]

    ranked = rank_blocks([matched] + unmatched, keywords, top_n=6)

    ranked_ids = [b.id for b in ranked]
    assert "matched" in ranked_ids
    unmatched_included = [i for i in ranked_ids if i.startswith("u")]
    assert len(unmatched_included) == 2  # the fixed reserve, plenty of unmatched to draw from


def test_rank_blocks_reserve_is_fixed_regardless_of_a_small_top_n():
    # a small request-driven top_n (e.g. 2) must not shrink the reserve to 0 -- that was
    # the exact bug with the old top_n // 3 formula
    keywords = CategorizedKeywords(environment=["Jira"])
    matched = Block(id="matched", body="## A\n\n**Environment:** Jira\n")
    unmatched = [Block(id=f"u{i}", body=f"## U{i}\n\nNo overlap.\n") for i in range(10)]

    ranked = rank_blocks([matched] + unmatched, keywords, top_n=2)

    unmatched_included = [b.id for b in ranked if b.id.startswith("u")]
    assert len(unmatched_included) == 2


def test_rank_blocks_reserve_is_capped_by_available_unmatched_blocks():
    keywords = CategorizedKeywords(environment=["Jira"])
    matched = Block(id="matched", body="## A\n\n**Environment:** Jira\n")
    only_one_unmatched = [Block(id="u0", body="## U0\n\nNo overlap.\n")]

    ranked = rank_blocks([matched] + only_one_unmatched, keywords, top_n=6)

    assert len(ranked) == 2  # matched + the single available unmatched block, not padded to 2


def test_rank_blocks_with_empty_keywords_returns_only_the_reserve():
    keywords = CategorizedKeywords()
    blocks = [Block(id=f"b{i}", body=f"## B{i}\n\nSomething.\n") for i in range(5)]

    ranked = rank_blocks(blocks, keywords, top_n=6)

    # nothing can score > 0 against empty keywords -- everything is "unmatched"
    assert len(ranked) == 2


def test_extract_keywords_truncates_to_max_per_category_even_if_model_returns_more():
    reply = "ROLE: a, b, c, d, e\nENVIRONMENT: \nRESPONSIBILITIES: \nDOMAIN: \n"
    client = FakeLLMClient(replies=[reply])

    signals = extract_retrieval_signals("x", client, "m", max_per_category=2)

    assert signals.keywords.role == ["a", "b"]


def test_extract_keywords_passes_configured_bounds_into_the_prompt():
    client = FakeLLMClient(replies=["ROLE: \nENVIRONMENT: \nRESPONSIBILITIES: \nDOMAIN: \n"])

    extract_retrieval_signals("x", client, "m", min_per_category=2, max_per_category=6)

    system_message = client.calls[0]["messages"][0]["content"]
    assert "2-6" in system_message


def test_extract_signals_parses_a_well_formed_project_count():
    reply = "ROLE: \nENVIRONMENT: \nRESPONSIBILITIES: \nDOMAIN: \nPROJECT_COUNT: 3\n"
    client = FakeLLMClient(replies=[reply])

    signals = extract_retrieval_signals("give me 3 projects", client, "m")

    assert signals.requested_count == 3


def test_extract_signals_missing_project_count_line_is_none():
    reply = "ROLE: engineer\nENVIRONMENT: \nRESPONSIBILITIES: \nDOMAIN: \n"
    client = FakeLLMClient(replies=[reply])

    signals = extract_retrieval_signals("x", client, "m")

    assert signals.requested_count is None


def test_extract_signals_blank_project_count_is_none():
    reply = "ROLE: \nENVIRONMENT: \nRESPONSIBILITIES: \nDOMAIN: \nPROJECT_COUNT: \n"
    client = FakeLLMClient(replies=[reply])

    signals = extract_retrieval_signals("x", client, "m")

    assert signals.requested_count is None


def test_extract_signals_non_numeric_project_count_is_none():
    reply = "ROLE: \nENVIRONMENT: \nRESPONSIBILITIES: \nDOMAIN: \nPROJECT_COUNT: a few\n"
    client = FakeLLMClient(replies=[reply])

    signals = extract_retrieval_signals("x", client, "m")

    assert signals.requested_count is None


def test_extract_signals_zero_or_negative_project_count_is_none():
    for value in ("0", "-2"):
        reply = f"ROLE: \nENVIRONMENT: \nRESPONSIBILITIES: \nDOMAIN: \nPROJECT_COUNT: {value}\n"
        client = FakeLLMClient(replies=[reply])

        signals = extract_retrieval_signals("x", client, "m")

        assert signals.requested_count is None


def test_extract_signals_discards_a_hallucinated_count_not_present_in_the_request():
    # the model invents PROJECT_COUNT: 3 even though the request states no number at all --
    # observed live; the deterministic guard must reject this
    reply = "ROLE: \nENVIRONMENT: \nRESPONSIBILITIES: \nDOMAIN: \nPROJECT_COUNT: 3\n"
    client = FakeLLMClient(replies=[reply])

    signals = extract_retrieval_signals("highlight backend infrastructure work", client, "m")

    assert signals.requested_count is None


def test_extract_signals_accepts_a_digit_count_present_in_the_request():
    reply = "ROLE: \nENVIRONMENT: \nRESPONSIBILITIES: \nDOMAIN: \nPROJECT_COUNT: 3\n"
    client = FakeLLMClient(replies=[reply])

    signals = extract_retrieval_signals("give me 3 projects about backend work", client, "m")

    assert signals.requested_count == 3


def test_extract_signals_accepts_a_spelled_out_count_present_in_the_request():
    reply = "ROLE: \nENVIRONMENT: \nRESPONSIBILITIES: \nDOMAIN: \nPROJECT_COUNT: 3\n"
    client = FakeLLMClient(replies=[reply])

    signals = extract_retrieval_signals("give me three projects about backend work", client, "m")

    assert signals.requested_count == 3
