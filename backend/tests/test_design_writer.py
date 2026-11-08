"""
Tests for app/design/writer.py. Uses a FakeLLM (no real network) that
echoes back whichever headings it was asked for, so we can check the
writer stitches every group's output together correctly.
"""

import logging
import re

import pytest

from app.design import writer as writer_module
from app.design.limiter import TokenBudget
from app.design.sections import ASSUMPTIONS_HEADING, all_headings
from app.design.writer import write_design
from app.llm import LLMProvider, LLMResult, RateLimitError
from app.schemas import AlternativeOut, DecisionResultOut, ExpectedScale, Requirements


# ── test doubles ─────────────────────────────────────────────────────────────

class FakeLLM(LLMProvider):
    """
    Records every call it receives and returns canned text containing
    whichever headings that call's system prompt asked for -- so the
    writer has something real to stitch together.
    """

    def __init__(self, prompt_tokens: int = 10, completion_tokens: int = 20) -> None:
        self.calls: list[dict] = []
        self._prompt_tokens = prompt_tokens
        self._completion_tokens = completion_tokens

    def complete_json(self, system: str, user: str, max_tokens: int) -> LLMResult:
        raise NotImplementedError("the design writer only uses complete_text")

    def complete_text(self, system: str, user: str, max_tokens: int) -> LLMResult:
        self.calls.append({"system": system, "user": user, "max_tokens": max_tokens})
        headings = re.findall(r"^## \d+\..*$", system, re.MULTILINE)
        # 17 repeats of a 5-word sentence = 85 words, clearing the 80-word
        # minimum so these canned responses pass validation on the first
        # try (no retry/fallback) unless a test deliberately breaks them.
        filler = " ".join(["Generated text for this section."] * 17)
        body = "\n\n".join(f"{heading}\n{filler}" for heading in headings)
        return LLMResult(
            text=body,
            prompt_tokens=self._prompt_tokens,
            completion_tokens=self._completion_tokens,
        )


class RateLimitedLLM(LLMProvider):
    """Always raises RateLimitError, to prove it propagates out of write_design."""

    def complete_json(self, system: str, user: str, max_tokens: int) -> LLMResult:
        raise NotImplementedError

    def complete_text(self, system: str, user: str, max_tokens: int) -> LLMResult:
        raise RateLimitError("rate limited")


def _no_wait_budget() -> TokenBudget:
    # Huge caps (both windows) and no real sleep, so tests never actually wait.
    return TokenBudget(
        max_total_tokens_per_minute=1_000_000,
        max_output_tokens_per_minute=1_000_000,
        clock=lambda: 0.0,
        sleep=lambda s: None,
    )


def _make_requirements(**overrides) -> Requirements:
    base = dict(
        project_summary="A to-do app for small teams.",
        app_type="web",
        core_features=["task creation"],
        user_roles=["user"],
        expected_scale=ExpectedScale(users=None, peak_requests_per_second=None, data_volume=None),
        realtime=False,
        geospatial=False,
        authentication=True,
        search_filtering=False,
        media_storage=False,
        payments=False,
        offline_support=False,
        external_integrations=[],
        constraints=[],
        assumptions=[],
        unknowns=[],
    )
    base.update(overrides)
    return Requirements(**base)


def _make_decision(**overrides) -> DecisionResultOut:
    base = dict(
        id="primary_database",
        question="Which database fits best?",
        status="accepted",
        choice="PostgreSQL",
        probability=0.9,
        top_alternatives=[AlternativeOut(option="PostgreSQL", probability=0.9)],
        based_on_unknowns=False,
    )
    base.update(overrides)
    return DecisionResultOut(**base)


# ── tests ──────────────────────────────────────────────────────────────────

def test_writer_stitches_all_13_headings_in_order():
    requirements = _make_requirements()
    result = write_design(requirements, decisions=None, llm=FakeLLM(), budget=_no_wait_budget())

    expected = all_headings()
    assert result.sections_found == expected

    # They must also appear in order in the actual markdown, not just be found.
    positions = [result.markdown.index(heading) for heading in expected]
    assert positions == sorted(positions)
    assert ASSUMPTIONS_HEADING in result.markdown


def test_writer_aggregates_token_counts_across_all_groups():
    fake_llm = FakeLLM(prompt_tokens=10, completion_tokens=20)
    result = write_design(
        _make_requirements(), decisions=None, llm=fake_llm, budget=_no_wait_budget()
    )

    # 4 section groups -> 4 calls, each contributing 10/20 tokens.
    assert len(fake_llm.calls) == 4
    assert result.prompt_tokens == 40
    assert result.completion_tokens == 80


def test_writer_calls_budget_record_and_wait_for_every_group():
    calls = {"waits": 0, "records": 0}

    class CountingBudget(TokenBudget):
        def wait_if_needed(self, estimated_total_tokens, estimated_output_tokens):
            calls["waits"] += 1

        def record(self, total_tokens, output_tokens):
            calls["records"] += 1

    budget = CountingBudget(
        max_total_tokens_per_minute=1_000_000,
        max_output_tokens_per_minute=1_000_000,
        clock=lambda: 0.0,
        sleep=lambda s: None,
    )
    write_design(_make_requirements(), decisions=None, llm=FakeLLM(), budget=budget)

    assert calls["waits"] == 4
    assert calls["records"] == 4


def test_writer_puts_do_not_invent_numbers_rule_in_every_prompt():
    fake_llm = FakeLLM()
    write_design(_make_requirements(), decisions=None, llm=fake_llm, budget=_no_wait_budget())

    for call in fake_llm.calls:
        assert "unspecified" in call["system"]
        assert "Never invent numbers" in call["system"]


def test_writer_puts_decision_statuses_in_the_user_message():
    decision = _make_decision(status="accepted", choice="PostgreSQL")
    fake_llm = FakeLLM()
    write_design(
        _make_requirements(), decisions=[decision], llm=fake_llm, budget=_no_wait_budget()
    )

    for call in fake_llm.calls:
        assert '"status": "accepted"' in call["user"]
        assert "PostgreSQL" in call["user"]


def test_writer_never_puts_evidence_quotes_in_any_prompt():
    # Evidence quotes are verbatim idea text -- they must never reach the
    # design-writer prompts.
    secret_quote = "zzz-raw-idea-text-that-must-never-leak-zzz"
    requirements = _make_requirements(evidence={"authentication": secret_quote})
    fake_llm = FakeLLM()
    write_design(requirements, decisions=None, llm=fake_llm, budget=_no_wait_budget())

    for call in fake_llm.calls:
        assert secret_quote not in call["system"]
        assert secret_quote not in call["user"]


def test_writer_works_when_decisions_is_none():
    fake_llm = FakeLLM()
    result = write_design(
        _make_requirements(), decisions=None, llm=fake_llm, budget=_no_wait_budget()
    )
    assert result.markdown  # did not crash, produced something
    for call in fake_llm.calls:
        assert "chosen by the model" in call["system"]


def test_writer_assumptions_section_groups_uncertain_decision_and_extra_unknown():
    # Section 13's format changed to grouped plain-word sub-sections (see
    # writer._build_assumptions_section); the old "- Open: <question> (<status>, <p>%)"
    # format and assertion no longer apply.
    requirements = _make_requirements(unknowns=["payments not specified"])
    open_decision = _make_decision(
        id="cache_needed",
        question="Does this project need a caching layer?",
        status="uncertain",
        choice=None,
        probability=0.5,
        based_on_unknowns=True,
    )
    result = write_design(
        requirements, decisions=[open_decision], llm=FakeLLM(), budget=_no_wait_budget()
    )

    assert "### Unclear" in result.markdown
    assert "Caching" in result.markdown  # the label for cache_needed
    assert "cache_needed" not in result.markdown  # never the raw id
    assert "uncertain" not in result.markdown  # never the raw status word
    assert "50%" in result.markdown
    assert "### Other open questions" in result.markdown
    assert "payments not specified" in result.markdown


def test_max_tokens_defaults_to_700():
    fake_llm = FakeLLM()
    write_design(_make_requirements(), decisions=None, llm=fake_llm, budget=_no_wait_budget())
    for call in fake_llm.calls:
        assert call["max_tokens"] == 700


def test_design_max_tokens_env_var_is_respected(monkeypatch):
    monkeypatch.setenv("DESIGN_MAX_TOKENS", "123")
    fake_llm = FakeLLM()
    write_design(_make_requirements(), decisions=None, llm=fake_llm, budget=_no_wait_budget())
    for call in fake_llm.calls:
        assert call["max_tokens"] == 123


def test_rate_limit_error_propagates_out_of_write_design():
    with pytest.raises(RateLimitError):
        write_design(
            _make_requirements(), decisions=None, llm=RateLimitedLLM(), budget=_no_wait_budget()
        )


def test_group_stats_are_present_and_numeric():
    fake_llm = FakeLLM(prompt_tokens=10, completion_tokens=20)
    result = write_design(
        _make_requirements(), decisions=None, llm=fake_llm, budget=_no_wait_budget(),
        clock=lambda: 0.0,
    )

    assert len(result.group_stats) == 4
    for stat in result.group_stats:
        assert stat.id in {"g1", "g2", "g3", "g4"}
        assert stat.prompt_tokens == 10
        assert stat.completion_tokens == 20
        assert stat.retries == 0  # FakeLLM's canned text passes validation first try
        assert stat.elapsed_seconds == 0.0  # fixed fake clock
        assert stat.retry_reasons == []  # no retry -> no reasons


# ── per-group quality gate: retry / fallback / status-word safety net ──────────
# These call the internal _write_one_group directly (not the full
# write_design, which runs all 4 real section groups) so each scenario can
# target exactly one group's behavior without the other groups' output
# interfering with the assertions.

_TEST_GROUP = {
    "id": "gX",
    "sections": [
        {"heading": "## 1. Test Heading One", "guidance": "Write about one thing."},
        {"heading": "## 2. Test Heading Two", "guidance": "Write about another thing."},
    ],
}


def _long_enough_body(heading: str) -> str:
    # 85 words -- clears the 80-word minimum.
    return heading + "\n" + " ".join(["word"] * 85)


class ScriptedLLM(LLMProvider):
    """Returns one canned response per call, in the given order."""

    def __init__(self, responses: list[str]) -> None:
        self.calls: list[dict] = []
        self._responses = list(responses)

    def complete_json(self, system: str, user: str, max_tokens: int) -> LLMResult:
        raise NotImplementedError

    def complete_text(self, system: str, user: str, max_tokens: int) -> LLMResult:
        self.calls.append({"system": system, "user": user, "max_tokens": max_tokens})
        return LLMResult(text=self._responses.pop(0), prompt_tokens=10, completion_tokens=20)


def _group_budget() -> TokenBudget:
    return TokenBudget(
        max_total_tokens_per_minute=10**9,
        max_output_tokens_per_minute=10**9,
        clock=lambda: 0.0,
        sleep=lambda s: None,
    )


def test_group_with_missing_heading_triggers_exactly_one_retry():
    first_try = _long_enough_body("## 1. Test Heading One")  # heading 2 missing
    second_try = "\n\n".join(
        _long_enough_body(h) for h in ["## 1. Test Heading One", "## 2. Test Heading Two"]
    )
    llm = ScriptedLLM([first_try, second_try])

    markdown, warnings, stats = writer_module._write_one_group(
        _TEST_GROUP, "user message", llm, _group_budget(), 700, False, None, lambda: 0.0
    )

    assert len(llm.calls) == 2  # exactly one retry
    assert stats.retries == 1
    assert "## 2. Test Heading Two" in markdown
    assert warnings == []  # the retry succeeded -- no fallback needed
    assert stats.retry_reasons == ["missing_heading"]  # category word, never prose


def test_group_with_placeholder_text_triggers_retry():
    first_try = "\n\n".join([
        _long_enough_body("## 1. Test Heading One"),
        "## 2. Test Heading Two\n" + " ".join(["word"] * 85) + " TBD",
    ])
    second_try = "\n\n".join(
        _long_enough_body(h) for h in ["## 1. Test Heading One", "## 2. Test Heading Two"]
    )
    llm = ScriptedLLM([first_try, second_try])

    markdown, warnings, stats = writer_module._write_one_group(
        _TEST_GROUP, "user message", llm, _group_budget(), 700, False, None, lambda: 0.0
    )

    assert len(llm.calls) == 2
    assert stats.retries == 1
    assert "TBD" not in markdown
    assert warnings == []
    assert stats.retry_reasons == ["placeholder"]


def test_still_bad_group_gets_fallback_line_and_warning():
    # Heading 2 is missing both times -- the retry doesn't fix it.
    always_bad = _long_enough_body("## 1. Test Heading One")
    llm = ScriptedLLM([always_bad, always_bad])

    markdown, warnings, stats = writer_module._write_one_group(
        _TEST_GROUP, "user message", llm, _group_budget(), 700, False, None, lambda: 0.0
    )

    assert len(llm.calls) == 2  # original + one retry, never more
    assert stats.retries == 1
    assert writer_module.FALLBACK_LINE in markdown
    assert any("## 2. Test Heading Two" in w for w in warnings)
    assert any("missing heading" in w for w in warnings)
    assert stats.retry_reasons == ["missing_heading"]  # reasons from the pre-retry failure


def test_retry_reasons_lists_one_category_word_per_failed_check():
    # Heading 1 too short AND heading 2 missing -- both failures land in
    # retry_reasons, as category words only (never the retry_text prose).
    first_try = "## 1. Test Heading One\n" + " ".join(["word"] * 5)  # too short, heading 2 missing
    second_try = "\n\n".join(
        _long_enough_body(h) for h in ["## 1. Test Heading One", "## 2. Test Heading Two"]
    )
    llm = ScriptedLLM([first_try, second_try])

    _markdown, _warnings, stats = writer_module._write_one_group(
        _TEST_GROUP, "user message", llm, _group_budget(), 700, False, None, lambda: 0.0
    )

    assert stats.retries == 1
    assert sorted(stats.retry_reasons) == ["missing_heading", "too_short"]
    for reason in stats.retry_reasons:
        assert " " not in reason  # category words only, never prose with spaces


def test_ordinary_status_words_are_never_rewritten():
    # A past version of the safety net blindly rewrote yes/no/accepted/
    # tentative/uncertain and mangled ordinary sentences (e.g. "no
    # background processing occurs" became "not required background
    # processing occurs"). It must now leave these words alone -- tested
    # directly against the replace function, which is where the bug was.
    text = (
        "The choice was accepted and the plan is tentative, so the answer "
        "is yes. This part is uncertain, and the answer is no background "
        "processing occurs."
    )
    replaced = writer_module._replace_leftover_identifiers(text)
    assert replaced == text  # unchanged -- no ordinary word was touched


def test_underscore_identifiers_and_decision_status_phrase_are_rewritten():
    text = "This is still needs_review and based_on_unknowns and the decision status is open."
    replaced = writer_module._replace_leftover_identifiers(text)
    assert "needs_review" not in replaced
    assert "based_on_unknowns" not in replaced
    assert "decision status" not in replaced
    assert "not yet decided" in replaced
    assert "depends on an unspecified requirement" in replaced


def test_project_summary_is_never_in_any_group_prompt():
    # project_summary is free text and can smuggle in a guessed platform
    # word (e.g. "a mobile app for..."), so it must never reach the prompt.
    secret_summary = "zzz-unique-project-summary-marker-zzz"
    requirements = _make_requirements(project_summary=secret_summary)
    fake_llm = FakeLLM()
    write_design(requirements, decisions=None, llm=fake_llm, budget=_no_wait_budget())

    for call in fake_llm.calls:
        assert secret_summary not in call["system"]
        assert secret_summary not in call["user"]


def test_app_type_none_adds_client_application_rule_to_prompt():
    requirements = _make_requirements(app_type=None)
    fake_llm = FakeLLM()
    write_design(requirements, decisions=None, llm=fake_llm, budget=_no_wait_budget())

    for call in fake_llm.calls:
        assert "client application" in call["system"]


def test_app_type_set_does_not_add_client_application_rule():
    requirements = _make_requirements(app_type="web")
    fake_llm = FakeLLM()
    write_design(requirements, decisions=None, llm=fake_llm, budget=_no_wait_budget())

    for call in fake_llm.calls:
        assert "client application" not in call["system"]


def test_platform_assumed_warning_when_app_type_none_but_text_guesses_platform():
    class GuessyLLM(LLMProvider):
        def complete_json(self, system, user, max_tokens):
            raise NotImplementedError

        def complete_text(self, system, user, max_tokens):
            headings = re.findall(r"^## \d+\..*$", system, re.MULTILINE)
            filler = " ".join(["word"] * 85) + " This looks like a mobile app."
            body = "\n\n".join(f"{heading}\n{filler}" for heading in headings)
            return LLMResult(text=body, prompt_tokens=10, completion_tokens=20)

    requirements = _make_requirements(app_type=None)
    result = write_design(
        requirements, decisions=None, llm=GuessyLLM(), budget=_no_wait_budget()
    )

    assert "platform assumed" in result.warnings


def test_no_platform_assumed_warning_when_app_type_is_set():
    class GuessyLLM(LLMProvider):
        def complete_json(self, system, user, max_tokens):
            raise NotImplementedError

        def complete_text(self, system, user, max_tokens):
            headings = re.findall(r"^## \d+\..*$", system, re.MULTILINE)
            filler = " ".join(["word"] * 85) + " This is a mobile app."
            body = "\n\n".join(f"{heading}\n{filler}" for heading in headings)
            return LLMResult(text=body, prompt_tokens=10, completion_tokens=20)

    requirements = _make_requirements(app_type="mobile")
    result = write_design(
        requirements, decisions=None, llm=GuessyLLM(), budget=_no_wait_budget()
    )

    assert "platform assumed" not in result.warnings


def test_design_min_words_env_var_is_honored(monkeypatch):
    monkeypatch.setenv("DESIGN_MIN_WORDS", "5")

    class ShortLLM(LLMProvider):
        def complete_json(self, system, user, max_tokens):
            raise NotImplementedError

        def complete_text(self, system, user, max_tokens):
            headings = re.findall(r"^## \d+\..*$", system, re.MULTILINE)
            # Only 6 words per section -- passes a 5-word minimum, would
            # have failed the old fixed 80-word minimum.
            filler = "six short words right here now"
            body = "\n\n".join(f"{heading}\n{filler}" for heading in headings)
            return LLMResult(text=body, prompt_tokens=10, completion_tokens=20)

    short_llm = ShortLLM()
    result = write_design(
        _make_requirements(), decisions=None, llm=short_llm, budget=_no_wait_budget()
    )

    assert not any("too short" in w for w in result.warnings)
    assert "six short words right here now" in result.markdown


def test_design_min_words_env_var_default_is_40(monkeypatch):
    monkeypatch.delenv("DESIGN_MIN_WORDS", raising=False)
    from app.design.sections import min_words_per_section
    assert min_words_per_section() == 40


def test_repetition_warning_for_duplicate_bullets():
    class RepeatyLLM(LLMProvider):
        def complete_json(self, system, user, max_tokens):
            raise NotImplementedError

        def complete_text(self, system, user, max_tokens):
            headings = re.findall(r"^## \d+\..*$", system, re.MULTILINE)
            filler = " ".join(["word"] * 85)
            # Section 1 repeats the exact same bullet twice.
            first_body = f"{filler}\n- Use caching for speed.\n- Use caching for speed."
            bodies = [first_body] + [filler] * (len(headings) - 1)
            text = "\n\n".join(f"{h}\n{b}" for h, b in zip(headings, bodies))
            return LLMResult(text=text, prompt_tokens=10, completion_tokens=20)

    result = write_design(
        _make_requirements(), decisions=None, llm=RepeatyLLM(), budget=_no_wait_budget()
    )

    assert any(w.startswith("repetition:") for w in result.warnings)


def test_assumptions_section_structure_for_a_mixed_set_of_decisions():
    decisions = [
        _make_decision(
            id="primary_database", status="accepted", choice="PostgreSQL",
            probability=0.9, top_alternatives=[AlternativeOut(option="PostgreSQL", probability=0.9)],
        ),
        _make_decision(
            id="api_style", status="tentative", choice="REST", probability=0.6,
            top_alternatives=[
                AlternativeOut(option="REST", probability=0.6),
                AlternativeOut(option="GraphQL", probability=0.3),
            ],
        ),
        _make_decision(
            id="cache_needed", status="uncertain", choice=None, probability=0.5,
            top_alternatives=[],
        ),
        _make_decision(
            id="async_processing_needed", status="no", choice=None, probability=0.1,
            top_alternatives=[],
        ),
        _make_decision(
            id="media_storage_approach", status="needs_review", choice=None, probability=0.0,
            top_alternatives=[],
        ),
    ]
    requirements = _make_requirements()

    section = writer_module._build_assumptions_section(requirements, decisions)

    # Grouped, in plain words, with labels -- never raw ids or status words.
    assert "### Decided" in section
    assert "Primary database: PostgreSQL (confidence 90%)" in section

    assert "### Proposed, to be confirmed" in section
    assert "API style: REST (60%); alternative: GraphQL (30%)" in section

    assert "### Unclear" in section
    assert "Caching (50% estimated likelihood needed)" in section
    assert "Media storage" in section  # needs_review -> just the label

    assert "Judged not needed: Asynchronous processing (estimated 10% likelihood it is needed)" in section

    for raw_id in (
        "primary_database", "api_style", "cache_needed",
        "async_processing_needed", "media_storage_approach",
    ):
        assert raw_id not in section
    for raw_status in ("accepted", "tentative", "uncertain", "needs_review"):
        assert raw_status not in section.lower()


def test_assumptions_section_omits_empty_subsections_when_some_have_entries():
    # Was: every empty subsection printed "- None." / "- None yet." -- now
    # an empty subsection is omitted entirely rather than printed as filler.
    decisions = [
        _make_decision(id="api_style", status="accepted", choice="REST", probability=0.9),
    ]
    requirements = _make_requirements(
        expected_scale=ExpectedScale(users="1000", peak_requests_per_second="10", data_volume="1GB"),
    )  # no unspecified fields this decision depends on, no unknowns

    section = writer_module._build_assumptions_section(requirements, decisions)

    assert "### Decided" in section
    assert "- None." not in section
    assert "- None yet." not in section
    assert "### Proposed, to be confirmed" not in section
    assert "### Unclear" not in section
    assert "### Depends on unspecified requirements" not in section
    assert "### Other open questions" not in section


def test_assumptions_section_all_empty_prints_the_single_fallback_line():
    requirements = _make_requirements()  # nothing unspecified, no unknowns
    section = writer_module._build_assumptions_section(requirements, decisions=[])

    assert section == f"{ASSUMPTIONS_HEADING}\n\nNo open questions were recorded."


def test_assumptions_section_llm_only_lists_unspecified_fields_and_unknowns():
    # llm_only mode (decisions=None): no decisions exist to say "affects X",
    # so unspecified fields are listed directly, same subsection headings
    # as pipeline mode.
    requirements = _make_requirements(
        authentication=None, unknowns=["payments not specified"],
    )

    section = writer_module._build_assumptions_section(requirements, decisions=None)

    assert "### Depends on unspecified requirements" in section
    assert "- Authentication" in section
    assert "affects" not in section  # no decisions to attribute it to
    assert "### Other open questions" in section
    assert "payments not specified" in section
    assert "### Decided" not in section
    assert "### Proposed, to be confirmed" not in section
    assert "### Unclear" not in section


def test_no_idea_text_or_design_text_in_logs(caplog):
    requirements = _make_requirements(
        project_summary="A to-do app for small teams.",
        evidence={"authentication": "super secret raw idea phrase"},
    )
    fake_llm = FakeLLM()

    with caplog.at_level(logging.DEBUG):
        result = write_design(
            requirements, decisions=None, llm=fake_llm, budget=_no_wait_budget()
        )

    for record in caplog.records:
        message = record.getMessage()
        assert "super secret raw idea phrase" not in message
        assert "Generated text for this section" not in message
        assert result.markdown not in message
