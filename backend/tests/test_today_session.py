"""「今日の学習」Plan 公開表現と Today Session 生成の domain テスト（Issue #178）。

テスト対象: `app.domain.today_session`

固定 fixture で以下を確認する。OpenAI / wall clock / FastAPI 非依存。
Phase 3/4 の Practice / Review Session は混ぜない。
"""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime

import pytest

from app.domain.daily_learning_plan import (
    DailyLearningPlanEntry,
    PlanConstraints,
    build_daily_learning_plan,
)
from app.domain.recommendation_ranking import ReasonCode, rank_recommendations
from app.domain.recommendation_signal import (
    FEATURE_VERSION,
    DirectionSignal,
    RecommendationSignalSnapshot,
)
from app.domain.today_session import (
    EMPTY_REASON_EXPLANATION,
    REASON_EXPLANATIONS,
    TodayPlanEntryView,
    build_today_learning_session,
    explain_reason_codes,
    to_public_plan,
)
from app.domain.tutor import LearningItem, SkillDirection, SourceDocument, SourceRef

_NOW = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)


def _direction(
    skill_direction: SkillDirection = "recognition",
    *,
    mastery_score: float = 0.0,
    attempt_count: int = 0,
    is_unseen: bool | None = None,
    review_urgency: str = "unscheduled",
    overdue_days: float = 0.0,
    recent_error_rate: float = 0.0,
    last_incorrect_age_days: float | None = None,
) -> DirectionSignal:
    if is_unseen is None:
        is_unseen = attempt_count == 0
    return DirectionSignal(
        skill_direction=skill_direction,
        mastery_score=mastery_score,
        attempt_count=attempt_count,
        consecutive_correct=0,
        is_unseen=is_unseen,
        review_urgency=review_urgency,  # type: ignore[arg-type]
        overdue_days=overdue_days,
        lapse_count=0,
        recent_error_rate=recent_error_rate,
        recent_incorrect_count=0,
        recent_correct_count=0,
        last_incorrect_age_days=last_incorrect_age_days,
    )


def _snapshot(
    learning_item_id: str,
    *,
    recognition: DirectionSignal | None = None,
    production: DirectionSignal | None = None,
    source_recency_days: float | None = None,
    source_ref_count: int = 0,
) -> RecommendationSignalSnapshot:
    return RecommendationSignalSnapshot(
        learning_item_id=learning_item_id,
        computed_at=_NOW,
        feature_version=FEATURE_VERSION,
        by_direction={
            "recognition": recognition or _direction("recognition"),
            "production": production or _direction("production"),
        },
        source_recency_days=source_recency_days,
        source_ref_count=source_ref_count,
        learner_level="B1",
        interest_weight=1.0,
        importance_weight=1.0,
    )


def _due_signal(
    direction: SkillDirection, *, overdue_days: float = 2.0
) -> DirectionSignal:
    return _direction(
        direction,
        mastery_score=0.5,
        attempt_count=4,
        is_unseen=False,
        review_urgency="due",
        overdue_days=overdue_days,
        recent_error_rate=0.5,
        last_incorrect_age_days=1.0,
    )


def _review_snapshot(
    item_id: str, *, overdue_days: float = 2.0
) -> RecommendationSignalSnapshot:
    return _snapshot(
        item_id,
        recognition=_due_signal("recognition", overdue_days=overdue_days),
        production=_direction(
            "production",
            mastery_score=0.8,
            attempt_count=4,
            is_unseen=False,
            review_urgency="future",
        ),
    )


def _new_snapshot(item_id: str) -> RecommendationSignalSnapshot:
    return _snapshot(item_id, source_recency_days=1.0, source_ref_count=1)


def _vocab(
    item_id: str, *, status: str = "active", source_id: str | None = None
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


def _pool(*ids: str) -> dict[str, LearningItem]:
    return {item_id: _vocab(item_id) for item_id in ids}


def _plan(
    snapshots: list[RecommendationSignalSnapshot],
    items: dict[str, LearningItem],
    **kwargs,
):
    ranked = rank_recommendations(snapshots)
    return build_daily_learning_plan(
        ranked,
        items_by_id=items,
        snapshots_by_id={row.learning_item_id: row for row in snapshots},
        constraints=PlanConstraints(
            total_count=kwargs.get("total_count", 10),
            max_new_count=kwargs.get("max_new_count", 3),
        ),
        generated_at=_NOW,
        seed=kwargs.get("seed", "test-today"),
    )


class TestReasonExplanation:
    def test_issue_examples_are_deterministic(self) -> None:
        assert explain_reason_codes(("OVERDUE_REVIEW",)) == "復習時期を迎えています。"
        assert (
            explain_reason_codes(("RECENT_ERROR",)) == "最近この項目で間違えています。"
        )
        assert (
            explain_reason_codes(("PRODUCTION_WEAKER",))
            == "意味は分かっていますが、自分で言う練習が不足しています。"
        )
        assert (
            explain_reason_codes(("RECENT_SOURCE",))
            == "最近追加した教材に出てきた表現です。"
        )

    def test_empty_codes_use_neutral_sentence(self) -> None:
        assert explain_reason_codes(()) == EMPTY_REASON_EXPLANATION

    def test_all_reason_codes_have_explanations(self) -> None:
        from typing import get_args

        assert set(REASON_EXPLANATIONS) == set(get_args(ReasonCode))

    def test_multiple_codes_join_in_order(self) -> None:
        text = explain_reason_codes(("OVERDUE_REVIEW", "RECENT_ERROR"))
        assert text.index("復習時期") < text.index("間違えて")


class TestPublicPlan:
    def test_omits_internal_score(self) -> None:
        assert "rank_score" not in TodayPlanEntryView.model_fields
        assert "components" not in TodayPlanEntryView.model_fields
        items = _pool("a", "b", "c", "d")
        plan = _plan([_new_snapshot(item_id) for item_id in items], items)
        view = to_public_plan(plan, items_by_id=items)
        dumped = view.model_dump()
        assert "rank_score" not in dumped
        for entry in dumped["entries"]:
            assert "rank_score" not in entry
            assert "components" not in entry
            assert entry["explanation"]
            assert entry["activity_kind"] in {"review", "new_practice"}

    def test_includes_source_titles(self) -> None:
        source = SourceDocument(id="src-1", title="Dialogue 1", content="bonjour")
        items = {
            "a": _vocab("a", source_id="src-1"),
            "b": _vocab("b"),
            "c": _vocab("c"),
            "d": _vocab("d"),
        }
        snap_a = _snapshot(
            "a",
            source_recency_days=1.0,
            source_ref_count=1,
        )
        plan = _plan(
            [snap_a, _new_snapshot("b"), _new_snapshot("c"), _new_snapshot("d")],
            items,
        )
        view = to_public_plan(
            plan, items_by_id=items, sources_by_id={source.id: source}
        )
        by_id = {row.learning_item_id: row for row in view.entries}
        assert by_id["a"].source_titles == ("Dialogue 1",)

    def test_review_and_new_counts(self) -> None:
        items = _pool("due-a", "n1", "n2", "n3", "n4")
        snapshots = [
            _review_snapshot("due-a", overdue_days=4.0),
            _new_snapshot("n1"),
            _new_snapshot("n2"),
            _new_snapshot("n3"),
            _new_snapshot("n4"),
        ]
        plan = _plan(snapshots, items, total_count=10, max_new_count=3)
        view = to_public_plan(plan, items_by_id=items)
        assert view.review_count == 1
        assert view.new_count == 3
        assert view.total_count == 4
        assert view.deferred_due_count == 0
        assert view.entries[0].activity_kind == "review"
        assert view.entries[0].skill_direction == "recognition"


class TestTodaySession:
    def test_session_follows_plan_order_and_direction(self) -> None:
        items = _pool("due-a", "n1", "n2", "n3", "n4")
        snapshots = [
            _review_snapshot("due-a", overdue_days=5.0),
            _new_snapshot("n1"),
            _new_snapshot("n2"),
            _new_snapshot("n3"),
            _new_snapshot("n4"),
        ]
        plan = _plan(snapshots, items, total_count=10, max_new_count=3)
        session = build_today_learning_session(
            plan,
            items_by_id=items,
            snapshots_by_id={row.learning_item_id: row for row in snapshots},
        )
        assert session.generated_count == 4
        assert session.review_count == 1
        assert session.new_count == 3
        assert session.exercises[0].spec.learning_item_id == "due-a"
        assert session.exercises[0].spec.skill_direction == "recognition"
        assert session.exercises[0].spec.exercise_type == "meaning_recognition"
        public = session.to_public_exercises()
        assert all("correct_answer" not in row.model_dump() for row in public)
        for exercise, entry in zip(session.exercises, session.entries, strict=True):
            assert exercise.spec.learning_item_id == entry.learning_item_id
            assert exercise.spec.skill_direction == entry.skill_direction
            assert entry.explanation

    def test_skips_inactive_item(self) -> None:
        items = _pool("due-a", "n1", "n2", "n3")
        snapshots = [
            _review_snapshot("due-a"),
            _new_snapshot("n1"),
            _new_snapshot("n2"),
        ]
        plan = _plan(snapshots, items)
        inactive = {**items, "due-a": _vocab("due-a", status="suspended")}
        session = build_today_learning_session(
            plan,
            items_by_id=inactive,
            snapshots_by_id={row.learning_item_id: row for row in snapshots},
        )
        skipped = {row.learning_item_id: row for row in session.skipped_entries}
        assert skipped["due-a"].skip_reason == "inactive_item"
        assert all(row.spec.learning_item_id != "due-a" for row in session.exercises)

    def test_skips_stale_due(self) -> None:
        items = _pool("due-a", "n1", "n2", "n3")
        snapshots = [_review_snapshot("due-a"), _new_snapshot("n1")]
        plan = _plan(snapshots, items)
        current = {
            "due-a": _snapshot(
                "due-a",
                recognition=_direction(
                    "recognition",
                    mastery_score=0.9,
                    attempt_count=5,
                    is_unseen=False,
                    review_urgency="future",
                ),
                production=_direction(
                    "production",
                    mastery_score=0.8,
                    attempt_count=4,
                    is_unseen=False,
                    review_urgency="future",
                ),
            ),
            "n1": _new_snapshot("n1"),
        }
        session = build_today_learning_session(
            plan, items_by_id=items, snapshots_by_id=current
        )
        skipped = {row.learning_item_id: row for row in session.skipped_entries}
        assert skipped["due-a"].skip_reason == "stale_due"

    def test_skips_stale_new(self) -> None:
        items = _pool("n1", "n2", "n3", "n4")
        snapshots = [_new_snapshot(item_id) for item_id in ("n1", "n2", "n3", "n4")]
        plan = _plan(snapshots, items, max_new_count=1)
        assert plan.entries[0].learning_item_id == "n1"
        current = {
            "n1": _snapshot(
                "n1",
                recognition=_direction(
                    "recognition",
                    mastery_score=0.5,
                    attempt_count=1,
                    is_unseen=False,
                    review_urgency="future",
                ),
                production=_direction("production"),
            ),
            "n2": _new_snapshot("n2"),
            "n3": _new_snapshot("n3"),
            "n4": _new_snapshot("n4"),
        }
        session = build_today_learning_session(
            plan, items_by_id=items, snapshots_by_id=current
        )
        skipped = {row.learning_item_id: row for row in session.skipped_entries}
        assert skipped["n1"].skip_reason == "stale_new"

    def test_skips_missing_item(self) -> None:
        items = _pool("n1", "n2", "n3", "n4")
        snapshots = [_new_snapshot(item_id) for item_id in items]
        plan = _plan(snapshots, items, max_new_count=1)
        first_id = plan.entries[0].learning_item_id
        remaining = {key: value for key, value in items.items() if key != first_id}
        session = build_today_learning_session(
            plan,
            items_by_id=remaining,
            snapshots_by_id={row.learning_item_id: row for row in snapshots},
        )
        skipped = {row.learning_item_id: row for row in session.skipped_entries}
        assert skipped[first_id].skip_reason == "missing_item"

    def test_empty_plan_is_empty_session(self) -> None:
        plan = build_daily_learning_plan((), items_by_id={}, generated_at=_NOW)
        session = build_today_learning_session(plan, items_by_id={})
        assert session.exercises == ()
        assert session.generated_count == 0
        assert session.skipped_entries == ()

    def test_does_not_create_learning_events(self) -> None:
        source = inspect.getsource(build_today_learning_session)
        assert "LearningEvent" not in source
        assert "append_event" not in source


class TestPhaseBoundary:
    def test_does_not_import_practice_or_review_session(self) -> None:
        import app.domain.today_session as module

        tree = ast.parse(inspect.getsource(module))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
            elif isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
        assert not any("practice_session" in name for name in names)
        assert not any("review_session" in name for name in names)

    def test_module_does_not_import_llm_or_frameworks(self) -> None:
        import app.domain.today_session as module

        tree = ast.parse(inspect.getsource(module))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".", 1)[0])
        forbidden = {
            "openai",
            "anthropic",
            "langchain",
            "litellm",
            "fastapi",
            "sqlalchemy",
        }
        assert not (names & forbidden)
        assert "datetime.now" not in inspect.getsource(module)


def test_public_entry_requires_existing_item() -> None:
    entry = DailyLearningPlanEntry(
        learning_item_id="missing",
        skill_direction="recognition",
        activity_kind="new_practice",
        selected_exercise_type="meaning_recognition",
        rank_score=0.1,
        reason_codes=(),
    )
    plan = build_daily_learning_plan((), items_by_id={}, generated_at=_NOW)
    broken = plan.model_copy(update={"entries": (entry,), "new_count": 1})
    with pytest.raises(ValueError, match="見つからない"):
        to_public_plan(broken, items_by_id={})
