"""Daily Learning Plan policy の単体テスト（Issue #177）。

テスト対象: `app.domain.daily_learning_plan`

固定 fixture で以下を確認する。OpenAI / wall clock 非依存。
Phase 4 の純 Review Session は混ぜない。
"""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime

import pytest

from app.domain.daily_learning_plan import (
    DEFAULT_MAX_NEW_COUNT,
    DEFAULT_PLAN_SIZE,
    PLAN_EXERCISE_PRIORITY,
    POLICY_VERSION,
    DailyLearningPlan,
    PlanConstraints,
    build_daily_learning_plan,
    is_new_practice_candidate,
    is_review_candidate,
    select_exercise_type_for,
)
from app.domain.recommendation_ranking import (
    RankedRecommendation,
    rank_recommendations,
    score_recommendation,
)
from app.domain.recommendation_signal import (
    FEATURE_VERSION,
    DirectionSignal,
    RecommendationSignalSnapshot,
)
from app.domain.tutor import LearningItem, SkillDirection, SourceRef

_NOW = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _direction(
    skill_direction: SkillDirection = "recognition",
    *,
    mastery_score: float = 0.0,
    attempt_count: int = 0,
    consecutive_correct: int = 0,
    is_unseen: bool | None = None,
    review_urgency: str = "unscheduled",
    overdue_days: float = 0.0,
    lapse_count: int = 0,
    recent_error_rate: float = 0.0,
    recent_incorrect_count: int = 0,
    recent_correct_count: int = 0,
    last_incorrect_age_days: float | None = None,
) -> DirectionSignal:
    if is_unseen is None:
        is_unseen = attempt_count == 0
    return DirectionSignal(
        skill_direction=skill_direction,
        mastery_score=mastery_score,
        attempt_count=attempt_count,
        consecutive_correct=consecutive_correct,
        is_unseen=is_unseen,
        review_urgency=review_urgency,  # type: ignore[arg-type]
        overdue_days=overdue_days,
        lapse_count=lapse_count,
        recent_error_rate=recent_error_rate,
        recent_incorrect_count=recent_incorrect_count,
        recent_correct_count=recent_correct_count,
        last_incorrect_age_days=last_incorrect_age_days,
    )


def _snapshot(
    learning_item_id: str,
    *,
    recognition: DirectionSignal | None = None,
    production: DirectionSignal | None = None,
    production_gap: float | None = None,
    item_level: str | None = None,
    learner_level: str = "B1",
    level_distance: int | None = None,
    source_recency_days: float | None = None,
    source_ref_count: int = 0,
    interest_weight: float = 1.0,
    importance_weight: float = 1.0,
) -> RecommendationSignalSnapshot:
    rec = recognition or _direction("recognition")
    prod = production or _direction("production")
    return RecommendationSignalSnapshot(
        learning_item_id=learning_item_id,
        computed_at=_NOW,
        feature_version=FEATURE_VERSION,
        by_direction={"recognition": rec, "production": prod},
        production_gap=production_gap,
        item_level=item_level,  # type: ignore[arg-type]
        learner_level=learner_level,  # type: ignore[arg-type]
        level_distance=level_distance,
        source_recency_days=source_recency_days,
        source_ref_count=source_ref_count,
        interest_weight=interest_weight,
        importance_weight=importance_weight,
    )


def _due_signal(
    direction: SkillDirection,
    *,
    overdue_days: float = 1.0,
) -> DirectionSignal:
    return _direction(
        direction,
        mastery_score=0.8,
        attempt_count=5,
        consecutive_correct=2,
        is_unseen=False,
        review_urgency="due",
        overdue_days=overdue_days,
    )


def _seen_future(direction: SkillDirection) -> DirectionSignal:
    """導入済みだが今日は due でない direction。新規にも復習にもしない。"""
    return _direction(
        direction,
        mastery_score=0.8,
        attempt_count=5,
        consecutive_correct=2,
        is_unseen=False,
        review_urgency="future",
    )


def _review_snapshot(
    item_id: str,
    *,
    overdue_days: float = 1.0,
    direction: SkillDirection = "recognition",
    both: bool = False,
) -> RecommendationSignalSnapshot:
    if both:
        rec = _due_signal("recognition", overdue_days=overdue_days)
        prod = _due_signal("production", overdue_days=overdue_days)
    elif direction == "recognition":
        rec = _due_signal("recognition", overdue_days=overdue_days)
        prod = _seen_future("production")
    else:
        rec = _seen_future("recognition")
        prod = _due_signal("production", overdue_days=overdue_days)
    return _snapshot(item_id, recognition=rec, production=prod)


def _new_snapshot(item_id: str) -> RecommendationSignalSnapshot:
    return _snapshot(item_id)


def _seen_unscheduled_snapshot(item_id: str) -> RecommendationSignalSnapshot:
    seen = _direction(
        "recognition",
        mastery_score=0.9,
        attempt_count=8,
        consecutive_correct=3,
        is_unseen=False,
        review_urgency="unscheduled",
    )
    seen_prod = _direction(
        "production",
        mastery_score=0.9,
        attempt_count=8,
        consecutive_correct=3,
        is_unseen=False,
        review_urgency="unscheduled",
    )
    return _snapshot(item_id, recognition=seen, production=seen_prod)


def _vocab(
    item_id: str,
    *,
    status: str = "active",
    source_id: str | None = None,
) -> LearningItem:
    refs: list[SourceRef] = []
    if source_id is not None:
        refs.append(SourceRef(source_document_id=source_id))
    return LearningItem(
        id=item_id,
        item_type="vocabulary",
        canonical_form=item_id,
        meaning_ja=f"{item_id}の意味",
        status=status,  # type: ignore[arg-type]
        source_refs=refs,
    )


def _grammar(item_id: str) -> LearningItem:
    """production Exercise が作れない grammar（source evidence なし）。"""
    return LearningItem(
        id=item_id,
        item_type="grammar",
        canonical_form="ne ... pas",
        meaning_ja="否定",
    )


def _conjugation_unknown(item_id: str) -> LearningItem:
    """recognition / production ともに Exercise を選べない conjugation。"""
    return LearningItem(
        id=item_id,
        item_type="conjugation",
        canonical_form="xyzverb",
        meaning_ja="未知の動詞",
    )


def _items(*rows: LearningItem) -> dict[str, LearningItem]:
    return {row.id: row for row in rows}


def _plan(
    snapshots: list[RecommendationSignalSnapshot],
    items: dict[str, LearningItem],
    *,
    total_count: int = DEFAULT_PLAN_SIZE,
    max_new_count: int = DEFAULT_MAX_NEW_COUNT,
    seed: str = "test-plan",
    pass_snapshots: bool = True,
) -> DailyLearningPlan:
    ranked = rank_recommendations(snapshots)
    return build_daily_learning_plan(
        ranked,
        items_by_id=items,
        snapshots_by_id={row.learning_item_id: row for row in snapshots}
        if pass_snapshots
        else None,
        constraints=PlanConstraints(
            total_count=total_count, max_new_count=max_new_count
        ),
        generated_at=_NOW,
        seed=seed,
    )


def _entry_ids(plan: DailyLearningPlan) -> list[tuple[str, str, str]]:
    return [
        (row.learning_item_id, row.skill_direction, row.activity_kind)
        for row in plan.entries
    ]


# ---------------------------------------------------------------------------
# 配分: due 3 / capacity 10 → due 3 + new 最大枠
# ---------------------------------------------------------------------------


class TestDueFitsThenNew:
    def test_due_three_capacity_ten_adds_max_new(self) -> None:
        snapshots = [
            _review_snapshot("due-a", overdue_days=3.0),
            _review_snapshot("due-b", overdue_days=2.0),
            _review_snapshot("due-c", overdue_days=1.0),
            _new_snapshot("new-1"),
            _new_snapshot("new-2"),
            _new_snapshot("new-3"),
            _new_snapshot("new-4"),
        ]
        item_ids = (
            "due-a",
            "due-b",
            "due-c",
            "new-1",
            "new-2",
            "new-3",
            "new-4",
        )
        items = _items(*(_vocab(item_id) for item_id in item_ids))
        plan = _plan(snapshots, items)
        assert plan.requested_count == 10
        assert plan.review_count == 3
        assert plan.new_count == DEFAULT_MAX_NEW_COUNT
        assert plan.deferred_due_count == 0
        assert len(plan.entries) == 6
        assert {row.activity_kind for row in plan.entries[:3]} == {"review"}
        assert {row.activity_kind for row in plan.entries[3:]} == {"new_practice"}
        assert plan.policy_version == POLICY_VERSION
        assert "復習 3 件" in plan.explanation_summary
        assert "新規 3 件" in plan.explanation_summary


# ---------------------------------------------------------------------------
# due 12 / capacity 10 → review のみ 10
# ---------------------------------------------------------------------------


class TestDueExceedsCapacity:
    def test_due_twelve_capacity_ten_is_review_only(self) -> None:
        snapshots = [
            _review_snapshot(f"due-{i}", overdue_days=float(12 - i)) for i in range(12)
        ]
        items = _items(*(_vocab(f"due-{i}") for i in range(12)))
        plan = _plan(snapshots, items, total_count=10, max_new_count=3)
        assert plan.review_count == 10
        assert plan.new_count == 0
        assert plan.deferred_due_count == 2
        assert all(row.activity_kind == "review" for row in plan.entries)
        assert "復習だけで埋めた" in plan.explanation_summary
        assert "2 件を繰り越した" in plan.explanation_summary


# ---------------------------------------------------------------------------
# new 上限
# ---------------------------------------------------------------------------


class TestNewCap:
    def test_new_count_does_not_exceed_max(self) -> None:
        snapshots = [_new_snapshot(f"new-{i}") for i in range(8)]
        items = _items(*(_vocab(f"new-{i}") for i in range(8)))
        plan = _plan(snapshots, items, total_count=10, max_new_count=3)
        assert plan.review_count == 0
        assert plan.new_count == 3
        assert plan.deferred_due_count == 0

    def test_max_new_zero_makes_review_only_plan(self) -> None:
        snapshots = [
            _review_snapshot("due-a"),
            _new_snapshot("new-1"),
        ]
        items = _items(_vocab("due-a"), _vocab("new-1"))
        plan = _plan(snapshots, items, max_new_count=0)
        assert plan.review_count == 1
        assert plan.new_count == 0
        assert _entry_ids(plan) == [("due-a", "recognition", "review")]


# ---------------------------------------------------------------------------
# deferred_due_count
# ---------------------------------------------------------------------------


class TestDeferredDue:
    def test_capacity_overflow_sets_deferred_due_count(self) -> None:
        snapshots = [_review_snapshot(f"due-{i}") for i in range(4)]
        items = _items(*(_vocab(f"due-{i}") for i in range(4)))
        plan = _plan(snapshots, items, total_count=2, max_new_count=0)
        assert plan.review_count == 2
        assert plan.deferred_due_count == 2

    def test_unsupported_due_is_deferred_and_skipped(self) -> None:
        snapshots = [
            _review_snapshot("grammar-due", direction="production", overdue_days=5.0),
            _review_snapshot("vocab-due", overdue_days=1.0),
        ]
        items = _items(_grammar("grammar-due"), _vocab("vocab-due"))
        plan = _plan(snapshots, items, total_count=5)
        assert plan.review_count == 1
        assert plan.entries[0].learning_item_id == "vocab-due"
        assert plan.deferred_due_count == 1
        assert any(
            row.learning_item_id == "grammar-due"
            and row.skip_reason == "unsupported_exercise"
            for row in plan.skipped
        )


# ---------------------------------------------------------------------------
# due 優先順位が #176 ranking を尊重
# ---------------------------------------------------------------------------


class TestRespectsRanking:
    def test_review_order_follows_ranking_not_input_order(self) -> None:
        low = _review_snapshot("low", overdue_days=0.0)
        high = _review_snapshot("high", overdue_days=6.0)
        snapshots = [low, high]
        items = _items(_vocab("low"), _vocab("high"))
        ranked = rank_recommendations(snapshots)
        review_ranked = [
            (c.learning_item_id, c.skill_direction)
            for c in ranked
            if c.activity_kind == "review"
        ]
        plan = _plan(snapshots, items, total_count=5)
        review_plan = [
            (row.learning_item_id, row.skill_direction)
            for row in plan.entries
            if row.activity_kind == "review"
        ]
        assert review_plan == review_ranked
        assert review_plan[0][0] == "high"


# ---------------------------------------------------------------------------
# unsupported candidate 補充
# ---------------------------------------------------------------------------


class TestUnsupportedFill:
    def test_unsupported_new_is_skipped_and_next_item_fills(self) -> None:
        snapshots = [
            _new_snapshot("bad-conj"),
            _new_snapshot("good-a"),
            _new_snapshot("good-b"),
        ]
        items = _items(
            _conjugation_unknown("bad-conj"),
            _vocab("good-a"),
            _vocab("good-b"),
        )
        plan = _plan(snapshots, items, total_count=10, max_new_count=2)
        assert plan.new_count == 2
        assert [row.learning_item_id for row in plan.entries] == [
            "good-a",
            "good-b",
        ]
        assert any(
            row.learning_item_id == "bad-conj"
            and row.skip_reason == "unsupported_exercise"
            for row in plan.skipped
        )
        assert all(row.activity_kind == "new_practice" for row in plan.entries)


# ---------------------------------------------------------------------------
# unseen / new 判定
# ---------------------------------------------------------------------------


class TestNewCandidateDefinition:
    def test_unseen_not_due_is_new(self) -> None:
        signal = _direction(
            "recognition", attempt_count=0, review_urgency="unscheduled"
        )
        assert is_new_practice_candidate(signal)
        assert not is_review_candidate(signal)

    def test_due_is_review_even_if_unseen(self) -> None:
        signal = _direction(
            "recognition",
            attempt_count=0,
            is_unseen=True,
            review_urgency="due",
            overdue_days=1.0,
        )
        assert is_review_candidate(signal)
        assert not is_new_practice_candidate(signal)

    def test_seen_unscheduled_is_not_new(self) -> None:
        signal = _direction(
            "recognition",
            mastery_score=0.9,
            attempt_count=8,
            is_unseen=False,
            review_urgency="unscheduled",
        )
        assert not is_new_practice_candidate(signal)
        assert not is_review_candidate(signal)

    def test_seen_unscheduled_item_is_excluded_from_plan(self) -> None:
        snapshots = [
            _seen_unscheduled_snapshot("learned"),
            _new_snapshot("fresh"),
        ]
        items = _items(_vocab("learned"), _vocab("fresh"))
        plan = _plan(snapshots, items, max_new_count=3)
        assert [row.learning_item_id for row in plan.entries] == ["fresh"]
        assert "learned" not in {row.learning_item_id for row in plan.entries}

    def test_ranked_new_is_rejected_when_snapshot_is_seen_unscheduled(self) -> None:
        ranked = rank_recommendations([_new_snapshot("learned")])
        plan = build_daily_learning_plan(
            ranked,
            items_by_id=_items(_vocab("learned")),
            snapshots_by_id={"learned": _seen_unscheduled_snapshot("learned")},
            generated_at=_NOW,
        )
        assert plan.entries == ()
        assert any(
            row.learning_item_id == "learned" and row.skip_reason == "seen_unscheduled"
            for row in plan.skipped
        )


# ---------------------------------------------------------------------------
# recognition / production の重複水増し抑止
# ---------------------------------------------------------------------------


class TestNoNewInflation:
    def test_new_item_uses_recognition_once(self) -> None:
        snapshots = [_new_snapshot("only-once")]
        items = _items(_vocab("only-once"))
        plan = _plan(snapshots, items)
        assert plan.new_count == 1
        assert plan.entries[0].skill_direction == "recognition"
        assert plan.entries[0].selected_exercise_type == "meaning_recognition"

    def test_new_falls_back_to_production_when_recognition_unsupported(self) -> None:
        snapshots = [_new_snapshot("conj-parler")]
        items = _items(
            LearningItem(
                id="conj-parler",
                item_type="conjugation",
                canonical_form="parler",
                meaning_ja="話す",
                metadata={"lemma": "parler", "tense": "présent"},
            )
        )
        plan = _plan(snapshots, items)
        assert plan.new_count == 1
        assert plan.entries[0].skill_direction == "production"
        assert plan.entries[0].selected_exercise_type == "verb_conjugation"

    def test_review_can_include_both_directions(self) -> None:
        snapshots = [_review_snapshot("both-due", both=True, overdue_days=2.0)]
        items = _items(_vocab("both-due"))
        plan = _plan(snapshots, items)
        kinds = {(row.skill_direction, row.activity_kind) for row in plan.entries}
        assert ("recognition", "review") in kinds
        assert ("production", "review") in kinds
        assert plan.review_count == 2
        assert plan.new_count == 0


# ---------------------------------------------------------------------------
# due 0 で new plan / candidate 0 で empty
# ---------------------------------------------------------------------------


class TestEmptyAndNewOnly:
    def test_due_zero_builds_new_plan(self) -> None:
        snapshots = [_new_snapshot("a"), _new_snapshot("b")]
        items = _items(_vocab("a"), _vocab("b"))
        plan = _plan(snapshots, items)
        assert plan.review_count == 0
        assert plan.new_count == 2
        assert plan.deferred_due_count == 0
        assert "期限到来の復習はなかった" in plan.explanation_summary

    def test_no_candidates_make_empty_plan(self) -> None:
        plan = _plan([], {})
        assert plan.entries == ()
        assert plan.review_count == 0
        assert plan.new_count == 0
        assert plan.deferred_due_count == 0
        assert plan.explanation_summary == "候補がないため空の学習計画にした。"
        assert plan.requested_count == DEFAULT_PLAN_SIZE


# ---------------------------------------------------------------------------
# deterministic / seed
# ---------------------------------------------------------------------------


class TestDeterministic:
    def test_same_input_same_plan(self) -> None:
        snapshots = [
            _review_snapshot("due-a", overdue_days=2.0),
            _new_snapshot("new-1"),
            _new_snapshot("new-2"),
        ]
        items = _items(_vocab("due-a"), _vocab("new-1"), _vocab("new-2"))
        first = _plan(snapshots, items, seed="same")
        second = _plan(snapshots, items, seed="same")
        assert first.entries == second.entries
        assert first.review_count == second.review_count
        assert first.new_count == second.new_count
        assert first.deferred_due_count == second.deferred_due_count
        assert first.explanation_summary == second.explanation_summary
        assert first.policy_version == second.policy_version
        assert first.generated_at == second.generated_at

    def test_naive_datetime_is_rejected(self) -> None:
        ranked = rank_recommendations([_new_snapshot("a")])
        with pytest.raises(ValueError, match="timezone-aware"):
            build_daily_learning_plan(
                ranked,
                items_by_id=_items(_vocab("a")),
                generated_at=datetime(2026, 9, 1, 12, 0, 0),
            )


# ---------------------------------------------------------------------------
# 区別 / provenance / exercise hint
# ---------------------------------------------------------------------------


class TestEntryContract:
    def test_review_and_new_are_explicit(self) -> None:
        snapshots = [_review_snapshot("due-a"), _new_snapshot("new-1")]
        items = _items(
            _vocab("due-a", source_id="src-1"),
            _vocab("new-1"),
        )
        plan = _plan(snapshots, items)
        kinds = [row.activity_kind for row in plan.entries]
        assert kinds == ["review", "new_practice"]
        review = plan.entries[0]
        assert review.source_provenance is not None
        assert review.source_provenance.source_document_ids == ("src-1",)
        assert review.reason_codes
        assert (
            review.rank_score
            == score_recommendation(snapshots[0], "recognition", "review").total_score
        )
        new = plan.entries[1]
        assert new.source_provenance is None
        assert new.selected_exercise_type == "meaning_recognition"

    def test_missing_item_skips_without_failing_plan(self) -> None:
        snapshots = [_review_snapshot("ghost"), _new_snapshot("alive")]
        items = _items(_vocab("alive"))
        plan = _plan(snapshots, items)
        assert [row.learning_item_id for row in plan.entries] == ["alive"]
        assert any(
            row.learning_item_id == "ghost" and row.skip_reason == "missing_item"
            for row in plan.skipped
        )
        assert plan.deferred_due_count == 1


# ---------------------------------------------------------------------------
# Phase 4 純 review session を壊さない
# ---------------------------------------------------------------------------


class TestPhase4Boundary:
    def test_review_session_does_not_import_daily_plan(self) -> None:
        import app.domain.review_session as review_session

        tree = ast.parse(inspect.getsource(review_session))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
            elif isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
        assert not any("daily_learning_plan" in name for name in names)

    def test_plan_does_not_import_review_session(self) -> None:
        import app.domain.daily_learning_plan as plan

        tree = ast.parse(inspect.getsource(plan))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
            elif isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
        assert not any("review_session" in name for name in names)

    def test_exercise_priority_matches_review_session(self) -> None:
        from app.domain.review_session import REVIEW_EXERCISE_PRIORITY

        assert PLAN_EXERCISE_PRIORITY == REVIEW_EXERCISE_PRIORITY

    def test_module_does_not_import_llm(self) -> None:
        import app.domain.daily_learning_plan as plan

        forbidden = {"openai", "anthropic", "langchain", "litellm"}
        tree = ast.parse(inspect.getsource(plan))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".", 1)[0])
        assert not (names & forbidden)


# ---------------------------------------------------------------------------
# 補助: select_exercise_type_for
# ---------------------------------------------------------------------------


class TestExerciseHint:
    def test_vocab_recognition_picks_meaning_recognition(self) -> None:
        exercise_type, reason, detail = select_exercise_type_for(
            _vocab("v"), "recognition"
        )
        assert exercise_type == "meaning_recognition"
        assert reason is None
        assert detail is None

    def test_grammar_production_without_source_is_unsupported(self) -> None:
        exercise_type, reason, detail = select_exercise_type_for(
            _grammar("g"), "production"
        )
        assert exercise_type is None
        assert reason is not None
        assert detail is not None


# ---------------------------------------------------------------------------
# ranked 入力を直接渡す
# ---------------------------------------------------------------------------


class TestDirectRankedInput:
    def test_empty_ranked_is_empty_plan(self) -> None:
        plan = build_daily_learning_plan(
            (),
            items_by_id={},
            generated_at=_NOW,
        )
        assert plan.entries == ()
        assert isinstance(plan.entries, tuple)

    def test_plan_records_seed(self) -> None:
        ranked: tuple[RankedRecommendation, ...] = rank_recommendations(
            [_new_snapshot("a")]
        )
        plan = build_daily_learning_plan(
            ranked,
            items_by_id=_items(_vocab("a")),
            generated_at=_NOW,
            seed="explicit",
        )
        assert plan.seed == "explicit"
