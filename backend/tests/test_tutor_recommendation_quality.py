"""Tutor 推薦品質ハーネス（Issue #180）のテスト。

実 LLM は呼ばない。固定 synthetic fixture と反実仮想で deterministic に検証する。
"""

from __future__ import annotations

import ast
import inspect
import json

import pytest
from evaluate_tutor_recommendations import (
    main,
    select_counterfactuals,
    select_fixtures,
)

from app.domain.daily_learning_plan import POLICY_VERSION as PLAN_POLICY_VERSION
from app.domain.recommendation_ranking import POLICY_VERSION as RANKING_POLICY_VERSION
from app.domain.recommendation_ranking import rank_recommendations
from app.domain.recommendation_signal import FEATURE_VERSION
from app.evaluation.recommendation_fixtures import (
    COUNTERFACTUAL_CASES,
    FIXTURE_A,
    FIXTURE_B,
    FIXTURE_C,
    FIXTURE_D,
    FIXTURE_E,
    FIXTURE_F,
    FIXTURE_INV,
    RECOMMENDATION_QUALITY_FIXTURES,
    get_counterfactual,
    get_fixture,
)
from app.evaluation.recommendation_quality import (
    evaluate_all_counterfactuals,
    evaluate_all_scenarios,
    evaluate_counterfactual,
    evaluate_learner_scenario,
    format_text_report,
    reports_failed,
    reports_to_json,
)


def test_lettered_fixtures_exist() -> None:
    ids = [row.fixture_id for row in RECOMMENDATION_QUALITY_FIXTURES]
    assert ids == ["A", "B", "C", "D", "E", "F", "INV"]
    assert get_fixture("a") is FIXTURE_A
    with pytest.raises(KeyError):
        get_fixture("Z")


@pytest.mark.parametrize(
    "scenario",
    RECOMMENDATION_QUALITY_FIXTURES,
    ids=[row.fixture_id for row in RECOMMENDATION_QUALITY_FIXTURES],
)
def test_each_fixture_passes(scenario) -> None:
    report = evaluate_learner_scenario(scenario)
    assert report.passed, report.issues
    assert report.policy_snapshot.feature_version == FEATURE_VERSION
    assert report.policy_snapshot.ranking_policy_version == RANKING_POLICY_VERSION
    assert report.policy_snapshot.plan_policy_version == PLAN_POLICY_VERSION
    assert report.policy_snapshot.ranked


@pytest.mark.parametrize(
    "case",
    COUNTERFACTUAL_CASES,
    ids=[row.case_id for row in COUNTERFACTUAL_CASES],
)
def test_each_counterfactual_moves_in_expected_direction(case) -> None:
    report = evaluate_counterfactual(case)
    assert report.passed, report.detail
    assert report.feature_version == FEATURE_VERSION
    assert report.ranking_policy_version == RANKING_POLICY_VERSION
    assert report.mutated_ranked


def test_overdue_beats_high_interest_new() -> None:
    report = evaluate_learner_scenario(FIXTURE_A)
    assert report.passed
    ranked = rank_recommendations(FIXTURE_A.snapshots)
    assert ranked[0].learning_item_id == "item-overdue"
    assert ranked[0].activity_kind == "review"


def test_production_gap_and_recent_error_reasons() -> None:
    report = evaluate_learner_scenario(FIXTURE_B)
    assert report.passed
    production = next(
        row
        for row in report.policy_snapshot.ranked
        if row.skill_direction == "production"
    )
    assert "PRODUCTION_WEAKER" in production.reason_codes
    assert "RECENT_ERROR" in production.reason_codes


def test_recent_error_raises_priority() -> None:
    report = evaluate_learner_scenario(FIXTURE_C)
    assert report.passed
    review_ids = [
        row.learning_item_id
        for row in report.policy_snapshot.ranked
        if row.activity_kind == "review"
    ]
    assert review_ids[0] == "item-errored"


def test_level_fit_does_not_exclude_far_or_unknown() -> None:
    report = evaluate_learner_scenario(FIXTURE_D)
    assert report.passed
    ids = {row.learning_item_id for row in report.policy_snapshot.ranked}
    assert {"item-a1", "item-a2", "item-b2", "item-unknown"} <= ids
    unknown = next(
        row
        for row in report.policy_snapshot.ranked
        if row.learning_item_id == "item-unknown"
        and row.skill_direction == "recognition"
    )
    assert "LEVEL_FIT" not in unknown.reason_codes
    assert "LOW_MASTERY" not in unknown.reason_codes


def test_due_overload_fills_with_reviews_only() -> None:
    report = evaluate_learner_scenario(FIXTURE_E)
    assert report.passed
    snap = report.policy_snapshot
    assert snap.review_count == 10
    assert snap.new_count == 0
    assert snap.deferred_due_count == 5


def test_due_under_capacity_adds_new_without_inflation() -> None:
    report = evaluate_learner_scenario(FIXTURE_F)
    assert report.passed
    snap = report.policy_snapshot
    assert snap.review_count == 4
    assert snap.new_count == 3
    assert snap.deferred_due_count == 0
    new_ids = [
        row.learning_item_id
        for row in snap.plan_entries or ()
        if row.activity_kind == "new_practice"
    ]
    assert len(new_ids) == len(set(new_ids)) == 3


def test_inactive_mastered_and_unsupported_are_skipped() -> None:
    report = evaluate_learner_scenario(FIXTURE_INV)
    assert report.passed
    selected = {
        row.learning_item_id for row in report.policy_snapshot.plan_entries or ()
    }
    assert selected == {"item-active"}
    assert report.policy_snapshot.deferred_due_count == 3


def test_neutral_interest_does_not_emit_high_interest() -> None:
    case = get_counterfactual("interest-neutral-to-high")
    baseline = rank_recommendations(case.baseline_snapshots)
    for row in baseline:
        assert "HIGH_INTEREST" not in row.score.reason_codes


def test_recognition_error_does_not_fabricate_production_recent_error() -> None:
    report = evaluate_learner_scenario(FIXTURE_C)
    production = [
        row
        for row in report.policy_snapshot.ranked
        if (
            row.learning_item_id == "item-errored"
            and row.skill_direction == "production"
        )
    ]
    assert production == []
    clean_prod = [
        row
        for row in report.policy_snapshot.ranked
        if row.learning_item_id == "item-errored"
    ]
    assert all(row.skill_direction == "recognition" for row in clean_prod)


def test_policy_snapshot_is_serializable() -> None:
    scenarios = evaluate_all_scenarios(RECOMMENDATION_QUALITY_FIXTURES)
    counterfactuals = evaluate_all_counterfactuals(COUNTERFACTUAL_CASES)
    payload = json.loads(reports_to_json(scenarios, counterfactuals))
    assert payload["feature_version"] == FEATURE_VERSION
    assert payload["ranking_policy_version"] == RANKING_POLICY_VERSION
    assert payload["plan_policy_version"] == PLAN_POLICY_VERSION
    assert {row["fixture_id"] for row in payload["scenarios"]} == {
        "A",
        "B",
        "C",
        "D",
        "E",
        "F",
        "INV",
    }
    assert payload["counterfactuals"]
    text = format_text_report(scenarios, counterfactuals)
    assert FEATURE_VERSION in text
    assert RANKING_POLICY_VERSION in text
    assert "fixture A" in text
    assert reports_failed(scenarios) is False
    assert reports_failed(counterfactuals) is False


def test_script_helpers_and_main_json(capsys) -> None:
    assert select_fixtures("all") == RECOMMENDATION_QUALITY_FIXTURES
    assert select_fixtures("b")[0] is FIXTURE_B
    assert select_counterfactuals("all", include=True) == COUNTERFACTUAL_CASES
    assert select_counterfactuals("A", include=True)
    assert select_counterfactuals("B", include=True) == ()
    assert select_counterfactuals("all", include=False) == ()
    exit_code = main(["--fixture", "A", "--json", "--strict"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["scenarios"][0]["fixture_id"] == "A"
    assert payload["scenarios"][0]["policy_snapshot"]["ranked"]


def test_quality_modules_do_not_import_llm() -> None:
    import app.evaluation.recommendation_fixtures as fixtures_module
    import app.evaluation.recommendation_quality as quality_module

    forbidden = {"openai", "anthropic", "langchain", "litellm"}
    for module in (fixtures_module, quality_module):
        tree = ast.parse(inspect.getsource(module))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".", 1)[0])
        assert not (names & forbidden)
