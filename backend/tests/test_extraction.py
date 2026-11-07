"""
Tests for extraction.py.
All tests use FakeProvider — no real network calls.
"""
import json
import logging

import pytest

from app.extraction import (
    ExtractionError,
    SYSTEM_PROMPT,
    _build_deterministic_unknowns,
    _merge_unknowns,
    extract_requirements,
)
from app.llm import LLMProvider, LLMResult
from app.schemas import ExpectedScale, Requirements

# ── shared fixture data ────────────────────────────────────────────────────────

# A minimal but fully valid Requirements JSON string.
# All booleans are explicitly True or False (not None) so this fixture
# does not trigger any deterministic unknowns entries.
VALID_JSON = json.dumps({
    "project_summary": "A to-do app",
    "app_type": "web",
    "core_features": ["task creation", "task completion"],
    "user_roles": ["user"],
    "expected_scale": {
        "users": "1000",
        "peak_requests_per_second": None,
        "data_volume": None,
    },
    "realtime": False,
    "geospatial": False,
    "authentication": True,
    "search_filtering": False,
    "media_storage": False,
    "payments": False,
    "offline_support": False,
    "external_integrations": [],
    "constraints": [],
    "assumptions": ["Single-user initially"],
    "unknowns": ["target platform"],
    # Only app_type is grounded here; the booleans are left without evidence
    # on purpose so the evidence check drops them (see the evidence tests
    # below) rather than keeping stale True/False fixture values unverified.
    # The quote includes "web" because the keyword heuristic now requires a
    # web/mobile/api word to back a non-"other" app_type, not just any
    # substring of the idea.
    "evidence": {"app_type": "to-do web app"},
})

# A second fixture where booleans are null, app_type is null, and all scale is null.
# Used to test deterministic unknowns generation.
NULL_BOOLEANS_JSON = json.dumps({
    "project_summary": "A vague app",
    "app_type": None,
    "core_features": ["core thing"],
    "user_roles": ["user"],
    "expected_scale": {
        "users": None,
        "peak_requests_per_second": None,
        "data_volume": None,
    },
    "realtime": None,
    "geospatial": None,
    "authentication": None,
    "search_filtering": None,
    "media_storage": None,
    "payments": None,
    "offline_support": None,
    "external_integrations": [],
    "constraints": [],
    "assumptions": [],
    "unknowns": [],
})


# ── FakeProvider helpers ───────────────────────────────────────────────────────

class SequentialFakeProvider(LLMProvider):
    """
    Returns responses from a pre-loaded list, one per call.
    Tracks prompt_tokens and completion_tokens on each result so token
    counts can be asserted.
    """
    def __init__(self, responses: list[LLMResult]) -> None:
        self._responses = iter(responses)

    def complete_json(self, system: str, user: str, max_tokens: int) -> LLMResult:
        return next(self._responses)


def make_result(text: str, prompt_tokens: int = 10, completion_tokens: int = 20) -> LLMResult:
    """Convenience constructor so every test does not repeat token defaults."""
    return LLMResult(text=text, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)


# ── extraction tests ───────────────────────────────────────────────────────────

def test_valid_json_returns_requirements_object():
    # Happy path: first call returns good JSON → Requirements comes back
    # Idea must contain "web" so the evidence quote's keyword check passes.
    provider = SequentialFakeProvider([make_result(VALID_JSON)])
    result = extract_requirements("build a to-do web app", provider)
    assert isinstance(result, Requirements)
    assert result.app_type == "web"


def test_json_wrapped_in_markdown_fences_is_parsed():
    # Model occasionally wraps output in ```json ... ``` — should still parse
    fenced = f"```json\n{VALID_JSON}\n```"
    provider = SequentialFakeProvider([make_result(fenced)])
    result = extract_requirements("build a to-do app", provider)
    assert isinstance(result, Requirements)


def test_think_tags_before_json_are_stripped():
    # Safety net: if reasoning leaks through, strip <think>...</think> then parse
    wrapped = f"<think>I will analyse this carefully.</think>\n{VALID_JSON}"
    provider = SequentialFakeProvider([make_result(wrapped)])
    result = extract_requirements("build a to-do app", provider)
    assert isinstance(result, Requirements)


def test_invalid_json_first_valid_second_retry_succeeds():
    # First response is garbage → triggers retry → second response is valid
    provider = SequentialFakeProvider([
        make_result("not valid json at all"),
        make_result(VALID_JSON),
    ])
    result = extract_requirements("build a to-do app", provider)
    assert isinstance(result, Requirements)


def test_invalid_twice_raises_extraction_error():
    # Both attempts return garbage → ExtractionError must be raised
    provider = SequentialFakeProvider([
        make_result("bad response 1"),
        make_result("bad response 2"),
    ])
    with pytest.raises(ExtractionError):
        extract_requirements("build a to-do app", provider)


def test_null_app_type_is_accepted_by_schema():
    # app_type=None is the new valid "not stated" state
    req = _make_requirements(app_type=None)
    assert req.app_type is None


def test_wrong_app_type_string_fails_validation_triggers_retry_then_succeeds():
    # An invalid Literal string (not null, not a valid option) → pydantic
    # ValidationError → retry → second response is valid
    bad_type = json.dumps({**json.loads(VALID_JSON), "app_type": "desktop"})
    provider = SequentialFakeProvider([
        make_result(bad_type),
        make_result(VALID_JSON),
    ])
    result = extract_requirements("build a to-do web app", provider)
    assert result.app_type == "web"


def test_token_counts_are_returned_in_llm_result():
    # LLMResult must carry the token counts reported by the provider
    result = make_result(VALID_JSON, prompt_tokens=42, completion_tokens=99)
    assert result.prompt_tokens == 42
    assert result.completion_tokens == 99


# ── ExpectedScale normalisation tests ─────────────────────────────────────────

@pytest.mark.parametrize("placeholder", ["null", "N/A", ""])
def test_scale_placeholder_string_becomes_none(placeholder):
    # "null", "N/A", and "" should all normalise to None before validation
    scale = ExpectedScale(
        users=placeholder,
        peak_requests_per_second=placeholder,
        data_volume=placeholder,
    )
    assert scale.users is None
    assert scale.peak_requests_per_second is None
    assert scale.data_volume is None


def test_scale_real_value_is_preserved():
    # Actual values must pass through unchanged
    scale = ExpectedScale(users="10 000 DAU", peak_requests_per_second=None, data_volume=None)
    assert scale.users == "10 000 DAU"


# ── list placeholder-filtering tests ──────────────────────────────────────────

def _make_requirements(**overrides):
    """Build a Requirements dict from VALID_JSON with optional field overrides."""
    base = json.loads(VALID_JSON)
    base.update(overrides)
    return Requirements(**base)


def test_placeholder_items_are_dropped_from_lists():
    # Items like "none", "N/A", "" must be removed from every list field
    req = _make_requirements(
        core_features=["task creation", "none", "N/A", ""],
        unknowns=["target platform", "unknown", "unspecified"],
        assumptions=["Single-user initially", "null"],
    )
    assert "none" not in req.core_features
    assert "N/A" not in req.core_features
    assert "" not in req.core_features
    assert "task creation" in req.core_features   # real item kept

    assert "unknown" not in req.unknowns
    assert "unspecified" not in req.unknowns
    assert "target platform" in req.unknowns      # real item kept

    assert "null" not in req.assumptions
    assert "Single-user initially" in req.assumptions  # real item kept


def test_empty_list_stays_empty_after_filter():
    # An already-empty list must remain empty (no crashes)
    req = _make_requirements(external_integrations=[])
    assert req.external_integrations == []


# ── tri-state boolean tests ────────────────────────────────────────────────────

def test_boolean_none_is_accepted_by_schema():
    # None is the valid "not addressed" state for every boolean flag
    req = _make_requirements(
        realtime=None,
        geospatial=None,
        authentication=None,
        search_filtering=None,
        media_storage=None,
        payments=None,
        offline_support=None,
    )
    assert req.realtime is None
    assert req.authentication is None
    assert req.payments is None


def test_boolean_true_and_false_still_accepted():
    # True and False must still work after the tri-state change
    req = _make_requirements(authentication=True, payments=False)
    assert req.authentication is True
    assert req.payments is False


# ── deterministic unknowns unit tests ─────────────────────────────────────────

def _make_req_from_null_booleans_json(**overrides):
    base = json.loads(NULL_BOOLEANS_JSON)
    base.update(overrides)
    return Requirements(**base)


def test_null_app_type_produces_unknown_entry():
    # app_type=None must generate "app_type not specified" as the first entry
    req = _make_req_from_null_booleans_json()
    entries = _build_deterministic_unknowns(req)
    assert "app_type not specified" in entries
    # app_type entry must appear before boolean entries
    assert entries.index("app_type not specified") < entries.index("realtime not specified")


def test_set_app_type_does_not_produce_unknown_entry():
    # A known app_type must not generate an unknown entry
    req = _make_req_from_null_booleans_json(app_type="web")
    entries = _build_deterministic_unknowns(req)
    assert "app_type not specified" not in entries


def test_null_boolean_produces_unknown_entry():
    # Each None boolean must generate "<field> not specified" in unknowns
    req = _make_req_from_null_booleans_json()
    entries = _build_deterministic_unknowns(req)
    assert "realtime not specified" in entries
    assert "authentication not specified" in entries
    assert "payments not specified" in entries
    assert "media_storage not specified" in entries
    assert "offline_support not specified" in entries


def test_true_boolean_does_not_produce_unknown_entry():
    # True means "stated" — no unknown should be generated
    req = _make_req_from_null_booleans_json(authentication=True)
    entries = _build_deterministic_unknowns(req)
    assert "authentication not specified" not in entries


def test_false_boolean_does_not_produce_unknown_entry():
    # False means "stated absent" — no unknown should be generated
    req = _make_req_from_null_booleans_json(payments=False)
    entries = _build_deterministic_unknowns(req)
    assert "payments not specified" not in entries


def test_all_scale_none_produces_scale_unknown_entry():
    # All three scale fields None → exactly one "expected scale not specified" entry
    req = _make_req_from_null_booleans_json()
    entries = _build_deterministic_unknowns(req)
    assert "expected scale not specified" in entries


def test_partial_scale_does_not_produce_scale_unknown_entry():
    # If even one scale field is set, the combined scale entry is suppressed
    req = _make_req_from_null_booleans_json(
        expected_scale={"users": "1000", "peak_requests_per_second": None, "data_volume": None}
    )
    entries = _build_deterministic_unknowns(req)
    assert "expected scale not specified" not in entries


# ── end-to-end deterministic unknowns via extract_requirements ─────────────────

def test_extract_requirements_injects_deterministic_unknowns():
    # When the LLM returns null booleans and null app_type, the final object
    # must contain those deterministic entries even if the LLM's unknowns was empty
    provider = SequentialFakeProvider([make_result(NULL_BOOLEANS_JSON)])
    result = extract_requirements("vague idea", provider)
    assert "app_type not specified" in result.unknowns
    assert "realtime not specified" in result.unknowns
    assert "expected scale not specified" in result.unknowns


def test_extract_requirements_merges_without_duplicates():
    # If the LLM also wrote "realtime not specified", there must be no duplicate
    llm_json = json.loads(NULL_BOOLEANS_JSON)
    llm_json["unknowns"] = ["realtime not specified", "some other unknown"]
    provider = SequentialFakeProvider([make_result(json.dumps(llm_json))])
    result = extract_requirements("vague idea", provider)

    assert result.unknowns.count("realtime not specified") == 1
    assert "some other unknown" in result.unknowns


def test_extract_requirements_llm_unknowns_preserved_after_merge():
    # Extra unknowns from the LLM (not covered by deterministic entries) must survive
    # Idea needs a realtime keyword ("live") so the grounded True survives
    # the keyword heuristic, not just the plain substring check.
    llm_json = json.loads(NULL_BOOLEANS_JSON)
    llm_json["realtime"] = True       # stated → no deterministic entry for realtime
    llm_json["evidence"] = {"realtime": "live updates"}  # grounds the True value
    llm_json["unknowns"] = ["target audience"]
    provider = SequentialFakeProvider([make_result(json.dumps(llm_json))])
    result = extract_requirements("a vague idea with live updates", provider)

    assert "target audience" in result.unknowns
    assert "realtime not specified" not in result.unknowns


# ── merge_unknowns unit tests ──────────────────────────────────────────────────

def test_merge_unknowns_deduplicates_case_insensitively():
    deterministic = ["realtime not specified"]
    llm = ["Realtime Not Specified", "target audience"]
    merged = _merge_unknowns(deterministic, llm)
    # Only one "realtime not specified" entry (the deterministic one comes first)
    assert merged.count("realtime not specified") == 1
    assert "target audience" in merged


def test_merge_unknowns_deterministic_entries_come_first():
    deterministic = ["payments not specified", "expected scale not specified"]
    llm = ["target audience", "payments not specified"]
    merged = _merge_unknowns(deterministic, llm)
    # Deterministic entries must appear before LLM entries
    assert merged.index("payments not specified") < merged.index("target audience")


# ── system prompt content tests ───────────────────────────────────────────────

def test_system_prompt_contains_tristate_boolean_rule():
    # The new tri-state wording must be in the prompt
    assert "null" in SYSTEM_PROMPT
    assert "true | false | null" in SYSTEM_PROMPT


def test_system_prompt_tells_llm_not_to_write_boolean_unknowns():
    # Updated wording covers boolean, scale, and app_type
    assert "Do NOT list boolean, scale, or app_type unknowns" in SYSTEM_PROMPT


def test_system_prompt_app_type_null_not_assumed():
    # The old "app_type assumed" rule is gone; null is now the instruction
    assert "app_type assumed" not in SYSTEM_PROMPT
    assert "use JSON null" in SYSTEM_PROMPT


def test_system_prompt_contains_constraints_rule():
    # constraints must say "only limits the input explicitly states"
    assert "constraints lists ONLY limits the input explicitly states" in SYSTEM_PROMPT


def test_system_prompt_contains_json_null_rule():
    assert "JSON null" in SYSTEM_PROMPT


def test_system_prompt_contains_no_invented_names_rule():
    assert "map provider" in SYSTEM_PROMPT


def test_system_prompt_contains_core_features_rule():
    assert "core_features lists only features" in SYSTEM_PROMPT


def test_system_prompt_contains_external_integrations_rule():
    assert "external_integrations lists only services" in SYSTEM_PROMPT


def test_system_prompt_contains_evidence_rule():
    # The new evidence-grounding rule must be present and must require a
    # verbatim (never paraphrased) quote.
    assert "evidence" in SYSTEM_PROMPT
    assert "verbatim quote" in SYSTEM_PROMPT
    assert "never paraphrased" in SYSTEM_PROMPT


# ── evidence-grounded extraction ───────────────────────────────────────────────
# Reproduces the "nearby bars" bug: a boolean/app_type claim with no quote
# backing it in the idea text must be dropped to None, never trusted as-is.

def _null_booleans_with(**overrides) -> str:
    data = json.loads(NULL_BOOLEANS_JSON)
    data.update(overrides)
    return json.dumps(data)


def test_evidence_valid_quote_keeps_the_value():
    idea = "An app to find nearby bars. Users must log in with a password."
    llm_json = _null_booleans_with(
        authentication=True,
        evidence={"authentication": "log in with a password"},
    )
    provider = SequentialFakeProvider([make_result(llm_json)])
    result = extract_requirements(idea, provider)
    assert result.authentication is True
    assert "authentication not specified" not in result.unknowns


def test_evidence_missing_quote_drops_value_and_adds_unknown():
    # authentication=True with no evidence entry at all — this is exactly the
    # "nearby bars" bug: an ungrounded claim must not survive.
    idea = "An app to find nearby bars."
    llm_json = _null_booleans_with(authentication=True)
    provider = SequentialFakeProvider([make_result(llm_json)])
    result = extract_requirements(idea, provider)
    assert result.authentication is None
    assert "authentication not specified" in result.unknowns
    assert "authentication" not in result.evidence


def test_evidence_quote_not_found_in_idea_drops_value():
    idea = "An app to find nearby bars."
    llm_json = _null_booleans_with(
        authentication=True,
        evidence={"authentication": "log in with a password"},  # not in idea
    )
    provider = SequentialFakeProvider([make_result(llm_json)])
    result = extract_requirements(idea, provider)
    assert result.authentication is None
    assert "authentication not specified" in result.unknowns


def test_evidence_quote_case_and_whitespace_differences_are_accepted():
    idea = "An app to find nearby bars.  Users must   LOG IN   with a password."
    llm_json = _null_booleans_with(
        authentication=True,
        evidence={"authentication": "log in with a password"},
    )
    provider = SequentialFakeProvider([make_result(llm_json)])
    result = extract_requirements(idea, provider)
    assert result.authentication is True


def test_evidence_app_type_dropped_without_matching_quote():
    idea = "An app to find nearby bars."
    llm_json = _null_booleans_with(app_type="mobile")
    provider = SequentialFakeProvider([make_result(llm_json)])
    result = extract_requirements(idea, provider)
    assert result.app_type is None
    assert "app_type not specified" in result.unknowns


def test_evidence_app_type_kept_with_matching_quote():
    # "built for phones" has no mobile/web/api keyword, so this now needs a
    # quote containing one (e.g. "mobile") to pass the keyword heuristic.
    idea = "An app to find nearby bars, built for mobile phones."
    llm_json = _null_booleans_with(
        app_type="mobile",
        evidence={"app_type": "built for mobile phones"},
    )
    provider = SequentialFakeProvider([make_result(llm_json)])
    result = extract_requirements(idea, provider)
    assert result.app_type == "mobile"
    assert "app_type not specified" not in result.unknowns


def test_evidence_check_never_logs_idea_text(caplog):
    # A field is dropped (triggering the evidence-check log line); the idea
    # text itself, including anything sensitive in it, must never appear.
    idea = "my secret idea with sk-abcdefghijklmnopqrstuvwxyz1234"
    llm_json = _null_booleans_with(authentication=True)  # no evidence → dropped
    provider = SequentialFakeProvider([make_result(llm_json)])

    with caplog.at_level(logging.INFO):
        result = extract_requirements(idea, provider)

    assert result.authentication is None
    assert any("authentication" in r.getMessage() for r in caplog.records)
    for record in caplog.records:
        assert idea not in record.getMessage()


# ── evidence keyword/negation heuristic ────────────────────────────────────────
# Tightens the plain substring check above: a quote that is merely *in* the
# idea (even the whole idea sentence) must also carry a field-relevant
# keyword (TRUE) or a negation word (FALSE) to be trusted.

def test_evidence_whole_idea_quote_without_keyword_is_dropped():
    # Quoting the entire idea passes the old substring check but contains no
    # authentication-related keyword, so it must not ground the claim.
    idea = "An app to find nearby bars"
    llm_json = _null_booleans_with(
        authentication=True,
        evidence={"authentication": idea},
    )
    provider = SequentialFakeProvider([make_result(llm_json)])
    result = extract_requirements(idea, provider)
    assert result.authentication is None
    assert "authentication not specified" in result.unknowns


def test_evidence_true_with_relevant_keyword_is_kept():
    idea = "An app to find nearby bars. Users must sign up for an account."
    llm_json = _null_booleans_with(
        authentication=True,
        evidence={"authentication": "sign up for an account"},
    )
    provider = SequentialFakeProvider([make_result(llm_json)])
    result = extract_requirements(idea, provider)
    assert result.authentication is True


def test_evidence_false_without_negation_is_dropped():
    # Quote is real and about payments, but has no negation word, so a FALSE
    # claim still cannot be trusted.
    idea = "An app to find nearby bars with payment info shown sometimes."
    llm_json = _null_booleans_with(
        payments=False,
        evidence={"payments": "payment info shown sometimes"},
    )
    provider = SequentialFakeProvider([make_result(llm_json)])
    result = extract_requirements(idea, provider)
    assert result.payments is None
    assert "payments not specified" in result.unknowns


def test_evidence_false_with_no_login_is_kept():
    idea = "An app to find nearby bars. There is no login required."
    llm_json = _null_booleans_with(
        authentication=False,
        evidence={"authentication": "no login required"},
    )
    provider = SequentialFakeProvider([make_result(llm_json)])
    result = extract_requirements(idea, provider)
    assert result.authentication is False


def test_evidence_false_with_contraction_negation_is_kept():
    idea = "An app to find nearby bars. It doesn't need offline support."
    llm_json = _null_booleans_with(
        offline_support=False,
        evidence={"offline_support": "doesn't need offline support"},
    )
    provider = SequentialFakeProvider([make_result(llm_json)])
    result = extract_requirements(idea, provider)
    assert result.offline_support is False


def test_evidence_app_type_mobile_from_bare_app_word_is_dropped():
    # "app" alone is explicitly not evidence for any app_type.
    idea = "A bars finder app."
    llm_json = _null_booleans_with(app_type="mobile", evidence={"app_type": "app"})
    provider = SequentialFakeProvider([make_result(llm_json)])
    result = extract_requirements(idea, provider)
    assert result.app_type is None


def test_evidence_app_type_mobile_from_mobile_app_is_kept():
    idea = "A bars finder mobile app."
    llm_json = _null_booleans_with(app_type="mobile", evidence={"app_type": "mobile app"})
    provider = SequentialFakeProvider([make_result(llm_json)])
    result = extract_requirements(idea, provider)
    assert result.app_type == "mobile"


def test_evidence_app_type_both_needs_two_words_one_is_not_enough():
    idea = "An app to find nearby bars, available on the web and as an iphone app."
    llm_json = _null_booleans_with(
        app_type="both",
        evidence={"app_type": "available on the web"},
    )
    provider = SequentialFakeProvider([make_result(llm_json)])
    result = extract_requirements(idea, provider)
    assert result.app_type is None


def test_evidence_app_type_both_kept_with_mobile_and_web_words():
    idea = "An app to find nearby bars, available on the web and as an iphone app."
    llm_json = _null_booleans_with(
        app_type="both",
        evidence={"app_type": "available on the web and as an iphone app"},
    )
    provider = SequentialFakeProvider([make_result(llm_json)])
    result = extract_requirements(idea, provider)
    assert result.app_type == "both"


def test_evidence_app_type_both_kept_with_cross_platform_word():
    idea = "An app to find nearby bars, built cross-platform."
    llm_json = _null_booleans_with(
        app_type="both",
        evidence={"app_type": "built cross-platform"},
    )
    provider = SequentialFakeProvider([make_result(llm_json)])
    result = extract_requirements(idea, provider)
    assert result.app_type == "both"


# ── LLM-written unknowns: contradiction filtering + cap ────────────────────────

def test_llm_unknown_contradicting_still_unresolved_field_is_filtered():
    # authentication=True is dropped for lack of evidence, so the
    # deterministic "authentication not specified" is added; a same-topic
    # LLM unknown saying the same thing in different words is redundant.
    idea = "An app to find nearby bars."
    llm_json = _null_booleans_with(
        authentication=True,  # no evidence → dropped
        unknowns=["no login flow mentioned", "something unrelated"],
    )
    provider = SequentialFakeProvider([make_result(llm_json)])
    result = extract_requirements(idea, provider)
    assert "authentication not specified" in result.unknowns
    assert "no login flow mentioned" not in result.unknowns
    assert "something unrelated" in result.unknowns


def test_llm_unknown_contradicting_resolved_field_is_filtered():
    idea = "An app to find nearby bars. Users must log in with a password."
    llm_json = _null_booleans_with(
        authentication=True,
        evidence={"authentication": "log in with a password"},
        unknowns=["login method not specified", "something unrelated"],
    )
    provider = SequentialFakeProvider([make_result(llm_json)])
    result = extract_requirements(idea, provider)
    assert result.authentication is True
    assert "login method not specified" not in result.unknowns
    assert "something unrelated" in result.unknowns


def test_llm_unknowns_capped_at_three():
    idea = "A vague app idea."
    llm_json = _null_booleans_with(unknowns=["one", "two", "three", "four", "five"])
    provider = SequentialFakeProvider([make_result(llm_json)])
    result = extract_requirements(idea, provider)
    kept = [u for u in result.unknowns if u in {"one", "two", "three", "four", "five"}]
    assert kept == ["one", "two", "three"]


def test_llm_unknown_truncated_to_100_chars():
    idea = "A vague app idea."
    long_unknown = "x" * 150
    llm_json = _null_booleans_with(unknowns=[long_unknown])
    provider = SequentialFakeProvider([make_result(llm_json)])
    result = extract_requirements(idea, provider)
    truncated = [u for u in result.unknowns if u.startswith("x")]
    assert len(truncated) == 1
    assert len(truncated[0]) == 100


def test_evidence_check_does_not_log_quote_text(caplog):
    # The dropped-field log line must name only the field, never the quote
    # or idea text, even when the quote was close but failed the keyword
    # heuristic.
    idea = "An app to find nearby bars."
    distinctive_quote = "zzz-distinctive-quote-zzz nearby bars"
    llm_json = _null_booleans_with(
        authentication=True,
        evidence={"authentication": distinctive_quote},
    )
    provider = SequentialFakeProvider([make_result(llm_json)])

    with caplog.at_level(logging.INFO):
        result = extract_requirements(idea, provider)

    assert result.authentication is None
    for record in caplog.records:
        assert "zzz-distinctive-quote-zzz" not in record.getMessage()
        assert idea not in record.getMessage()
