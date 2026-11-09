"""Tests for eval/m6/score_m6.py. No network, small fixed fixtures."""

import json

import pytest

import score_m6 as sm


def _headings_markdown(sections: dict, include_13=True) -> str:
    parts = []
    for n in range(1, 13):
        parts.append(sm.all_headings()[n - 1] + "\n\n" + sections.get(n, "Some generic text here."))
    if include_13:
        parts.append(sm.all_headings()[12] + "\n\n" + sections.get(13, "Assumptions text."))
    return "\n\n".join(parts)


@pytest.fixture
def _env(tmp_path, monkeypatch):
    ideas_dir = tmp_path / "ideas"
    runs_dir = tmp_path / "runs"
    ideas_dir.mkdir()
    runs_dir.mkdir()
    (ideas_dir / "idea1.md").write_text("An idea for 1000 users and a bar finder app.", encoding="utf-8")
    monkeypatch.setattr(sm, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(sm, "DEFAULT_IDEAS_DIR", ideas_dir)
    return ideas_dir, runs_dir


def _write_run(runs_dir, run_id, meta_info, body):
    (runs_dir / f"{run_id}.json").write_text(json.dumps(body), encoding="utf-8")
    (runs_dir / f"{run_id}.meta.json").write_text(json.dumps(meta_info), encoding="utf-8")


def test_sections_found_and_fallback_lines():
    markdown = _headings_markdown({1: sm.FALLBACK_LINE, 2: sm.FALLBACK_LINE})
    body = {"design_markdown": markdown, "design_warnings": [], "meta": {}, "requirements": {}}
    result = sm._score_one_run("x", body, {"idea": "x", "version": "A", "repeat": 1}, "")
    assert result["sections_found"] == 13
    assert result["fallback_lines"] == 2


def test_placeholder_and_jargon_hits():
    markdown = _headings_markdown({1: "This is TBD and uses needs_review internally."})
    body = {"design_markdown": markdown, "design_warnings": [], "meta": {}, "requirements": {}}
    result = sm._score_one_run("x", body, {"idea": "x", "version": "A", "repeat": 1}, "")
    assert result["placeholder_hits"] >= 1
    assert result["jargon_hits"] >= 1


def test_decision_adherence_fraction_of_accepted_choices_mentioned():
    markdown = _headings_markdown({4: "We use REST for the API."})
    decisions = [
        {"id": "api_style", "status": "accepted", "choice": "REST"},
        {"id": "primary_database", "status": "accepted", "choice": "MongoDB"},
    ]
    body = {"design_markdown": markdown, "design_warnings": [], "meta": {}, "requirements": {}, "decisions": decisions}
    result = sm._score_one_run("x", body, {"idea": "x", "version": "B", "repeat": 1}, "")
    assert result["decision_adherence"] == 0.5


def test_decision_adherence_is_n_a_for_version_a():
    markdown = _headings_markdown({})
    body = {"design_markdown": markdown, "design_warnings": [], "meta": {}, "requirements": {}, "decisions": None}
    result = sm._score_one_run("x", body, {"idea": "x", "version": "A", "repeat": 1}, "")
    assert result["decision_adherence"] == "n/a"


def test_tech_choices_picks_most_mentioned_term_per_category():
    markdown = _headings_markdown({4: "REST REST REST GraphQL", 5: "MongoDB", 1: "microservices microservices"})
    body = {"design_markdown": markdown, "design_warnings": [], "meta": {}, "requirements": {}}
    result = sm._score_one_run("x", body, {"idea": "x", "version": "A", "repeat": 1}, "")
    assert result["tech_choices"]["api_style"] == "REST"
    assert result["tech_choices"]["database"] == "MongoDB"
    assert result["tech_choices"]["architecture"] == "microservices"


def test_tech_choices_is_mixed_on_a_tie_and_none_on_no_mention():
    # Was "none" on a tie -- the new spec gives "mixed" for a real tie and
    # reserves "none" for zero mentions only.
    markdown = _headings_markdown({4: "REST GraphQL"})  # 1 mention each -- a tie
    body = {"design_markdown": markdown, "design_warnings": [], "meta": {}, "requirements": {}}
    result = sm._score_one_run("x", body, {"idea": "x", "version": "A", "repeat": 1}, "")
    assert result["tech_choices"]["api_style"] == "mixed"
    assert result["tech_choices"]["database"] == "none"  # never mentioned


def test_restful_and_rest_api_both_count_as_rest():
    markdown = _headings_markdown({4: "Uses a RESTful style with a REST API and REST-based endpoints."})
    body = {"design_markdown": markdown, "design_warnings": [], "meta": {}, "requirements": {}}
    result = sm._score_one_run("x", body, {"idea": "x", "version": "A", "repeat": 1}, "")
    assert result["tech_choices"]["api_style"] == "REST"
    assert result["tech_counts"]["api_style"]["REST"] == 3


def test_modular_monolith_is_not_also_counted_as_plain_monolith():
    markdown = _headings_markdown({1: "A modular monolith architecture, not a plain monolith elsewhere."})
    body = {"design_markdown": markdown, "design_warnings": [], "meta": {}, "requirements": {}}
    result = sm._score_one_run("x", body, {"idea": "x", "version": "A", "repeat": 1}, "")
    assert result["tech_counts"]["architecture"]["modular monolith"] == 1
    assert result["tech_counts"]["architecture"]["monolith"] == 1  # only the standalone mention
    assert result["tech_choices"]["architecture"] == "mixed"  # 1 vs 1 -- a real tie


def test_database_synonyms_postgres_and_postgis_count_toward_postgresql():
    markdown = _headings_markdown({5: "Postgres with PostGIS for geospatial queries."})
    body = {"design_markdown": markdown, "design_warnings": [], "meta": {}, "requirements": {}}
    result = sm._score_one_run("x", body, {"idea": "x", "version": "A", "repeat": 1}, "")
    assert result["tech_choices"]["database"] == "PostgreSQL"
    assert result["tech_counts"]["database"]["PostgreSQL"] == 2


def test_redis_is_never_counted_as_a_database():
    markdown = _headings_markdown({7: "Redis caches hot reads."})
    body = {"design_markdown": markdown, "design_warnings": [], "meta": {}, "requirements": {}}
    result = sm._score_one_run("x", body, {"idea": "x", "version": "A", "repeat": 1}, "")
    assert result["tech_choices"]["database"] == "none"
    assert "Redis" not in result["tech_counts"]["database"]


def test_numeric_claims_counts_digit_and_written_numbers_with_units():
    markdown = _headings_markdown({1: "We expect 500 users and about ten thousand requests per day."})
    body = {"design_markdown": markdown, "design_warnings": [], "meta": {}, "requirements": {"expected_scale": {}}}
    result = sm._score_one_run("x", body, {"idea": "x", "version": "A", "repeat": 1}, "no numbers here")
    assert result["numeric_claims"] == 2
    assert result["unsupported_numbers"] == 2  # neither 500 nor "ten thousand" appears in the idea


def test_numeric_claims_vs_unsupported_numbers_mixed_support():
    markdown = _headings_markdown({1: "We expect 1000 users and 500 sellers on the platform."})
    body = {"design_markdown": markdown, "design_warnings": [], "meta": {}, "requirements": {"expected_scale": {}}}
    result = sm._score_one_run("x", body, {"idea": "x", "version": "A", "repeat": 1}, "a platform for 1000 users")
    assert result["numeric_claims"] == 2       # both "1000 users" and "500 sellers" are claims
    assert result["unsupported_numbers"] == 1  # only 500 sellers is unbacked


def test_unsupported_numbers_counts_unbacked_numeric_claims():
    # "500 users" is a numeric claim; the idea/requirements never say 500.
    markdown = _headings_markdown({1: "We expect 500 users and up to 10 requests per second."})
    body = {"design_markdown": markdown, "design_warnings": [], "meta": {}, "requirements": {"expected_scale": {}}}
    result = sm._score_one_run("x", body, {"idea": "x", "version": "A", "repeat": 1}, "an idea with no numbers")
    assert result["unsupported_numbers"] == 2


def test_unsupported_numbers_excludes_a_number_backed_by_the_idea_text():
    markdown = _headings_markdown({1: "We expect 1000 users."})
    body = {"design_markdown": markdown, "design_warnings": [], "meta": {}, "requirements": {"expected_scale": {}}}
    result = sm._score_one_run("x", body, {"idea": "x", "version": "A", "repeat": 1}, "an idea for 1000 users")
    assert result["unsupported_numbers"] == 0


def test_unsupported_numbers_excludes_a_number_backed_by_requirements_scale():
    markdown = _headings_markdown({1: "We expect 2500 users."})
    body = {
        "design_markdown": markdown, "design_warnings": [], "meta": {},
        "requirements": {"expected_scale": {"users": "2500"}},
    }
    result = sm._score_one_run("x", body, {"idea": "x", "version": "A", "repeat": 1}, "no numbers here")
    assert result["unsupported_numbers"] == 0


def test_assumption_mentions_counts_the_four_tokens():
    markdown = _headings_markdown({
        1: "This is unspecified.", 2: "Not specified anywhere.",
        3: "Not stated in the idea.", 4: "We assume this is fine.",
    })
    body = {"design_markdown": markdown, "design_warnings": [], "meta": {}, "requirements": {}}
    result = sm._score_one_run("x", body, {"idea": "x", "version": "A", "repeat": 1}, "")
    assert result["assumption_mentions"] == 4


def test_leak_hits_counts_the_three_phrases_in_sections_1_to_12():
    markdown = _headings_markdown({
        1: "Decisions are provided for this project.",
        2: "There are no decisions here.",
        13: "No decisions were provided in this run.",  # section 13 -- must not count
    }, include_13=True)
    body = {"design_markdown": markdown, "design_warnings": [], "meta": {}, "requirements": {}}
    result = sm._score_one_run("x", body, {"idea": "x", "version": "A", "repeat": 1}, "")
    assert result["leak_hits"] == 2


def test_retries_and_retry_reason_counts_come_from_group_stats():
    markdown = _headings_markdown({})
    meta = {
        "design_group_stats": [
            {"id": "g1", "retries": 1, "retry_reasons": ["too_short", "jargon"]},
            {"id": "g2", "retries": 0, "retry_reasons": []},
            {"id": "g3", "retries": 1, "retry_reasons": ["too_short"]},
        ],
    }
    body = {"design_markdown": markdown, "design_warnings": [], "meta": meta, "requirements": {}}
    result = sm._score_one_run("x", body, {"idea": "x", "version": "A", "repeat": 1}, "")
    assert result["retries"] == 2
    assert result["retry_reason_counts"] == {"too_short": 2, "jargon": 1}


def test_retries_are_zero_and_empty_when_no_group_had_a_retry():
    markdown = _headings_markdown({})
    meta = {"design_group_stats": [{"id": "g1", "retries": 0, "retry_reasons": []}]}
    body = {"design_markdown": markdown, "design_warnings": [], "meta": meta, "requirements": {}}
    result = sm._score_one_run("x", body, {"idea": "x", "version": "A", "repeat": 1}, "")
    assert result["retries"] == 0
    assert result["retry_reason_counts"] == {}


def test_aggregate_sums_retry_reason_totals_per_category_across_runs(_env):
    ideas_dir, runs_dir = _env
    body_1 = {
        "design_markdown": _headings_markdown({}), "design_warnings": [], "requirements": {},
        "meta": {"llm_model": "x", "design_group_stats": [
            {"elapsed_seconds": 1.0, "retries": 1, "retry_reasons": ["too_short"]},
        ]},
    }
    body_2 = {
        "design_markdown": _headings_markdown({}), "design_warnings": [], "requirements": {},
        "meta": {"llm_model": "x", "design_group_stats": [
            {"elapsed_seconds": 1.0, "retries": 1, "retry_reasons": ["too_short", "jargon"]},
        ]},
    }
    _write_run(runs_dir, "idea1__A__r1", {"idea": "idea1", "version": "A", "repeat": 1}, body_1)
    _write_run(runs_dir, "idea1__A__r2", {"idea": "idea1", "version": "A", "repeat": 2}, body_2)

    data = sm.score(ideas_dir=ideas_dir, runs_dir=runs_dir)

    assert data["aggregate"]["A"]["retry_reason_totals"] == {"too_short": 2, "jargon": 1}


def test_cost_and_time_for_version_a_has_zero_jev_requests():
    markdown = _headings_markdown({})
    meta = {
        "design_prompt_tokens": 100, "design_completion_tokens": 200,
        "design_group_stats": [{"elapsed_seconds": 1.5}, {"elapsed_seconds": 2.5}],
    }
    body = {"design_markdown": markdown, "design_warnings": [], "meta": meta, "requirements": {}}
    result = sm._score_one_run("x", body, {"idea": "x", "version": "A", "repeat": 1}, "")
    assert result["jev_requests"] == 0
    assert result["elapsed_seconds"] == 4.0
    assert result["design_prompt_tokens"] == 100


def test_cost_and_time_for_version_b_counts_decide_plus_validation_calls():
    markdown = _headings_markdown({})
    meta = {
        "input_tokens": 5, "output_tokens": 5, "validation_calls": 2,
        "validation_input_tokens": 10, "validation_output_tokens": 10,
    }
    body = {"design_markdown": markdown, "design_warnings": [], "meta": meta, "requirements": {}, "validation": []}
    result = sm._score_one_run("x", body, {"idea": "x", "version": "B", "repeat": 1}, "")
    assert result["jev_requests"] == 3  # 1 decide + 2 validation_calls
    assert result["jev_input_tokens"] == 15
    assert result["jev_output_tokens"] == 15


def test_flagged_and_possible_ids_only_computed_for_version_b():
    markdown = _headings_markdown({})
    validation = [
        {"id": "val_auth", "status": "flagged"},
        {"id": "val_contradiction", "status": "possible"},
        {"id": "val_scale", "status": "ok"},
    ]
    body = {"design_markdown": markdown, "design_warnings": [], "meta": {}, "requirements": {}, "validation": validation}
    result = sm._score_one_run("x", body, {"idea": "x", "version": "B", "repeat": 1}, "")
    assert result["flagged_ids"] == ["val_auth"]
    assert result["possible_ids"] == ["val_contradiction"]


def test_score_ignores_a_run_that_fails_the_real_run_check(_env):
    ideas_dir, runs_dir = _env
    markdown = _headings_markdown({})
    fake_body = {
        "design_markdown": markdown, "design_warnings": [], "requirements": {},
        "meta": {"decision_model": "fake (demo only)", "validation_model": "fake (demo only)",
                  "validation_input_tokens": 10, "validation_status": "flagged"},
    }
    _write_run(runs_dir, "idea1__B__r1", {"idea": "idea1", "version": "B", "repeat": 1}, fake_body)

    data = sm.score(ideas_dir=ideas_dir, runs_dir=runs_dir)

    assert data["ignored"] == ["idea1__B__r1"]
    assert data["runs"] == []


def test_score_aggregates_mean_and_n(_env):
    ideas_dir, runs_dir = _env
    a_body = {
        "design_markdown": _headings_markdown({}), "design_warnings": [], "requirements": {},
        "meta": {"llm_model": "x", "design_group_stats": [{"elapsed_seconds": 1.0}],
                  "design_prompt_tokens": 10, "design_completion_tokens": 10},
    }
    _write_run(runs_dir, "idea1__A__r1", {"idea": "idea1", "version": "A", "repeat": 1}, a_body)
    _write_run(runs_dir, "idea1__A__r2", {"idea": "idea1", "version": "A", "repeat": 2}, a_body)

    data = sm.score(ideas_dir=ideas_dir, runs_dir=runs_dir)

    assert data["aggregate"]["A"]["n"] == 2
    assert data["aggregate"]["A"]["design_prompt_tokens"] == 10


def test_consistency_is_n_a_with_only_one_repeat(_env):
    ideas_dir, runs_dir = _env
    a_body = {
        "design_markdown": _headings_markdown({}), "design_warnings": [], "requirements": {},
        "meta": {"llm_model": "x", "design_group_stats": [{"elapsed_seconds": 1.0}]},
    }
    _write_run(runs_dir, "idea1__A__r1", {"idea": "idea1", "version": "A", "repeat": 1}, a_body)

    data = sm.score(ideas_dir=ideas_dir, runs_dir=runs_dir)

    assert data["consistency"][("idea1", "A")] == "n/a"


def test_consistency_is_full_fraction_when_tech_choices_identical(_env):
    ideas_dir, runs_dir = _env
    a_body = {
        "design_markdown": _headings_markdown({4: "REST", 5: "MongoDB", 1: "monolith"}),
        "design_warnings": [], "requirements": {},
        "meta": {"llm_model": "x", "design_group_stats": [{"elapsed_seconds": 1.0}]},
    }
    _write_run(runs_dir, "idea1__A__r1", {"idea": "idea1", "version": "A", "repeat": 1}, a_body)
    _write_run(runs_dir, "idea1__A__r2", {"idea": "idea1", "version": "A", "repeat": 2}, a_body)

    data = sm.score(ideas_dir=ideas_dir, runs_dir=runs_dir)

    assert data["consistency"][("idea1", "A")] == 1.0


def test_render_report_is_ascii_and_lists_ignored(_env):
    ideas_dir, runs_dir = _env
    fake_body = {
        "design_markdown": _headings_markdown({}), "design_warnings": [], "requirements": {},
        "meta": {"decision_model": "fake (demo only)", "validation_model": "fake (demo only)",
                  "validation_input_tokens": 10, "validation_status": "flagged"},
    }
    _write_run(runs_dir, "idea1__B__r1", {"idea": "idea1", "version": "B", "repeat": 1}, fake_body)

    data = sm.score(ideas_dir=ideas_dir, runs_dir=runs_dir)
    report = sm.render_report(data)

    assert report.isascii()
    assert "idea1__B__r1" in report
