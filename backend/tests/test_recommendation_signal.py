"""RecommendationSignalSnapshot の単体テスト（Issue #175）。

テスト対象: `app.domain.recommendation_signal.extract_recommendation_signal`

OpenAI 非依存・wall clock 非依存。
"""

from __future__ import annotations

from datetime import UTC, datetime
from datetime import timedelta as td

import pytest

from app.domain.recommendation_signal import (
    DEFAULT_LEARNER_LEVEL,
    FEATURE_VERSION,
    NEUTRAL_IMPORTANCE_WEIGHT,
    NEUTRAL_INTEREST_WEIGHT,
    RECENT_EVENT_WINDOW,
    extract_recommendation_signal,
)
from app.domain.tutor import (
    LearnerState,
    LearningEvent,
    LearningItem,
    ReviewSchedule,
    SourceDocument,
    SourceRef,
    apply_review_event,
)

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)


def _item(
    *,
    level: str | None = None,
    source_refs: list[SourceRef] | None = None,
    metadata: dict | None = None,
) -> LearningItem:
    return LearningItem(
        item_type="vocabulary",
        canonical_form="parler",
        meaning_ja="話す",
        level=level,  # type: ignore[arg-type]
        source_refs=source_refs or [],
        metadata=metadata or {},
    )


def _source(*, created_at: datetime) -> SourceDocument:
    return SourceDocument(title="test", content="test content", created_at=created_at)


def _schedule(
    item_id: str,
    direction: str,
    *,
    due_at: datetime,
    lapse_count: int = 0,
) -> ReviewSchedule:
    return ReviewSchedule(
        learning_item_id=item_id,
        skill_direction=direction,  # type: ignore[arg-type]
        due_at=due_at,
        interval_days=1.0,
        lapse_count=lapse_count,
    )


def _event(
    item_id: str,
    result: str,
    exercise_type: str = "fr_to_ja",  # recognition
    *,
    occurred_at: datetime,
) -> LearningEvent:
    return LearningEvent(
        learning_item_id=item_id,
        exercise_type=exercise_type,  # type: ignore[arg-type]
        result=result,  # type: ignore[arg-type]
        occurred_at=occurred_at,
    )


def _build_state(item_id: str, events: list[LearningEvent]) -> LearnerState:
    state: LearnerState | None = None
    for e in events:
        state = apply_review_event(state, e)
    assert state is not None
    return state


# ---------------------------------------------------------------------------
# 1. due / overdue signal
# ---------------------------------------------------------------------------


class TestReviewUrgency:
    def test_due_item_is_marked_due(self) -> None:
        item = _item()
        due_at = _NOW - td(hours=1)
        schedules = {
            "recognition": _schedule(item.id, "recognition", due_at=due_at),
        }
        snap = extract_recommendation_signal(
            item, schedules_by_direction=schedules, now=_NOW
        )
        assert snap.by_direction["recognition"].review_urgency == "due"

    def test_overdue_days_computed_correctly(self) -> None:
        item = _item()
        due_at = _NOW - td(days=2)
        schedules = {
            "recognition": _schedule(item.id, "recognition", due_at=due_at),
        }
        snap = extract_recommendation_signal(
            item, schedules_by_direction=schedules, now=_NOW
        )
        assert abs(snap.by_direction["recognition"].overdue_days - 2.0) < 0.01

    def test_future_schedule_is_not_due(self) -> None:
        item = _item()
        due_at = _NOW + td(days=1)
        schedules = {
            "recognition": _schedule(item.id, "recognition", due_at=due_at),
        }
        snap = extract_recommendation_signal(
            item, schedules_by_direction=schedules, now=_NOW
        )
        assert snap.by_direction["recognition"].review_urgency == "future"
        assert snap.by_direction["recognition"].overdue_days == 0.0

    def test_no_schedule_is_unscheduled(self) -> None:
        item = _item()
        snap = extract_recommendation_signal(item, now=_NOW)
        assert snap.by_direction["recognition"].review_urgency == "unscheduled"

    def test_due_at_exactly_now_is_due(self) -> None:
        item = _item()
        schedules = {
            "production": _schedule(item.id, "production", due_at=_NOW),
        }
        snap = extract_recommendation_signal(
            item, schedules_by_direction=schedules, now=_NOW
        )
        assert snap.by_direction["production"].review_urgency == "due"

    def test_lapse_count_is_included(self) -> None:
        item = _item()
        schedules = {
            "recognition": _schedule(
                item.id, "recognition", due_at=_NOW, lapse_count=3
            ),
        }
        snap = extract_recommendation_signal(
            item, schedules_by_direction=schedules, now=_NOW
        )
        assert snap.by_direction["recognition"].lapse_count == 3

    def test_missing_schedule_lapse_count_is_zero(self) -> None:
        item = _item()
        snap = extract_recommendation_signal(item, now=_NOW)
        assert snap.by_direction["recognition"].lapse_count == 0


# ---------------------------------------------------------------------------
# 2. unseen vs low mastery
# ---------------------------------------------------------------------------


class TestUnseenVsLowMastery:
    def test_unseen_item_is_flagged(self) -> None:
        item = _item()
        snap = extract_recommendation_signal(item, now=_NOW)
        assert snap.by_direction["recognition"].is_unseen is True
        assert snap.by_direction["recognition"].attempt_count == 0

    def test_low_mastery_item_is_not_unseen(self) -> None:
        item = _item()
        events = [
            _event(item.id, "incorrect", "fr_to_ja", occurred_at=_NOW - td(days=1)),
        ]
        state = _build_state(item.id, events)
        snap = extract_recommendation_signal(item, learner_state=state, now=_NOW)
        assert snap.by_direction["recognition"].is_unseen is False
        assert snap.by_direction["recognition"].mastery_score == 0.0
        assert snap.by_direction["recognition"].attempt_count == 1

    def test_high_mastery_not_unseen(self) -> None:
        item = _item()
        events = [
            _event(item.id, "correct", "fr_to_ja", occurred_at=_NOW - td(days=i))
            for i in range(5, 0, -1)
        ]
        state = _build_state(item.id, events)
        snap = extract_recommendation_signal(item, learner_state=state, now=_NOW)
        assert snap.by_direction["recognition"].is_unseen is False
        assert snap.by_direction["recognition"].mastery_score == 1.0


# ---------------------------------------------------------------------------
# 3. recognition / production imbalance
# ---------------------------------------------------------------------------


class TestDirectionImbalance:
    def test_production_gap_when_both_seen(self) -> None:
        item = _item()
        # recognition: 5正答 → mastery=1.0
        # production: 1正答2誤答 → mastery=1/3
        rec_events = [
            _event(item.id, "correct", "fr_to_ja", occurred_at=_NOW - td(days=i))
            for i in range(5, 0, -1)
        ]
        prod_events = [
            _event(item.id, "correct", "ja_to_fr", occurred_at=_NOW - td(days=5)),
            _event(item.id, "incorrect", "ja_to_fr", occurred_at=_NOW - td(days=4)),
            _event(item.id, "incorrect", "ja_to_fr", occurred_at=_NOW - td(days=3)),
        ]
        state = _build_state(item.id, rec_events + prod_events)
        snap = extract_recommendation_signal(item, learner_state=state, now=_NOW)
        assert snap.production_gap is not None
        # recognition(1.0) - production(1/3) ≈ 0.667
        assert abs(snap.production_gap - (1.0 - 1 / 3)) < 0.01

    def test_production_gap_none_when_production_unseen(self) -> None:
        item = _item()
        events = [
            _event(item.id, "correct", "fr_to_ja", occurred_at=_NOW - td(days=1)),
        ]
        state = _build_state(item.id, events)
        snap = extract_recommendation_signal(item, learner_state=state, now=_NOW)
        assert snap.production_gap is None

    def test_production_gap_none_when_both_unseen(self) -> None:
        item = _item()
        snap = extract_recommendation_signal(item, now=_NOW)
        assert snap.production_gap is None


# ---------------------------------------------------------------------------
# 4. recent incorrect signal
# ---------------------------------------------------------------------------


class TestRecentErrorSignal:
    def test_recent_error_rate(self) -> None:
        item = _item()
        events = [
            _event(item.id, "correct", "fr_to_ja", occurred_at=_NOW - td(days=5)),
            _event(item.id, "incorrect", "fr_to_ja", occurred_at=_NOW - td(days=4)),
            _event(item.id, "incorrect", "fr_to_ja", occurred_at=_NOW - td(days=3)),
        ]
        state = _build_state(item.id, events)
        snap = extract_recommendation_signal(
            item,
            learner_state=state,
            events_by_direction={"recognition": events},
            now=_NOW,
        )
        assert abs(snap.by_direction["recognition"].recent_error_rate - 2 / 3) < 0.01

    def test_no_events_error_rate_is_zero(self) -> None:
        item = _item()
        snap = extract_recommendation_signal(item, now=_NOW)
        assert snap.by_direction["recognition"].recent_error_rate == 0.0

    def test_last_incorrect_age_days(self) -> None:
        item = _item()
        incorrect_at = _NOW - td(days=3)
        events = [
            _event(item.id, "incorrect", "fr_to_ja", occurred_at=incorrect_at),
            _event(item.id, "correct", "fr_to_ja", occurred_at=_NOW - td(days=1)),
        ]
        snap = extract_recommendation_signal(
            item,
            events_by_direction={"recognition": events},
            now=_NOW,
        )
        assert snap.by_direction["recognition"].last_incorrect_age_days is not None
        age = snap.by_direction["recognition"].last_incorrect_age_days
        assert abs(age - 3.0) < 0.01

    def test_last_incorrect_age_none_when_no_incorrect(self) -> None:
        item = _item()
        events = [
            _event(item.id, "correct", "fr_to_ja", occurred_at=_NOW - td(days=1)),
        ]
        snap = extract_recommendation_signal(
            item,
            events_by_direction={"recognition": events},
            now=_NOW,
        )
        assert snap.by_direction["recognition"].last_incorrect_age_days is None

    def test_recent_window_is_capped(self) -> None:
        """RECENT_EVENT_WINDOW より古いイベントは error rate に含まれない。"""
        item = _item()
        # RECENT_EVENT_WINDOW 件すべて correct の後に old_incorrect を追加
        old_incorrect = _event(
            item.id,
            "incorrect",
            "fr_to_ja",
            occurred_at=_NOW - td(days=RECENT_EVENT_WINDOW + 10),
        )
        recent_events = [
            _event(
                item.id,
                "correct",
                "fr_to_ja",
                occurred_at=_NOW - td(days=RECENT_EVENT_WINDOW - i),
            )
            for i in range(RECENT_EVENT_WINDOW)
        ]
        all_events = [old_incorrect] + recent_events
        snap = extract_recommendation_signal(
            item,
            events_by_direction={"recognition": all_events},
            now=_NOW,
        )
        assert snap.by_direction["recognition"].recent_error_rate == 0.0


# ---------------------------------------------------------------------------
# 5. CEFR level fit
# ---------------------------------------------------------------------------


class TestCefrLevelFit:
    def test_level_distance_same(self) -> None:
        item = _item(level="B1")
        snap = extract_recommendation_signal(item, learner_level="B1", now=_NOW)
        assert snap.level_distance == 0

    def test_level_distance_far(self) -> None:
        item = _item(level="C2")
        snap = extract_recommendation_signal(item, learner_level="A1", now=_NOW)
        assert snap.level_distance == 5

    def test_level_distance_unknown_item(self) -> None:
        item = _item(level=None)
        snap = extract_recommendation_signal(item, learner_level="B1", now=_NOW)
        assert snap.level_distance is None

    def test_learner_level_default_when_not_set(self) -> None:
        item = _item(level="A1")
        snap = extract_recommendation_signal(item, now=_NOW)
        assert snap.learner_level == DEFAULT_LEARNER_LEVEL
        assert snap.level_distance is not None


# ---------------------------------------------------------------------------
# 6. Source recency / interest
# ---------------------------------------------------------------------------


class TestSourceRecencyInterest:
    def test_recent_source_recency_days(self) -> None:
        source = _source(created_at=_NOW - td(days=3))
        item = _item(source_refs=[SourceRef(source_document_id=source.id)])
        snap = extract_recommendation_signal(
            item,
            sources_by_id={source.id: source},
            now=_NOW,
        )
        assert snap.source_recency_days is not None
        assert abs(snap.source_recency_days - 3.0) < 0.01

    def test_no_source_refs_recency_is_none(self) -> None:
        item = _item()
        snap = extract_recommendation_signal(item, now=_NOW)
        assert snap.source_recency_days is None

    def test_source_ref_count(self) -> None:
        sources = [_source(created_at=_NOW - td(days=i)) for i in range(3)]
        item = _item(source_refs=[SourceRef(source_document_id=s.id) for s in sources])
        snap = extract_recommendation_signal(
            item,
            sources_by_id={s.id: s for s in sources},
            now=_NOW,
        )
        assert snap.source_ref_count == 3

    def test_interest_weight_neutral_when_not_set(self) -> None:
        item = _item()
        snap = extract_recommendation_signal(item, now=_NOW)
        assert snap.interest_weight == NEUTRAL_INTEREST_WEIGHT

    def test_interest_weight_from_metadata(self) -> None:
        item = _item(metadata={"interest_weight": 2.5})
        snap = extract_recommendation_signal(item, now=_NOW)
        assert snap.interest_weight == 2.5

    def test_multiple_source_refs_uses_newest(self) -> None:
        old_source = _source(created_at=_NOW - td(days=10))
        new_source = _source(created_at=_NOW - td(days=2))
        item = _item(
            source_refs=[
                SourceRef(source_document_id=old_source.id),
                SourceRef(source_document_id=new_source.id),
            ]
        )
        snap = extract_recommendation_signal(
            item,
            sources_by_id={old_source.id: old_source, new_source.id: new_source},
            now=_NOW,
        )
        # 最新 source = 2日前
        assert snap.source_recency_days is not None
        assert abs(snap.source_recency_days - 2.0) < 0.01


# ---------------------------------------------------------------------------
# 7. importance_weight
# ---------------------------------------------------------------------------


class TestImportanceWeight:
    def test_neutral_when_not_set(self) -> None:
        item = _item()
        snap = extract_recommendation_signal(item, now=_NOW)
        assert snap.importance_weight == NEUTRAL_IMPORTANCE_WEIGHT

    def test_importance_from_metadata(self) -> None:
        item = _item(metadata={"importance_weight": 1.5})
        snap = extract_recommendation_signal(item, now=_NOW)
        assert snap.importance_weight == 1.5


# ---------------------------------------------------------------------------
# 8. deterministic
# ---------------------------------------------------------------------------


class TestDeterministic:
    def test_same_input_same_output(self) -> None:
        item = _item(level="B1")
        source = _source(created_at=_NOW - td(days=5))
        item2 = LearningItem(
            id=item.id,
            item_type=item.item_type,
            canonical_form=item.canonical_form,
            meaning_ja=item.meaning_ja,
            level=item.level,
            source_refs=[SourceRef(source_document_id=source.id)],
            created_at=item.created_at,
        )
        schedules = {
            "recognition": _schedule(item.id, "recognition", due_at=_NOW - td(hours=1)),
        }
        snap1 = extract_recommendation_signal(
            item2,
            schedules_by_direction=schedules,
            sources_by_id={source.id: source},
            learner_level="B1",
            now=_NOW,
        )
        snap2 = extract_recommendation_signal(
            item2,
            schedules_by_direction=schedules,
            sources_by_id={source.id: source},
            learner_level="B1",
            now=_NOW,
        )
        assert snap1 == snap2

    def test_different_now_gives_different_overdue(self) -> None:
        item = _item()
        due_at = _NOW - td(days=1)
        schedules = {
            "recognition": _schedule(item.id, "recognition", due_at=due_at),
        }
        snap1 = extract_recommendation_signal(
            item, schedules_by_direction=schedules, now=_NOW
        )
        snap2 = extract_recommendation_signal(
            item,
            schedules_by_direction=schedules,
            now=_NOW + td(days=1),
        )
        assert (
            snap1.by_direction["recognition"].overdue_days
            != snap2.by_direction["recognition"].overdue_days
        )


# ---------------------------------------------------------------------------
# 9. timezone boundary
# ---------------------------------------------------------------------------


class TestTimezoneBoundary:
    def test_aware_datetime_required(self) -> None:
        item = _item()
        naive_now = datetime(2026, 9, 1, 12, 0, 0)
        with pytest.raises(ValueError, match="timezone-aware"):
            extract_recommendation_signal(item, now=naive_now)


# ---------------------------------------------------------------------------
# 10. feature_version
# ---------------------------------------------------------------------------


class TestFeatureVersion:
    def test_feature_version_is_set(self) -> None:
        item = _item()
        snap = extract_recommendation_signal(item, now=_NOW)
        assert snap.feature_version == FEATURE_VERSION
