"""
Tests for extraction.py.
All tests use FakeProvider — no real network calls.
"""
import json
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
    provider = SequentialFakeProvider([make_result(VALID_JSON)])
    result = extract_requirements("build a to-do app", provider)
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
    result = extract_requirements("build a to-do app", provider)
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
    llm_json = json.loads(NULL_BOOLEANS_JSON)
    llm_json["realtime"] = True       # stated → no deterministic entry for realtime
    llm_json["unknowns"] = ["target audience"]
    provider = SequentialFakeProvider([make_result(json.dumps(llm_json))])
    result = extract_requirements("vague idea", provider)

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
