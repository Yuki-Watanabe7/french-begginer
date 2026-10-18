"""学習負荷の自動調整（Issue #204）。

テスト対象: `app.domain.adaptive_plan` と TodayLearningService への接続。
OpenAI / wall clock には依存しない。件数だけを変え、Phase 5 の due 優先は維持する。
"""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.domain.adaptive_plan import (
    ADAPTIVE_DEFAULT_NEW,
    ADAPTIVE_DEFAULT_TOTAL,
    ADAPTIVE_MAX_NEW,
    ADAPTIVE_MAX_TOTAL,
    ADAPTIVE_MIN_NEW,
    ADAPTIVE_MIN_TOTAL,
    POLICY_VERSION,
    AdaptivePlanSignals,
    InvalidAdaptivePlanInputError,
    collect_adaptive_plan_signals,
    decide_adaptive_plan_constraints,
    describe_load_adjustment,
)
from app.domain.daily_learning_plan import (
    POLICY_VERSION as PLAN_POLICY_VERSION,
)
from app.domain.daily_learning_plan import (
    PlanConstraints,
    build_daily_learning_plan,
)
from app.domain.recommendation_ranking import rank_recommendations
from app.domain.recommendation_signal import (
    FEATURE_VERSION,
    DirectionSignal,
    RecommendationSignalSnapshot,
)
from app.domain.tutor import LearningEvent, LearningItem, SkillDirection
from app.repositories.sqlite import TutorSqliteStore
from app.services.today_learning_service import build_today_learning_service
from app.services.tutor_service import build_tutor_service

_NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
DUE_SOFT = 8
DUE_HARD = 16


def _decide(
    signals: AdaptivePlanSignals | None = None,
    **explicit: int,
):
    return decide_adaptive_plan_constraints(
        AdaptivePlanSignals() if signals is None else signals,
        explicit_total_count=explicit.get("total"),
        explicit_max_new_count=explicit.get("new"),
    )


def _direction(
    skill_direction: SkillDirection,
    *,
    review_urgency: str = "unscheduled",
    overdue_days: float = 0.0,
    attempt_count: int = 0,
    recent_incorrect_count: int = 0,
    recent_correct_count: int = 0,
    mastery_score: float = 0.0,
) -> DirectionSignal:
    return DirectionSignal(
        skill_direction=skill_direction,
        mastery_score=mastery_score,
        attempt_count=attempt_count,
        consecutive_correct=0,
        is_unseen=attempt_count == 0,
        review_urgency=review_urgency,  # type: ignore[arg-type]
        overdue_days=overdue_days,
        lapse_count=0,
        recent_error_rate=0.0,
        recent_incorrect_count=recent_incorrect_count,
        recent_correct_count=recent_correct_count,
    )


def _snapshot(
    item_id: str,
    *,
    recognition: DirectionSignal | None = None,
    production: DirectionSignal | None = None,
    production_gap: float | None = None,
) -> RecommendationSignalSnapshot:
    return RecommendationSignalSnapshot(
        learning_item_id=item_id,
        computed_at=_NOW,
        feature_version=FEATURE_VERSION,
        by_direction={
            "recognition": recognition or _direction("recognition"),
            "production": production or _direction("production"),
        },
        production_gap=production_gap,
        learner_level="B1",
        source_ref_count=0,
        interest_weight=1.0,
        importance_weight=1.0,
    )


def _event(
    item_id: str,
    *,
    result: str,
    occurred_at: datetime,
) -> LearningEvent:
    return LearningEvent(
        learning_item_id=item_id,
        exercise_type="meaning_recognition",
        result=result,  # type: ignore[arg-type]
        occurred_at=occurred_at,
    )


def _vocab(item_id: str) -> LearningItem:
    return LearningItem(
        id=item_id,
        item_type="vocabulary",
        canonical_form=item_id,
        meaning_ja=f"{item_id}の意味",
    )


def test_high_review_backlog_reduces_new_and_keeps_total() -> None:
    soft = _decide(AdaptivePlanSignals(due_count=DUE_SOFT, overdue_count=0))
    assert soft.max_new_count == 1
    assert soft.total_count == ADAPTIVE_DEFAULT_TOTAL
    assert soft.reason_codes == ("HIGH_REVIEW_BACKLOG",)
    assert soft.policy_version == POLICY_VERSION

    hard = _decide(AdaptivePlanSignals(due_count=DUE_HARD, overdue_count=DUE_HARD))
    assert hard.max_new_count == 0
    assert hard.total_count == ADAPTIVE_DEFAULT_TOTAL
    assert hard.reason_codes == ("HIGH_REVIEW_BACKLOG",)


def test_overdue_and_deferred_count_as_backlog() -> None:
    overdue = _decide(AdaptivePlanSignals(due_count=4, overdue_count=4))
    assert overdue.max_new_count == 1
    assert overdue.reason_codes == ("HIGH_REVIEW_BACKLOG",)

    deferred = _decide(AdaptivePlanSignals(deferred_due_count=8))
    assert deferred.max_new_count == 0
    assert deferred.total_count == ADAPTIVE_DEFAULT_TOTAL


def test_recent_error_reduces_new_without_one_answer() -> None:
    one = _decide(AdaptivePlanSignals(recent_error_rate=1.0, recent_attempt_count=1))
    assert one.max_new_count == ADAPTIVE_DEFAULT_NEW
    assert one.total_count == ADAPTIVE_DEFAULT_TOTAL
    assert one.reason_codes == ("STABLE_PROGRESS",)

    soft = _decide(AdaptivePlanSignals(recent_error_rate=0.8, recent_attempt_count=5))
    assert soft.max_new_count == 2
    assert soft.total_count == ADAPTIVE_DEFAULT_TOTAL
    assert soft.reason_codes == ("RECENT_ERROR_RATE_HIGH",)

    hard = _decide(AdaptivePlanSignals(recent_error_rate=0.8, recent_attempt_count=8))
    assert hard.max_new_count == 1
    assert hard.total_count == ADAPTIVE_DEFAULT_TOTAL


def test_repeated_difficulty_shortens_the_day_by_one_step() -> None:
    result = _decide(
        AdaptivePlanSignals(
            recent_error_rate=0.8,
            recent_attempt_count=8,
            consecutive_difficult_sessions=2,
            recent_study_volume=20,
            recent_session_count=2,
            recent_session_completion_rate=0.0,
        )
    )
    assert result.max_new_count == 1
    assert result.total_count == ADAPTIVE_DEFAULT_TOTAL - 2
    assert result.reason_codes == ("RECENT_ERROR_RATE_HIGH",)
    note = describe_load_adjustment(
        result, total_was_adaptive=True, new_was_adaptive=True
    )
    assert "最近の誤答が続いている" in note
    assert "今日の問題数も少し抑えました" in note


def test_secondary_signals_do_not_move_a_stable_day() -> None:
    result = _decide(
        AdaptivePlanSignals(
            recognition_production_imbalance=1.0,
            imbalance_sample_count=4,
            recent_study_volume=10_000,
            recent_session_count=4,
            recent_session_completion_rate=0.0,
            consecutive_difficult_sessions=1,
        )
    )
    assert result.total_count == ADAPTIVE_DEFAULT_TOTAL
    assert result.max_new_count == ADAPTIVE_DEFAULT_NEW
    assert result.reason_codes == ("STABLE_PROGRESS",)


def test_imbalance_tightens_only_an_existing_reduction() -> None:
    alone = _decide(
        AdaptivePlanSignals(
            recognition_production_imbalance=0.8,
            imbalance_sample_count=2,
        )
    )
    assert alone.max_new_count == ADAPTIVE_DEFAULT_NEW

    with_error = _decide(
        AdaptivePlanSignals(
            recent_error_rate=0.6,
            recent_attempt_count=5,
            recognition_production_imbalance=0.8,
            imbalance_sample_count=2,
        )
    )
    assert with_error.max_new_count == 1
    assert with_error.reason_codes == ("RECENT_ERROR_RATE_HIGH",)


def test_stable_progress_returns_to_the_default_budget() -> None:
    pressured = _decide(AdaptivePlanSignals(due_count=DUE_HARD, overdue_count=DUE_HARD))
    assert pressured.max_new_count == 0
    restored = _decide(
        AdaptivePlanSignals(
            recent_error_rate=0.0,
            recent_attempt_count=12,
            recent_session_completion_rate=1.0,
            recent_session_count=3,
            admission_budget=8,
        )
    )
    assert restored.total_count == ADAPTIVE_DEFAULT_TOTAL
    assert restored.max_new_count == ADAPTIVE_DEFAULT_NEW
    assert restored.reason_codes == ("STABLE_PROGRESS",)
    assert restored.total_count <= ADAPTIVE_MAX_TOTAL
    assert restored.max_new_count <= ADAPTIVE_MAX_NEW


def test_missing_history_uses_the_default_budget() -> None:
    signals = collect_adaptive_plan_signals(
        [],
        [],
        admission_budget=None,
        now=_NOW,
    )
    result = _decide(signals)
    assert signals.recent_error_rate is None
    assert signals.recent_session_completion_rate is None
    assert result.total_count == ADAPTIVE_DEFAULT_TOTAL
    assert result.max_new_count == ADAPTIVE_DEFAULT_NEW
    assert result.reason_codes == ("STABLE_PROGRESS",)
    assert (
        describe_load_adjustment(result, total_was_adaptive=True, new_was_adaptive=True)
        == ""
    )


def test_admission_budget_limits_new_without_raising_it() -> None:
    limited = _decide(AdaptivePlanSignals(admission_budget=1))
    assert limited.max_new_count == 1
    assert limited.reason_codes == ("NEW_ADMISSION_LIMITED",)

    wide = _decide(AdaptivePlanSignals(admission_budget=100))
    assert wide.max_new_count == ADAPTIVE_DEFAULT_NEW
    assert wide.reason_codes == ("STABLE_PROGRESS",)

    both = _decide(
        AdaptivePlanSignals(due_count=DUE_HARD, overdue_count=0, admission_budget=0)
    )
    assert both.max_new_count == 0
    assert both.reason_codes == ("HIGH_REVIEW_BACKLOG", "NEW_ADMISSION_LIMITED")


def test_extreme_inputs_stay_inside_the_safety_bounds() -> None:
    result = _decide(
        AdaptivePlanSignals(
            due_count=1_000_000,
            overdue_count=1_000_000,
            deferred_due_count=1_000_000,
            recent_error_rate=1.0,
            recent_attempt_count=1_000_000,
            recent_session_completion_rate=0.0,
            recent_session_count=1_000_000,
            recognition_production_imbalance=1.0,
            imbalance_sample_count=1_000_000,
            consecutive_difficult_sessions=1_000_000,
            recent_study_volume=1_000_000,
            admission_budget=0,
        )
    )
    assert ADAPTIVE_MIN_TOTAL <= result.total_count <= ADAPTIVE_MAX_TOTAL
    assert ADAPTIVE_MIN_NEW <= result.max_new_count <= ADAPTIVE_MAX_NEW
    assert result.total_count == ADAPTIVE_DEFAULT_TOTAL
    assert result.max_new_count == 0


def test_same_signals_are_deterministic() -> None:
    signals = AdaptivePlanSignals(
        due_count=9,
        overdue_count=4,
        deferred_due_count=1,
        recent_error_rate=0.8,
        recent_attempt_count=8,
        recent_session_completion_rate=0.25,
        recent_session_count=4,
        recognition_production_imbalance=-0.5,
        imbalance_sample_count=3,
        consecutive_difficult_sessions=2,
        recent_study_volume=20,
        admission_budget=2,
    )
    assert _decide(signals) == _decide(signals)


def test_explicit_counts_override_the_suggestion() -> None:
    signals = AdaptivePlanSignals(due_count=DUE_HARD, overdue_count=DUE_HARD)
    overridden = _decide(signals, total=10, new=3)
    assert overridden.total_count == 10
    assert overridden.max_new_count == 3
    assert overridden.reason_codes == ("HIGH_REVIEW_BACKLOG",)
    assert (
        describe_load_adjustment(
            overridden, total_was_adaptive=False, new_was_adaptive=False
        )
        == ""
    )

    total_only = _decide(signals, total=6)
    assert total_only.total_count == 6
    assert total_only.max_new_count == 0

    new_only = _decide(signals, new=3)
    assert new_only.total_count == ADAPTIVE_DEFAULT_TOTAL
    assert new_only.max_new_count == 3


def test_explicit_counts_outside_plan_bounds_are_rejected() -> None:
    with pytest.raises(InvalidAdaptivePlanInputError):
        _decide(total=0)
    with pytest.raises(InvalidAdaptivePlanInputError):
        _decide(total=21)
    with pytest.raises(InvalidAdaptivePlanInputError):
        _decide(new=-1)
    with pytest.raises(InvalidAdaptivePlanInputError):
        _decide(new=21)


def test_overdue_cannot_exceed_due() -> None:
    with pytest.raises(ValidationError):
        AdaptivePlanSignals(due_count=1, overdue_count=2)


def test_explicit_constraints_keep_the_phase5_plan() -> None:
    assert PLAN_POLICY_VERSION == "plan-v1"
    snapshots = [
        _snapshot(
            "due-a",
            recognition=_direction(
                "recognition",
                review_urgency="due",
                overdue_days=3,
                attempt_count=4,
                mastery_score=0.5,
            ),
        ),
        _snapshot(
            "due-b",
            recognition=_direction(
                "recognition",
                review_urgency="due",
                overdue_days=1,
                attempt_count=4,
                mastery_score=0.5,
            ),
        ),
        _snapshot("new-1"),
        _snapshot("new-2"),
        _snapshot("new-3"),
        _snapshot("new-4"),
    ]
    items = {row.learning_item_id: _vocab(row.learning_item_id) for row in snapshots}
    ranked = rank_recommendations(snapshots)
    direct = build_daily_learning_plan(
        ranked,
        items_by_id=items,
        snapshots_by_id={row.learning_item_id: row for row in snapshots},
        constraints=PlanConstraints(total_count=10, max_new_count=3),
        generated_at=_NOW,
    )
    adaptive = _decide(
        AdaptivePlanSignals(due_count=DUE_HARD, overdue_count=DUE_HARD),
        total=10,
        new=3,
    )
    via_explicit = build_daily_learning_plan(
        ranked,
        items_by_id=items,
        snapshots_by_id={row.learning_item_id: row for row in snapshots},
        constraints=PlanConstraints(
            total_count=adaptive.total_count,
            max_new_count=adaptive.max_new_count,
        ),
        generated_at=_NOW,
    )
    explicit_ids = [
        (row.learning_item_id, row.activity_kind) for row in via_explicit.entries
    ]
    direct_ids = [(row.learning_item_id, row.activity_kind) for row in direct.entries]
    assert explicit_ids == direct_ids
    assert via_explicit.review_count == 2
    assert via_explicit.new_count == 3
    assert via_explicit.entries[0].activity_kind == "review"
    assert via_explicit.policy_version == PLAN_POLICY_VERSION

    suppressed = _decide(
        AdaptivePlanSignals(due_count=DUE_HARD, overdue_count=DUE_HARD)
    )
    review_first = build_daily_learning_plan(
        ranked,
        items_by_id=items,
        snapshots_by_id={row.learning_item_id: row for row in snapshots},
        constraints=PlanConstraints(
            total_count=suppressed.total_count,
            max_new_count=suppressed.max_new_count,
        ),
        generated_at=_NOW,
    )
    assert review_first.new_count == 0
    assert review_first.review_count == 2
    assert review_first.entries[0].activity_kind == "review"


def test_collect_splits_sessions_and_ignores_missing_history() -> None:
    difficult = [
        _event("item", result="incorrect", occurred_at=_NOW - timedelta(hours=3))
        for _ in range(4)
    ]
    later = [
        _event(
            "item",
            result="incorrect",
            occurred_at=_NOW
            - timedelta(hours=3)
            + timedelta(minutes=45)
            + timedelta(seconds=1)
            + timedelta(minutes=index),
        )
        for index in range(4)
    ]
    # 45 分ちょうどは同じ session。境界の 1 秒前に古い塊を置き、続きを分ける。
    boundary = [
        _event("item", result="correct", occurred_at=_NOW - timedelta(hours=6)),
        _event(
            "item",
            result="correct",
            occurred_at=_NOW - timedelta(hours=6) + timedelta(minutes=45),
        ),
    ]
    future = [_event("item", result="incorrect", occurred_at=_NOW + timedelta(hours=1))]
    stale = [_event("item", result="incorrect", occurred_at=_NOW - timedelta(days=15))]
    signals = collect_adaptive_plan_signals(
        [
            _snapshot(
                "due",
                recognition=_direction(
                    "recognition",
                    review_urgency="due",
                    overdue_days=2,
                    recent_incorrect_count=4,
                    recent_correct_count=1,
                    attempt_count=5,
                ),
                production_gap=0.6,
            )
        ],
        [*difficult, *later, *boundary, *future, *stale],
        admission_budget=8,
        now=_NOW,
    )
    assert signals.due_count == 1
    assert signals.overdue_count == 1
    assert signals.deferred_due_count == 0
    assert signals.recent_attempt_count == 5
    assert signals.recent_error_rate == pytest.approx(4 / 5)
    assert signals.recent_session_count == 3
    assert signals.consecutive_difficult_sessions == 2
    assert signals.recent_study_volume == len(difficult) + len(later) + len(boundary)
    assert signals.imbalance_sample_count == 1
    assert signals.admission_budget == 8


def test_short_session_does_not_break_a_difficult_streak() -> None:
    first = [
        _event(
            "item",
            result="incorrect",
            occurred_at=_NOW - timedelta(hours=5, minutes=index),
        )
        for index in range(4)
    ]
    short = [_event("item", result="correct", occurred_at=_NOW - timedelta(hours=3))]
    second = [
        _event(
            "item",
            result="incorrect",
            occurred_at=_NOW - timedelta(hours=1, minutes=index),
        )
        for index in range(4)
    ]
    signals = collect_adaptive_plan_signals(
        [],
        [*first, *short, *second],
        admission_budget=None,
        now=_NOW,
    )
    assert signals.consecutive_difficult_sessions == 2
    decided = _decide(signals)
    assert decided.max_new_count == 2
    assert decided.total_count == ADAPTIVE_DEFAULT_TOTAL - 2
    assert decided.reason_codes == ("RECENT_ERROR_RATE_HIGH",)


def test_module_does_not_import_llm_or_clock() -> None:
    import app.domain.adaptive_plan as module

    source = inspect.getsource(module)
    assert "datetime.now" not in source
    assert "utcnow" not in source
    forbidden = {"openai", "fastapi", "anthropic", "langchain", "litellm"}
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".", 1)[0])
    assert not (names & forbidden)


def test_today_plan_uses_defaults_when_history_is_missing() -> None:
    store = TutorSqliteStore.in_memory()
    tutor = build_tutor_service(store, clock=lambda: _NOW)
    today = build_today_learning_service(store, clock=lambda: _NOW)
    for form, meaning in (
        ("livre", "本"),
        ("maison", "家"),
        ("chat", "猫"),
        ("chien", "犬"),
    ):
        tutor.create_item(
            item_type="vocabulary", canonical_form=form, meaning_ja=meaning
        )
    plan = today.get_plan()
    assert plan.requested_count == ADAPTIVE_DEFAULT_TOTAL
    assert plan.new_count == ADAPTIVE_DEFAULT_NEW
    assert plan.review_count == 0
    assert "減らしました" not in plan.explanation_summary


def test_repeated_errors_reduce_new_unless_counts_are_explicit() -> None:
    store = TutorSqliteStore.in_memory()
    tutor = build_tutor_service(store, clock=lambda: _NOW)
    today = build_today_learning_service(store, clock=lambda: _NOW)
    items = [
        tutor.create_item(
            item_type="vocabulary",
            canonical_form=form,
            meaning_ja=meaning,
        )
        for form, meaning in (
            ("livre", "本"),
            ("maison", "家"),
            ("chat", "猫"),
            ("chien", "犬"),
            ("eau", "水"),
        )
    ]
    answered_at = _NOW - timedelta(days=2)
    for offset in range(5):
        tutor.record_review(
            items[0].id,
            exercise_type="meaning_recognition",
            result="incorrect",
            occurred_at=answered_at + timedelta(minutes=offset),
        )
    adaptive = today.get_plan()
    explicit = today.get_plan(question_count=10, max_new_count=3)
    assert adaptive.review_count == 1
    assert adaptive.new_count == 2
    assert adaptive.requested_count == 10
    assert "最近の誤答が続いている" in adaptive.explanation_summary
    assert explicit.review_count == 1
    assert explicit.new_count == 3
    assert "最近の誤答が続いている" not in explicit.explanation_summary
    assert explicit.policy_version == PLAN_POLICY_VERSION


def test_today_plan_reduces_new_when_the_review_backlog_is_high() -> None:
    store = TutorSqliteStore.in_memory()
    tutor = build_tutor_service(store, clock=lambda: _NOW)
    today = build_today_learning_service(store, clock=lambda: _NOW)
    for index in range(DUE_SOFT):
        item = tutor.create_item(
            item_type="vocabulary",
            canonical_form=f"mot{index}",
            meaning_ja=f"語{index}",
        )
        tutor.record_review(
            item.id,
            exercise_type="meaning_recognition",
            result="incorrect",
            occurred_at=_NOW - timedelta(days=2),
        )
    for form, meaning in (("livre", "本"), ("maison", "家"), ("chat", "猫")):
        tutor.create_item(
            item_type="vocabulary", canonical_form=form, meaning_ja=meaning
        )
    adaptive = today.get_plan()
    explicit = today.get_plan(question_count=10, max_new_count=3)
    assert adaptive.review_count == DUE_SOFT
    assert adaptive.new_count == 0
    assert adaptive.requested_count == ADAPTIVE_DEFAULT_TOTAL
    assert "復習が溜まっている" in adaptive.explanation_summary
    # 明示した新規上限は自動の 0 より優先する。在庫は admission の 1 件のまま。
    assert explicit.new_count == 1
    assert "復習が溜まっている" not in explicit.explanation_summary


def test_one_incorrect_answer_does_not_shrink_today_plan() -> None:
    store = TutorSqliteStore.in_memory()
    tutor = build_tutor_service(store, clock=lambda: _NOW)
    today = build_today_learning_service(store, clock=lambda: _NOW)
    items = [
        tutor.create_item(
            item_type="vocabulary",
            canonical_form=form,
            meaning_ja=meaning,
        )
        for form, meaning in (
            ("livre", "本"),
            ("maison", "家"),
            ("chat", "猫"),
            ("chien", "犬"),
        )
    ]
    tutor.record_review(
        items[0].id,
        exercise_type="meaning_recognition",
        result="incorrect",
        occurred_at=_NOW - timedelta(days=1),
    )
    plan = today.get_plan()
    assert plan.review_count == 1
    assert plan.new_count == ADAPTIVE_DEFAULT_NEW
    assert plan.requested_count == ADAPTIVE_DEFAULT_TOTAL
    assert "減らしました" not in plan.explanation_summary
