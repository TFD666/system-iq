"""
Tests for app/validation/revise.py -- uses a scripted FakeLLM (no real
network) that echoes back whichever headings a call's system prompt asks
for, same pattern as test_design_writer.py.
"""

import re

from app.design.limiter import TokenBudget
from app.design.sections import all_headings
from app.llm import LLMProvider, LLMResult
from app.schemas import AlternativeOut, DecisionResultOut, ExpectedScale, Requirements
from app.validation.policy import ValidationResult
from app.validation.revise import revise_sections


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


def _good_body() -> str:
    return " ".join(["word"] * 85)  # clears the 40-word default minimum with margin


def _revised_body() -> str:
    # Different filler words than _good_body() -- clears the 25% word-change
    # threshold revise.py now requires before accepting a revision.
    return " ".join(["newword"] * 85)


def _original_markdown() -> str:
    # One real body per heading, including section 13.
    return "\n\n".join(f"{heading}\n{_good_body()}" for heading in all_headings())


class EchoLLM(LLMProvider):
    """Echoes back whichever headings a call's system prompt asked for."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def complete_json(self, system, user, max_tokens):
        raise NotImplementedError

    def complete_text(self, system, user, max_tokens):
        self.calls.append({"system": system, "user": user, "max_tokens": max_tokens})
        headings = re.findall(r"^## \d+\..*$", system, re.MULTILINE)
        body = "\n\n".join(f"{h}\nRevised content here. {_revised_body()}" for h in headings)
        return LLMResult(text=body, prompt_tokens=10, completion_tokens=20)


class RephraseOnlyLLM(LLMProvider):
    """Echoes back the SAME words as the original body -- barely changed."""

    def complete_json(self, system, user, max_tokens):
        raise NotImplementedError

    def complete_text(self, system, user, max_tokens):
        headings = re.findall(r"^## \d+\..*$", system, re.MULTILINE)
        return LLMResult(
            text="\n\n".join(f"{h}\n{_good_body()}" for h in headings),
            prompt_tokens=10, completion_tokens=20,
        )


class NewComponentLLM(LLMProvider):
    """Revises with enough new words AND a new bolded component name."""

    def complete_json(self, system, user, max_tokens):
        raise NotImplementedError

    def complete_text(self, system, user, max_tokens):
        headings = re.findall(r"^## \d+\..*$", system, re.MULTILINE)
        body = "\n\n".join(
            f"{h}\n**Notification Service**: sends alerts. {_revised_body()}" for h in headings
        )
        return LLMResult(text=body, prompt_tokens=10, completion_tokens=20)


class AlwaysBadLLM(LLMProvider):
    """Never writes the requested headings -- always fails the quality gate."""

    def complete_json(self, system, user, max_tokens):
        raise NotImplementedError

    def complete_text(self, system, user, max_tokens):
        return LLMResult(text="nothing useful", prompt_tokens=5, completion_tokens=5)


def _budget() -> TokenBudget:
    return TokenBudget(
        max_total_tokens_per_minute=10**9,
        max_output_tokens_per_minute=10**9,
        clock=lambda: 0.0,
        sleep=lambda s: None,
    )


def _flagged(section_numbers: list[int], question_id: str = "val_geospatial") -> list[ValidationResult]:
    return [ValidationResult(id=question_id, text="Is it?", probability=0.1, status="flagged", sections=section_numbers)]


def test_revision_touches_only_the_mapped_sections():
    original = _original_markdown()
    new_markdown, revised_numbers, warnings = revise_sections(
        original, _flagged([4, 5]), _make_requirements(), None, EchoLLM(), _budget(),
    )

    assert revised_numbers == [4, 5]
    assert warnings == []
    assert "Revised content here." in new_markdown

    # Every OTHER section is byte-identical to the original.
    from app.design.checks import split_into_sections
    headings = all_headings()
    old_bodies = split_into_sections(original, headings)
    new_bodies = split_into_sections(new_markdown, headings)
    for heading in headings:
        if heading in ("## 4. API architecture", "## 5. Database architecture and data model"):
            continue
        assert new_bodies[heading] == old_bodies[heading]


def test_revision_never_touches_section_13():
    original = _original_markdown()
    # Sections span 1-13, but revise_sections must drop 13.
    new_markdown, revised_numbers, warnings = revise_sections(
        original, _flagged(list(range(1, 14))), _make_requirements(), None, EchoLLM(), _budget(),
    )
    assert 13 not in revised_numbers
    from app.design.checks import split_into_sections
    headings = all_headings()
    old_bodies = split_into_sections(original, headings)
    new_bodies = split_into_sections(new_markdown, headings)
    assert new_bodies["## 13. Assumptions and open questions"] == old_bodies["## 13. Assumptions and open questions"]


def test_no_flagged_sections_means_no_revision():
    original = _original_markdown()
    new_markdown, revised_numbers, warnings = revise_sections(
        original, [], _make_requirements(), None, EchoLLM(), _budget(),
    )
    assert new_markdown == original
    assert revised_numbers == []
    assert warnings == []


def test_quality_gate_failure_keeps_old_text_and_warns():
    original = _original_markdown()
    new_markdown, revised_numbers, warnings = revise_sections(
        original, _flagged([1]), _make_requirements(), None, AlwaysBadLLM(), _budget(),
    )

    assert revised_numbers == []
    assert any("quality gate failed" in w for w in warnings)

    from app.design.checks import split_into_sections
    headings = all_headings()
    old_bodies = split_into_sections(original, headings)
    new_bodies = split_into_sections(new_markdown, headings)
    assert new_bodies["## 1. Architecture overview"] == old_bodies["## 1. Architecture overview"]


def test_more_than_three_sections_are_split_into_multiple_calls():
    original = _original_markdown()
    llm = EchoLLM()
    new_markdown, revised_numbers, warnings = revise_sections(
        original, _flagged([1, 2, 3, 4, 5]), _make_requirements(), None, llm, _budget(),
    )
    assert revised_numbers == [1, 2, 3, 4, 5]
    assert len(llm.calls) == 2  # 3 sections + 2 sections = 2 calls


def test_rephrase_only_revision_is_rejected_and_warns():
    original = _original_markdown()
    new_markdown, revised_numbers, warnings = revise_sections(
        original, _flagged([1]), _make_requirements(), None, RephraseOnlyLLM(), _budget(),
    )
    assert revised_numbers == []
    assert any("revision no change" in w for w in warnings)
    from app.design.checks import split_into_sections
    headings = all_headings()
    old_bodies = split_into_sections(original, headings)
    new_bodies = split_into_sections(new_markdown, headings)
    assert new_bodies["## 1. Architecture overview"] == old_bodies["## 1. Architecture overview"]


def test_missing_component_revision_without_a_new_component_is_rejected():
    original = _original_markdown()
    new_markdown, revised_numbers, warnings = revise_sections(
        original, _flagged([2, 8], question_id="val_missing_component"),
        _make_requirements(), None, EchoLLM(), _budget(),
    )
    # Enough words changed, but no new component-like phrase was introduced.
    assert revised_numbers == []
    assert any("revision no change: val_missing_component" in w for w in warnings)


def test_missing_component_revision_with_a_new_component_is_accepted():
    original = _original_markdown()
    new_markdown, revised_numbers, warnings = revise_sections(
        original, _flagged([2, 8], question_id="val_missing_component"),
        _make_requirements(), None, NewComponentLLM(), _budget(),
    )
    assert revised_numbers == [2, 8]
    assert warnings == []
    assert "Notification Service" in new_markdown


def test_missing_component_issue_message_tells_the_model_what_to_do():
    original = _original_markdown()
    llm = EchoLLM()
    revise_sections(
        original, _flagged([2, 8], question_id="val_missing_component"),
        _make_requirements(), None, llm, _budget(),
    )
    assert any("Identify the most likely missing component" in call["user"] for call in llm.calls)


def test_decision_choice_issue_statement_names_the_choice_not_the_id(monkeypatch):
    decision = DecisionResultOut(
        id="primary_database", question="Which database fits best?", status="accepted",
        choice="PostgreSQL", probability=0.9,
        top_alternatives=[AlternativeOut(option="PostgreSQL", probability=0.9)],
        based_on_unknowns=False,
    )
    original = _original_markdown()
    llm = EchoLLM()
    revise_sections(
        original,
        _flagged([5], question_id="val_decision_primary_database"),
        _make_requirements(), [decision], llm, _budget(),
    )
    # The plain-word issue statement names the choice and label...
    assert any("Primary database" in call["user"] for call in llm.calls)
    assert any("PostgreSQL" in call["user"] for call in llm.calls)
    # ...never the bare validation question id.
    assert not any("val_decision_primary_database" in call["user"] for call in llm.calls)
