from models.blocks import Block
from fakes import FakeLLMClient
from tools.retrieval import (
    CategorizedKeywords,
    extract_retrieval_signals,
    extract_target_count,
    rank_blocks,
    score_block,
)

# _lexical_tokens/_block_lexical_tokens/_project_lexical_token_sets/_lexical_document_frequencies/
# lexical_matches don't exist in tools.retrieval yet (TDD -- implementation lands in a later task).
# Imported lazily inside each test that needs them so a missing name fails only that test, not
# collection of this whole module (which would also break the pre-existing tests below).
try:
    from tools.retrieval import (
        _block_lexical_tokens,
        _lexical_document_frequencies,
        _lexical_tokens,
        _project_lexical_token_sets,
        lexical_matches,
    )
except ImportError:
    _lexical_tokens = _block_lexical_tokens = _project_lexical_token_sets = None
    _lexical_document_frequencies = lexical_matches = None


def _conferencing_family_blocks():
    # 4 stored variants of the same project, sharing one tag_signature -- the
    # multi-variant blind-spot scenario from research.md
    return [
        Block(id="conferencing_software_solution", body="Family base variant.", tags=["conferencing_software_solution"]),
        Block(id="conferencing_software_solution_mut_a", body="Variant A.", tags=["conferencing_software_solution"]),
        Block(id="conferencing_software_solution_mut_b", body="Variant B.", tags=["conferencing_software_solution"]),
        Block(id="conferencing_software_solution_mut_c", body="Variant C.", tags=["conferencing_software_solution"]),
    ]


def _unrelated_singleton_blocks():
    # untagged -- each is its own tag_signature group; ids share "management"
    # across both, but neither shares anything with the conferencing family
    return [
        Block(id="veterinary_clinic_management", body="## Veterinary Practice\n"),
        Block(id="restaurant_inventory_management", body="## Restaurant Ops\n"),
    ]


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


def test_extract_keywords_swallows_client_exceptions():
    class BrokenClient:
        def chat(self, *a, **kw):
            raise RuntimeError("network down")

    signals = extract_retrieval_signals("x", BrokenClient(), "m")

    assert signals.keywords.is_empty()


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
    # a small top_n must not shrink the unmatched reserve to 0
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


def test_extract_target_count_parses_a_well_formed_reply():
    client = FakeLLMClient(replies=["3"])

    count = extract_target_count("give me 3 projects", client, "m")

    assert count == 3


def test_extract_target_count_none_reply_is_none():
    client = FakeLLMClient(replies=["NONE"])

    count = extract_target_count("highlight backend infrastructure work", client, "m")

    assert count is None


def test_extract_target_count_discards_a_hallucinated_count_not_present_in_the_request():
    # a count the model invents but the request never states must be rejected
    client = FakeLLMClient(replies=["3"])

    count = extract_target_count("highlight backend infrastructure work", client, "m")

    assert count is None


def test_extract_target_count_swallows_client_exceptions():
    class BrokenClient:
        def chat(self, *a, **kw):
            raise RuntimeError("network down")

    count = extract_target_count("x", BrokenClient(), "m")

    assert count is None


def test_extract_target_count_accepts_a_spelled_out_count_present_in_the_request():
    client = FakeLLMClient(replies=["3"])

    count = extract_target_count("give me three projects about backend work", client, "m")

    assert count == 3


def test_extract_target_count_takes_the_last_number_from_a_verbose_reply():
    client = FakeLLMClient(replies=["The request mentions 3 projects, so my answer is 3"])

    count = extract_target_count("give me 3 projects", client, "m")

    assert count == 3


def test_extract_target_count_verbose_reply_with_no_number_is_none():
    client = FakeLLMClient(replies=["I don't see a specific count stated anywhere"])

    count = extract_target_count("highlight backend infrastructure work", client, "m")

    assert count is None


def test_score_block_default_keyword_weight_matches_explicit_none():
    keywords = CategorizedKeywords(role=["engineer"], responsibilities=["shipped features"])
    block = Block(id="x", body="## Engineer Project\n\nDid stuff.\n\n**Responsibilities:**\n- shipped features\n")

    default_scored = score_block(block, keywords)
    explicit_none_scored = score_block(block, keywords, keyword_weight=None)

    assert default_scored.score == explicit_none_scored.score == 1.5 + 1.0
    assert default_scored.matched == explicit_none_scored.matched == {
        "role": ["engineer"],
        "responsibilities": ["shipped features"],
    }


def test_score_block_keyword_weight_multiplies_into_category_weight():
    keywords = CategorizedKeywords(role=["engineer"])
    block = Block(id="x", body="## Engineer Project\n\nDid stuff.\n")

    scored = score_block(block, keywords, keyword_weight=lambda category, kw: 2.0)

    assert scored.score == 3.0  # 1.5 (role weight) * 2.0 (keyword_weight)


def test_score_block_keyword_weight_applies_per_matched_keyword():
    keywords = CategorizedKeywords(role=["engineer", "manager"])
    block = Block(id="x", body="## Engineer Manager Project\n\nDid stuff.\n")
    weights = {"engineer": 2.0, "manager": 3.0}

    scored = score_block(block, keywords, keyword_weight=lambda category, kw: weights[kw])

    assert scored.score == 7.5  # 1.5 * (2.0 + 3.0)


# --- T006: _lexical_tokens -------------------------------------------------


def test_lexical_tokens_lowercases_and_splits_into_word_tokens():
    tokens = _lexical_tokens("ERP-PDM System")

    assert "erp" in tokens
    assert "pdm" in tokens


def test_lexical_tokens_drops_tokens_of_length_two_or_less():
    tokens = _lexical_tokens("an id ERP")

    assert "id" not in tokens  # length 2
    assert "an" not in tokens  # length 2
    assert "erp" in tokens


def test_lexical_tokens_drops_generic_stopwords_but_keeps_distinctive_words():
    tokens = _lexical_tokens("the conferencing system for the platform project")

    assert "system" not in tokens
    assert "platform" not in tokens
    assert "project" not in tokens
    assert "for" not in tokens
    assert "the" not in tokens
    assert "conferencing" in tokens


# --- T007: _block_lexical_tokens --------------------------------------------


def test_block_lexical_tokens_draws_from_id_tags_and_name():
    block = Block(id="erp_pdm_system", body="## Conferencing Platform\n\nDetails.\n", tags=["finance_tools"])

    tokens = _block_lexical_tokens(block)

    assert "erp" in tokens
    assert "pdm" in tokens
    assert "finance" in tokens
    assert "conferencing" in tokens


def test_block_lexical_tokens_normalizes_underscores_and_dashes_before_tokenizing():
    block = Block(id="erp-pdm_gizmo", body="Untitled block, no heading.\n")

    tokens = _block_lexical_tokens(block)

    assert "erp" in tokens
    assert "pdm" in tokens
    assert "gizmo" in tokens
    assert "erppdmgizmo" not in tokens  # must not be glued into one token


# --- T008: _project_lexical_token_sets / _lexical_document_frequencies -----


def test_project_lexical_token_sets_groups_by_tag_signature():
    family = _conferencing_family_blocks()
    singletons = _unrelated_singleton_blocks()

    groups = _project_lexical_token_sets(family + singletons)

    # one group for the shared-tag family, one each for the two untagged singletons
    assert len(groups) == 3
    family_tokens = groups[family[0].tag_signature]
    assert "conferencing" in family_tokens


def test_lexical_document_frequencies_counts_projects_not_stored_blocks():
    family = _conferencing_family_blocks()
    singletons = _unrelated_singleton_blocks()

    dfs = _lexical_document_frequencies(family + singletons)

    # a naive per-block count would see "conferencing" in all 4 stored blocks and report 4;
    # it must be counted once, for the one project those 4 blocks belong to
    assert dfs["conferencing"] == 1


def test_lexical_document_frequencies_counts_a_word_unique_to_one_singleton_as_one():
    family = _conferencing_family_blocks()
    singletons = _unrelated_singleton_blocks()

    dfs = _lexical_document_frequencies(family + singletons)

    assert dfs["veterinary"] == 1
    assert dfs["restaurant"] == 1


def test_lexical_document_frequencies_counts_cross_project_sharing_normally():
    family = _conferencing_family_blocks()
    singletons = _unrelated_singleton_blocks()

    dfs = _lexical_document_frequencies(family + singletons)

    # both unrelated singletons independently use "management" -- two distinct
    # projects sharing a word is still counted normally, unlike within-project duplication
    assert dfs["management"] == 2


# --- T009: lexical_matches ---------------------------------------------------


def test_lexical_matches_returns_empty_for_a_request_with_no_lexical_overlap():
    blocks = _conferencing_family_blocks() + _unrelated_singleton_blocks()

    matches = lexical_matches(blocks, "completely unrelated request text about nothing")

    assert matches == []


def test_lexical_matches_force_includes_family_member_despite_variant_count():
    blocks = _conferencing_family_blocks() + _unrelated_singleton_blocks()

    matches = lexical_matches(blocks, "my conferencing software solution project")

    matched_ids = {b.id for b in matches}
    family_ids = {b.id for b in _conferencing_family_blocks()}
    assert matched_ids & family_ids  # at least one family member force-included


def test_lexical_matches_excludes_a_token_shared_by_more_than_rare_df_max_projects():
    rare_df_max = 3
    # rare_df_max + 1 distinct singleton projects, all sharing the one word "gizmo"
    blocks = [Block(id=f"gizmo_{i}", body="No heading here.\n") for i in range(rare_df_max + 1)]

    matches = lexical_matches(blocks, "gizmo", rare_df_max=rare_df_max)

    assert matches == []


# --- T010: rank_blocks(force_include=...) ------------------------------------


def test_rank_blocks_force_include_prepends_ahead_of_score_ranked_output():
    keywords = CategorizedKeywords(environment=["Jira"])
    strong = Block(id="strong", body="## A\n\n**Environment:** Jira\n")
    forced = Block(id="forced", body="## Forced\n\nNo keyword overlap.\n")

    ranked = rank_blocks([strong], keywords, top_n=5, force_include=[forced])

    assert ranked[0].id == "forced"
    assert ranked[1].id == "strong"


def test_rank_blocks_force_include_dedups_a_block_already_in_ranked_output():
    keywords = CategorizedKeywords(environment=["Jira"])
    strong = Block(id="strong", body="## A\n\n**Environment:** Jira\n")

    ranked = rank_blocks([strong], keywords, top_n=5, force_include=[strong])

    assert [b.id for b in ranked] == ["strong"]


def test_rank_blocks_force_include_none_or_empty_matches_omitting_the_parameter():
    keywords = CategorizedKeywords(environment=["Jira"])
    strong = Block(id="strong", body="## A\n\n**Environment:** Jira\n")
    weak = Block(id="weak", body="## B\n\nNothing relevant.\n")

    without_param = rank_blocks([weak, strong], keywords, top_n=5)
    with_none = rank_blocks([weak, strong], keywords, top_n=5, force_include=None)
    with_empty = rank_blocks([weak, strong], keywords, top_n=5, force_include=[])

    assert [b.id for b in with_none] == [b.id for b in without_param]
    assert [b.id for b in with_empty] == [b.id for b in without_param]
