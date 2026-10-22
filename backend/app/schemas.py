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


class DesignRequest(BaseModel):
    # The raw project idea from the user
    idea: str = Field(min_length=1, max_length=20_000)


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


class DesignResponse(BaseModel):
    # "stage" records which pipeline step produced this response
    stage: str
    requirements: Requirements
