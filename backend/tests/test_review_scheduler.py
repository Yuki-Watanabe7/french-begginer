"""初期 Review Scheduler（Issue #111）の純関数テスト。"""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.review_scheduler import (
    SCHEDULER_VERSION,
    interval_days_after_review,
    schedule_next_review,
)
from app.domain.tutor import (
    LearnerState,
    LearningEvent,
    ReviewSchedule,
    apply_review_event,
)

OCCURRED_AT = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


def _event(item_id: str, result: str, **overrides) -> LearningEvent:
    values = {
        "learning_item_id": item_id,
        "exercise_type": "fr_to_ja",
        "result": result,
        "occurred_at": OCCURRED_AT,
    }
    values.update(overrides)
    return LearningEvent(**values)


def _state_after(
    item_id: str, results: tuple[str, ...]
) -> tuple[LearnerState, LearningEvent]:
    state: LearnerState | None = None
    event: LearningEvent | None = None
    for i, result in enumerate(results):
        event = _event(
            item_id,
            result,
            occurred_at=OCCURRED_AT + timedelta(days=i),
        )
        state = apply_review_event(state, event)
    assert state is not None
    assert event is not None
    return state, event


def test_first_correct_review_is_due_the_next_day():
    state, event = _state_after("item-1", ("correct",))
    schedule = schedule_next_review(state, event)

    assert schedule.learning_item_id == "item-1"
    assert schedule.interval_days == 1.0
    assert schedule.due_at == event.occurred_at + timedelta(days=1)
    assert schedule.review_count == 1
    assert schedule.lapse_count == 0
    assert schedule.scheduler_version == SCHEDULER_VERSION


def test_first_incorrect_review_is_due_the_next_day():
    state, event = _state_after("item-1", ("incorrect",))
    schedule = schedule_next_review(state, event)

    assert schedule.interval_days == 1.0
    assert schedule.due_at == event.occurred_at + timedelta(days=1)
    assert schedule.review_count == 1
    assert schedule.lapse_count == 1


@pytest.mark.parametrize(
    ("consecutive_correct", "expected_days"),
    [(1, 1.0), (2, 3.0), (3, 7.0), (4, 14.0), (5, 14.0)],
)
def test_correct_streak_extends_interval(
    consecutive_correct: int, expected_days: float
):
    results = tuple(["correct"] * consecutive_correct)
    state, event = _state_after("item-1", results)
    assert state.consecutive_correct == consecutive_correct

    schedule = schedule_next_review(state, event)
    assert schedule.interval_days == expected_days
    assert schedule.due_at == event.occurred_at + timedelta(days=expected_days)
    assert schedule.lapse_count == 0


def test_correct_streak_does_not_shorten_interval():
    previous: ReviewSchedule | None = None
    state: LearnerState | None = None
    intervals: list[float] = []
    for i in range(1, 6):
        event = _event("item-1", "correct", occurred_at=OCCURRED_AT + timedelta(days=i))
        state = apply_review_event(state, event)
        schedule = schedule_next_review(state, event, previous)
        intervals.append(schedule.interval_days)
        previous = schedule

    assert intervals == [1.0, 3.0, 7.0, 14.0, 14.0]
    for earlier, later in zip(intervals, intervals[1:]):
        assert later >= earlier


def test_incorrect_shortens_interval_and_increments_lapse_count():
    previous: ReviewSchedule | None = None
    state: LearnerState | None = None
    event: LearningEvent | None = None
    for i, result in enumerate(("correct", "correct", "correct")):
        event = _event("item-1", result, occurred_at=OCCURRED_AT + timedelta(days=i))
        state = apply_review_event(state, event)
        previous = schedule_next_review(state, event, previous)
    assert state is not None
    assert event is not None
    assert previous is not None
    assert previous.interval_days == 7.0
    assert previous.lapse_count == 0
    assert previous.review_count == 3

    lapse_event = _event(
        "item-1", "incorrect", occurred_at=event.occurred_at + timedelta(days=1)
    )
    next_state = apply_review_event(state, lapse_event)
    schedule = schedule_next_review(next_state, lapse_event, previous)

    assert schedule.interval_days == 1.0
    assert schedule.due_at == lapse_event.occurred_at + timedelta(days=1)
    assert schedule.review_count == 4
    assert schedule.lapse_count == 1
    assert next_state.consecutive_correct == 0


def test_lapse_count_is_unchanged_on_correct():
    state, event = _state_after("item-1", ("incorrect",))
    previous = schedule_next_review(state, event)
    assert previous.lapse_count == 1

    correct = _event(
        "item-1", "correct", occurred_at=event.occurred_at + timedelta(days=1)
    )
    next_state = apply_review_event(state, correct)
    schedule = schedule_next_review(next_state, correct, previous)

    assert schedule.lapse_count == 1
    assert schedule.review_count == 2
    assert schedule.interval_days == 1.0


def test_due_at_is_based_on_event_time_not_clock():
    occurred_at = datetime(2020, 1, 1, 0, 0, tzinfo=UTC)
    event = _event("item-1", "correct", occurred_at=occurred_at)
    state = apply_review_event(None, event)
    schedule = schedule_next_review(state, event)
    assert schedule.due_at == datetime(2020, 1, 2, 0, 0, tzinfo=UTC)


def test_same_inputs_produce_the_same_schedule():
    state, event = _state_after("item-1", ("correct", "incorrect", "correct"))
    previous = ReviewSchedule(
        learning_item_id="item-1",
        due_at=OCCURRED_AT,
        interval_days=1.0,
        review_count=2,
        lapse_count=1,
        scheduler_version="legacy",
        metadata={"note": "keep"},
    )
    first = schedule_next_review(state, event, previous)
    second = schedule_next_review(state, event, previous)
    assert first == second
    assert first.scheduler_version == SCHEDULER_VERSION
    assert first.metadata == {"note": "keep"}
    assert first.review_count == 3
    assert first.lapse_count == 1


def test_schedule_next_review_does_not_mutate_previous_schedule():
    state, event = _state_after("item-1", ("correct",))
    previous = ReviewSchedule(
        learning_item_id="item-1",
        due_at=OCCURRED_AT,
        interval_days=3.0,
        review_count=1,
        lapse_count=0,
    )
    schedule_next_review(state, event, previous)
    assert previous.review_count == 1
    assert previous.interval_days == 3.0


def test_schedule_next_review_rejects_mismatched_state_item_id():
    event = _event("item-b", "correct")
    state = LearnerState(
        learning_item_id="item-a",
        attempt_count=1,
        correct_count=1,
        consecutive_correct=1,
        last_reviewed_at=OCCURRED_AT,
        mastery_score=1.0,
    )
    with pytest.raises(ValueError, match="learning_item_id が一致しない"):
        schedule_next_review(state, event)


def test_schedule_next_review_rejects_mismatched_previous_schedule():
    state, event = _state_after("item-1", ("correct",))
    previous = ReviewSchedule(
        learning_item_id="item-other",
        due_at=OCCURRED_AT,
        interval_days=1.0,
    )
    with pytest.raises(ValueError, match="ReviewSchedule と LearningEvent"):
        schedule_next_review(state, event, previous)


def test_interval_days_after_review_matches_baseline_table():
    assert interval_days_after_review(result="incorrect", consecutive_correct=0) == 1.0
    assert interval_days_after_review(result="correct", consecutive_correct=1) == 1.0
    assert interval_days_after_review(result="correct", consecutive_correct=2) == 3.0
    assert interval_days_after_review(result="correct", consecutive_correct=3) == 7.0
    assert interval_days_after_review(result="correct", consecutive_correct=4) == 14.0
    assert interval_days_after_review(result="correct", consecutive_correct=99) == 14.0
