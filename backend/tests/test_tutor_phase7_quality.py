"""Tutor 学習品質の複数日シミュレーション（Issue #206）。

実 LLM は呼ばない。固定 clock の synthetic learner で、
Phase 7 policy を組み合わせたときの不変条件を検証する。
"""

from __future__ import annotations

import ast
import inspect
import json

import pytest
from evaluate_tutor_learning_quality import main, select_scenarios

from app.domain.adaptive_plan import POLICY_VERSION as ADAPTIVE_POLICY_VERSION
from app.domain.admission_policy import (
    DUE_BACKLOG_HARD_THRESHOLD,
    DUE_BACKLOG_SOFT_THRESHOLD,
    PER_SOURCE_ADMISSION_CAP,
)
from app.domain.admission_policy import (
    POLICY_VERSION as ADMISSION_POLICY_VERSION,
)
from app.domain.context_selection import POLICY_VERSION as CONTEXT_POLICY_VERSION
from app.domain.daily_learning_plan import (
    DEFAULT_MAX_NEW_COUNT,
    DEFAULT_PLAN_SIZE,
)
from app.domain.daily_learning_plan import (
    POLICY_VERSION as PLAN_POLICY_VERSION,
)
from app.domain.known_item_policy import POLICY_VERSION as KNOWN_POLICY_VERSION
from app.domain.recommendation_ranking import POLICY_VERSION as RANKING_POLICY_VERSION
from app.domain.recommendation_signal import FEATURE_VERSION
from app.domain.weakness_pattern import PATTERN_VERSION
from app.evaluation.learning_quality import (
    evaluate_all_scenarios,
    evaluate_scenario,
    format_text_report,
    reports_failed,
    reports_to_json,
)
from app.evaluation.learning_quality_fixtures import (
    COMBINED_SCENARIO,
    LEARNING_QUALITY_SCENARIOS,
    SPARSE_SCENARIO,
    get_scenario,
)


def test_scenarios_cover_a_multi_day_horizon() -> None:
    ids = [row.scenario_id for row in LEARNING_QUALITY_SCENARIOS]
    assert ids == ["combined-21d", "sparse-errors-3d"]
    assert get_scenario("COMBINED-21D") is COMBINED_SCENARIO
    assert 7 <= len(COMBINED_SCENARIO.days) <= 30
    with pytest.raises(KeyError):
        get_scenario("missing")


def test_combined_scenario_passes() -> None:
    report = evaluate_scenario(COMBINED_SCENARIO)
    assert report.passed, report.issues
    names = [check.name for check in report.checks]
    assert "due_backlog_suppresses_new" in names
    assert "known_items_do_not_consume_new_slots" in names
    assert "context_does_not_stay_fixed" in names
    assert "production_weakness_spares_recognition" in names
    assert "load_returns_after_difficult_period" in names
    assert report.metrics.day_count == len(COMBINED_SCENARIO.days)


def test_high_due_backlog_suppresses_new_items() -> None:
    days = evaluate_scenario(COMBINED_SCENARIO).days
    soft = [day for day in days if day.due_review_count >= DUE_BACKLOG_SOFT_THRESHOLD]
    hard = [day for day in days if day.due_review_count >= DUE_BACKLOG_HARD_THRESHOLD]
    assert soft
    assert hard
    assert all(day.admission_budget <= 1 for day in soft)
    assert all(day.max_new_count <= 1 for day in soft)
    assert all(day.admitted_count == 0 and day.max_new_count == 0 for day in hard)


def test_known_items_do_not_consume_new_slots() -> None:
    report = evaluate_scenario(COMBINED_SCENARIO)
    known = COMBINED_SCENARIO.known_item_ids
    assert known
    assert report.metrics.known_skip_total > 0
    for day in report.days:
        assert set(day.admitted_ids).isdisjoint(known)
        assert set(day.new_item_ids).isdisjoint(known)


def test_one_source_does_not_fill_the_admission_budget() -> None:
    days = evaluate_scenario(COMBINED_SCENARIO).days
    pressured = False
    for day in days:
        unseen = dict(day.unseen_by_source)
        admitted = dict(day.admitted_by_source)
        for source_id, unseen_count in unseen.items():
            taken = admitted.get(source_id, 0)
            assert taken <= PER_SOURCE_ADMISSION_CAP
            if (
                source_id == "src-flood"
                and unseen_count > PER_SOURCE_ADMISSION_CAP
                and taken == PER_SOURCE_ADMISSION_CAP
                and day.admitted_count > taken
            ):
                pressured = True
    assert pressured


def test_duplicate_expression_is_not_admitted_twice() -> None:
    days = evaluate_scenario(COMBINED_SCENARIO).days
    assert any(
        dict(day.deferral_reasons).get("DUPLICATE_OR_REDUNDANT", 0) > 0 for day in days
    )
    for day in days:
        assert len(day.admitted_forms) == len(set(day.admitted_forms))


def test_context_rotates_away_from_the_same_source() -> None:
    report = evaluate_scenario(COMBINED_SCENARIO)
    assert report.metrics.repeated_same_context_rate == 0.0
    chosen: list[str] = []
    for day in report.days:
        for item_id, _exercise, source_id, count in day.context_selections:
            if item_id == "item-000-multi" and count >= 2:
                chosen.append(source_id)
    assert len(chosen) >= 2
    assert len(set(chosen)) >= 2


def test_production_weakness_does_not_mark_recognition() -> None:
    days = evaluate_scenario(COMBINED_SCENARIO).days
    assert any(day.tracked_production_weak for day in days)
    assert all(not day.tracked_recognition_weak for day in days)
    early = [
        day
        for day in days
        if day.tracked_production_attempts < 4 and day.tracked_production_weak
    ]
    assert early == []


def test_sparse_errors_do_not_declare_a_weakness() -> None:
    report = evaluate_scenario(SPARSE_SCENARIO)
    assert report.passed, report.issues
    assert report.metrics.day_count == 3
    assert report.metrics.weakness_count_per_day == (0, 0, 0)
    assert all(day.weakness_count == 0 for day in report.days)


def test_difficult_period_lowers_max_new_then_recovers() -> None:
    days = evaluate_scenario(COMBINED_SCENARIO).days
    error_days = [
        day for day in days if "RECENT_ERROR_RATE_HIGH" in day.adaptive_reasons
    ]
    assert error_days
    assert all(day.max_new_count < DEFAULT_MAX_NEW_COUNT for day in error_days)
    recovered = [
        day
        for day in days
        if day.day_index > error_days[0].day_index
        and day.adaptive_reasons == ("STABLE_PROGRESS",)
        and day.max_new_count == DEFAULT_MAX_NEW_COUNT
        and day.requested_count == DEFAULT_PLAN_SIZE
    ]
    assert recovered


def test_due_reviews_stay_ahead_of_new_items() -> None:
    for day in evaluate_scenario(COMBINED_SCENARIO).days:
        seen_new = False
        for kind in day.entry_kinds:
            if kind == "new_practice":
                seen_new = True
            elif kind == "review":
                assert not seen_new
        if day.deferred_due_count > 0:
            assert day.new_count == 0
        if day.due_review_count > 0:
            assert day.review_count > 0
        assert day.overdue_count <= day.due_review_count


def test_direction_counts_and_overdue_are_recorded() -> None:
    metrics = evaluate_scenario(COMBINED_SCENARIO).metrics
    assert metrics.recognition_count > 0
    assert metrics.production_count > 0
    assert max(metrics.overdue_per_day) >= 1
    assert len(metrics.admitted_new_per_day) == metrics.day_count
    assert len(metrics.max_new_per_day) == metrics.day_count


def test_simulation_is_deterministic() -> None:
    first = evaluate_scenario(COMBINED_SCENARIO)
    second = evaluate_scenario(COMBINED_SCENARIO)
    assert first.days == second.days
    assert first.metrics == second.metrics
    assert first.policy_versions == second.policy_versions
    sparse = evaluate_all_scenarios((SPARSE_SCENARIO, SPARSE_SCENARIO))
    assert sparse[0].days == sparse[1].days


def test_policy_versions_are_reported() -> None:
    reports = evaluate_all_scenarios(LEARNING_QUALITY_SCENARIOS)
    payload = json.loads(reports_to_json(reports))
    versions = payload["policy_versions"]
    assert versions == {
        "feature_version": FEATURE_VERSION,
        "ranking_policy_version": RANKING_POLICY_VERSION,
        "plan_policy_version": PLAN_POLICY_VERSION,
        "admission_policy_version": ADMISSION_POLICY_VERSION,
        "adaptive_load_policy_version": ADAPTIVE_POLICY_VERSION,
        "context_policy_version": CONTEXT_POLICY_VERSION,
        "weakness_pattern_version": PATTERN_VERSION,
        "known_item_policy_version": KNOWN_POLICY_VERSION,
    }
    assert {row["scenario_id"] for row in payload["scenarios"]} == {
        "combined-21d",
        "sparse-errors-3d",
    }
    text = format_text_report(reports)
    assert FEATURE_VERSION in text
    assert ADMISSION_POLICY_VERSION in text
    assert ADAPTIVE_POLICY_VERSION in text
    assert CONTEXT_POLICY_VERSION in text
    assert reports_failed(reports) is False


def test_script_json_and_strict(capsys: pytest.CaptureFixture[str]) -> None:
    assert select_scenarios("all") == LEARNING_QUALITY_SCENARIOS
    assert select_scenarios("sparse-errors-3d") == (SPARSE_SCENARIO,)
    assert main(["--scenario", "missing"]) == 2
    assert main(["--scenario", "combined-21d", "--json", "--strict"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["scenarios"][0]["scenario_id"] == "combined-21d"
    assert payload["scenarios"][0]["metrics"]["day_count"] == 21
    assert payload["policy_versions"]["plan_policy_version"] == PLAN_POLICY_VERSION


def test_quality_modules_do_not_import_llm_or_clock() -> None:
    import evaluate_tutor_learning_quality as script_module

    import app.evaluation.learning_quality as quality_module
    import app.evaluation.learning_quality_fixtures as fixtures_module

    forbidden = {"openai", "anthropic", "langchain", "litellm", "fastapi"}
    for module in (quality_module, fixtures_module, script_module):
        source = inspect.getsource(module)
        assert "datetime.now" not in source
        assert "utcnow" not in source
        tree = ast.parse(source)
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".", 1)[0])
        assert not (names & forbidden)
