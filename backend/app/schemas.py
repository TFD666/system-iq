from typing import Literal
from pydantic import BaseModel, Field, field_validator


# Strings the model might return when it doesn't know a scale value.
# We normalise all of these to None so callers never see placeholder text.
_SCALE_PLACEHOLDERS = {"null", "none", "n/a", "na", "unknown", "unspecified", ""}

# Short placeholder strings a model might put in lists instead of real items.
_LIST_PLACEHOLDERS = {"null", "none", "n/a", "na", "unknown", "unspecified"}

# The seven boolean feature flags that can be tri-state (True / False / None).
# None means "the input does not address this at all".
TRISTATE_BOOL_FIELDS = (
    "realtime",
    "geospatial",
    "authentication",
    "search_filtering",
    "media_storage",
    "payments",
    "offline_support",
)

# Fields whose non-null value must be backed by a verbatim quote from the idea
# text in "evidence" (see extraction._enforce_evidence).
EVIDENCE_FIELDS = ("app_type",) + TRISTATE_BOOL_FIELDS

# Longest evidence quote we keep; longer values are truncated, never rejected.
_EVIDENCE_QUOTE_MAX_LEN = 120


class DesignRequest(BaseModel):
    # The raw project idea from the user
    idea: str = Field(min_length=1, max_length=20_000)
    # Which pipeline step to stop at. Default "validate" runs the whole thing.
    stage: Literal["extract", "decide", "design", "validate"] = "validate"
    # How many revise-then-revalidate rounds the validate stage may use.
    max_revisions: int = Field(default=1, ge=0, le=2)
    # "pipeline" (default): extraction -> Jev decisions -> design -> validate.
    # "llm_only": extraction -> design with no decisions at all (no Jev call),
    # used as a baseline. Always stops at stage "designed" regardless of `stage`.
    mode: Literal["pipeline", "llm_only"] = "pipeline"


class ExpectedScale(BaseModel):
    # Scale info is often missing, so all fields are optional
    users: str | None = None
    peak_requests_per_second: str | None = None
    data_volume: str | None = None

    @field_validator("users", "peak_requests_per_second", "data_volume", mode="before")
    @classmethod
    def normalise_scale_field(cls, value):
        """
        Convert placeholder strings to None before type validation runs.
        Handles: "null", "none", "n/a", "na", "unknown", "unspecified", ""
        (all case-insensitive, with leading/trailing whitespace trimmed).
        """
        if isinstance(value, str) and value.strip().lower() in _SCALE_PLACEHOLDERS:
            return None
        return value


class Requirements(BaseModel):
    project_summary: str
    # None means the input does not say what kind of app this is.
    app_type: Literal["web", "mobile", "both", "api", "other"] | None = None
    core_features: list[str]
    user_roles: list[str]
    expected_scale: ExpectedScale

    # Tri-state feature flags:
    #   True  = input states/requires it
    #   False = input states it is not needed, or it is clearly absent
    #   None  = input does not address it at all
    realtime: bool | None = None
    geospatial: bool | None = None
    authentication: bool | None = None
    search_filtering: bool | None = None
    media_storage: bool | None = None
    payments: bool | None = None
    offline_support: bool | None = None

    external_integrations: list[str]
    constraints: list[str]
    assumptions: list[str]   # things inferred but not stated
    unknowns: list[str]      # things missing that we cannot guess

    # Verbatim idea quotes supporting each non-null field in EVIDENCE_FIELDS.
    # Only fields that pass the evidence check (extraction.py) keep an entry.
    evidence: dict[str, str] = Field(default_factory=dict)

    @field_validator("evidence", mode="before")
    @classmethod
    def normalise_evidence(cls, value):
        """
        Keep only entries keyed by an EVIDENCE_FIELDS name with a non-empty
        string value, truncated to _EVIDENCE_QUOTE_MAX_LEN characters.
        """
        if not isinstance(value, dict):
            return {}
        return {
            key: val.strip()[:_EVIDENCE_QUOTE_MAX_LEN]
            for key, val in value.items()
            if key in EVIDENCE_FIELDS and isinstance(val, str) and val.strip()
        }

    @field_validator(*TRISTATE_BOOL_FIELDS, mode="before")
    @classmethod
    def normalise_bool_field(cls, value):
        """
        Accept JSON null (Python None) to mean 'not addressed'.
        True and False pass through unchanged.
        """
        # None (from JSON null) is the valid third state — allow it
        return value

    @field_validator("app_type", mode="before")
    @classmethod
    def normalise_app_type(cls, value):
        """
        Convert placeholder strings to None before Literal validation runs.
        An absent app_type is recorded as None; the deterministic unknowns
        system adds 'app_type not specified' automatically.
        """
        if isinstance(value, str) and value.strip().lower() in _SCALE_PLACEHOLDERS:
            return None
        return value

    @field_validator(
        "core_features", "user_roles", "external_integrations",
        "constraints", "assumptions", "unknowns",
        mode="before",
    )
    @classmethod
    def drop_placeholder_list_items(cls, value):
        """
        Remove empty strings and known placeholder strings from every list field.
        Prevents the model from returning lists like ["none"] or ["unknown"].
        """
        if not isinstance(value, list):
            return value
        return [
            item for item in value
            if not (isinstance(item, str) and item.strip().lower() in _LIST_PLACEHOLDERS)
            and item != ""
        ]


class AlternativeOut(BaseModel):
    """One alternative answer and its probability, safe for JSON output."""
    option: str
    probability: float


class DecisionResultOut(BaseModel):
    """
    Serialisable form of a DecisionResult for the API response.
    'question' is always a fixed template sentence, never user input.
    """
    id: str
    question: str         # fixed template sentence describing what was asked
    status: str           # accepted | tentative | needs_review | yes | no | uncertain
    choice: str | None    # selected option (None for noul)
    probability: float
    top_alternatives: list[AlternativeOut]
    based_on_unknowns: bool


class ValidateRequest(BaseModel):
    """
    POST /validate: validate (and optionally revise) an already-produced
    design without re-running extraction/decide/design.
    """
    requirements: Requirements
    # Same shape /design returns; extra fields are ignored by pydantic.
    decisions: list[DecisionResultOut] = Field(default_factory=list)
    design_markdown: str = Field(max_length=40_000)
    max_revisions: int = Field(default=0, ge=0, le=2)


class DesignGroupStat(BaseModel):
    """Numbers only (no prompt text or model output) for one section group."""
    id: str
    prompt_tokens: int
    completion_tokens: int
    retries: int
    elapsed_seconds: float


class ValidationResultOut(BaseModel):
    """One validation question's answer, after apply_validation_policy."""
    id: str
    text: str              # fixed template sentence, never user input
    probability: float
    status: str            # "ok" | "possible" | "flagged"
    sections: list[int]    # design section numbers this answer is about


class RevisionRoundOut(BaseModel):
    """Numbers and ids only for one revise-then-revalidate round."""
    round: int
    sections_revised: list[int]
    flagged_ids: list[str]


class DecisionMeta(BaseModel):
    """Token-usage and model metadata from the Jev call, plus (for the
    "designed"/"validated" stages) the LLM model, design token counts,
    and (for "validated") validation call/token counts and status."""
    decision_model: str
    input_tokens: int
    output_tokens: int
    # Set when the provider reports billing info; None for fake/unknown providers.
    decision_billing: str | None = None
    decision_cost: float | None = None
    # The fields below are only set when stage == "design" or "validate".
    llm_model: str | None = None
    design_prompt_tokens: int | None = None
    design_completion_tokens: int | None = None
    design_group_stats: list[DesignGroupStat] | None = None
    # The fields below are only set when stage == "validate".
    validation_calls: int | None = None
    validation_input_tokens: int | None = None
    validation_output_tokens: int | None = None
    validation_status: str | None = None  # "passed" | "flagged" | "skipped"
    # The decision provider's model label for the validation call itself.
    # decision_model is fixed to "n/a (validation only)" for /validate, so
    # this is what callers must check to tell a real Jev run from fake/replay.
    validation_model: str | None = None


class DesignResponse(BaseModel):
    # "stage" records which pipeline step produced this response:
    # "extracted" | "decided" | "designed" | "validated"
    stage: str
    requirements: Requirements
    # Present when stage == "decided"/"designed"/"validated"; None for "extracted"
    decisions: list[DecisionResultOut] | None = None
    meta: DecisionMeta | None = None
    # Present when stage == "designed" or "validated"
    design_markdown: str | None = None
    design_warnings: list[str] | None = None
    # Present only when stage == "validated"
    validation: list[ValidationResultOut] | None = None
    revisions: list[RevisionRoundOut] | None = None
