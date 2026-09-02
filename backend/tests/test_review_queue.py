"""direction-aware due review queue（Issue #163）の domain テスト。

検証方針:
  - due 前は出ない / due 時刻で出る
  - overdue 順と同一時刻の安定順
  - recognition / production は別 entry
  - 片方向だけ due ならその方向だけ
  - suspended / mastered 除外
  - 未スケジュール Item を due 扱いしない
  - 0件 / limit / timezone 境界
  - schedule に Item が無い不整合は黙って落とさない
  - 正解情報を混ぜない / FastAPI 等に依存しない
"""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.domain.exercise import skill_direction_for
from app.domain.review_queue import (
    DEFAULT_QUEUE_LIMIT,
    MAX_QUEUE_LIMIT,
    InvalidReviewQueueRequestError,
    MissingReviewQueueItemError,
    available_exercise_types_for,
    build_review_queue,
    compute_overdue,
)
from app.domain.tutor import LearnerState, LearningItem, MasteryStats, ReviewSchedule

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
JST = timezone(timedelta(hours=9))


def _item(item_id: str, **overrides) -> LearningItem:
    values = {
        "id": item_id,
        "item_type": "vocabulary",
        "canonical_form": "livre",
        "meaning_ja": "本",
        "status": "active",
        "created_at": NOW - timedelta(days=10),
    }
    values.update(overrides)
    return LearningItem(**values)


def _schedule(item_id: str, due_at: datetime, **overrides) -> ReviewSchedule:
    values = {
        "learning_item_id": item_id,
        "skill_direction": "recognition",
        "due_at": due_at,
        "interval_days": 1.0,
        "review_count": 1,
    }
    values.update(overrides)
    return ReviewSchedule(**values)


def _state(item_id: str, *, direction: str = "recognition") -> LearnerState:
    stats = MasteryStats(
        attempt_count=1,
        correct_count=1,
        last_reviewed_at=NOW - timedelta(days=1),
        mastery_score=1.0,
    )
    return LearnerState(
        learning_item_id=item_id,
        attempt_count=1,
        correct_count=1,
        last_reviewed_at=NOW - timedelta(days=1),
        mastery_score=1.0,
        by_direction={direction: stats},
    )


def _queue(schedules, items, *, now=NOW, limit=DEFAULT_QUEUE_LIMIT, states=None):
    return build_review_queue(
        schedules,
        items_by_id={item.id: item for item in items},
        states_by_id=states,
        now=now,
        limit=limit,
    )


def test_due_before_now_is_excluded_and_due_at_now_is_included():
    item = _item("item-a")
    future = _schedule(item.id, NOW + timedelta(seconds=1))
    due_now = _schedule(item.id, NOW)
    queue = _queue([future, due_now], [item])
    assert [row.review_schedule.due_at for row in queue.entries] == [NOW]
    assert queue.summary.total_due == 1
    assert queue.summary.overdue_count == 0
    assert queue.entries[0].overdue_seconds == 0
    assert queue.entries[0].overdue_days == 0


def test_most_overdue_comes_first_then_item_id_then_skill_direction():
    earlier = _item("item-z")
    later = _item("item-a")
    same_due_prod = _schedule(
        later.id, NOW - timedelta(days=1), skill_direction="production"
    )
    same_due_rec = _schedule(
        later.id, NOW - timedelta(days=1), skill_direction="recognition"
    )
    oldest = _schedule(earlier.id, NOW - timedelta(days=2))
    queue = _queue([same_due_rec, oldest, same_due_prod], [earlier, later])
    keys = [
        (row.review_schedule.due_at, row.item.id, row.skill_direction)
        for row in queue.entries
    ]
    assert keys == [
        (NOW - timedelta(days=2), earlier.id, "recognition"),
        (NOW - timedelta(days=1), later.id, "production"),
        (NOW - timedelta(days=1), later.id, "recognition"),
    ]


def test_recognition_and_production_are_separate_entries():
    item = _item("item-both")
    rec = _schedule(item.id, NOW - timedelta(hours=2), skill_direction="recognition")
    prod = _schedule(item.id, NOW - timedelta(hours=1), skill_direction="production")
    state = _state(item.id)
    queue = _queue([rec, prod], [item], states={item.id: state})
    assert [row.skill_direction for row in queue.entries] == [
        "recognition",
        "production",
    ]
    assert queue.summary.total_due == 2
    assert queue.summary.recognition_due == 1
    assert queue.summary.production_due == 1
    assert all(row.item.id == item.id for row in queue.entries)
    assert queue.entries[0].learner_state is state
    assert "recognition" in queue.entries[0].learner_state.by_direction


def test_only_due_direction_is_returned():
    item = _item("item-split")
    rec = _schedule(item.id, NOW - timedelta(days=1), skill_direction="recognition")
    prod = _schedule(item.id, NOW + timedelta(days=1), skill_direction="production")
    queue = _queue([rec, prod], [item])
    assert [row.skill_direction for row in queue.entries] == ["recognition"]
    assert queue.summary.production_due == 0


def test_suspended_and_mastered_are_excluded():
    active = _item("active")
    suspended = _item("suspended", status="suspended")
    mastered = _item("mastered", status="mastered")
    schedules = [
        _schedule(active.id, NOW - timedelta(hours=1)),
        _schedule(suspended.id, NOW - timedelta(hours=1)),
        _schedule(mastered.id, NOW - timedelta(hours=1)),
    ]
    queue = _queue(schedules, [active, suspended, mastered])
    assert [row.item.id for row in queue.entries] == [active.id]


def test_unscheduled_active_item_is_not_treated_as_due():
    scheduled = _item("scheduled")
    unscheduled = _item("unscheduled")
    queue = _queue(
        [_schedule(scheduled.id, NOW)],
        [scheduled, unscheduled],
    )
    assert [row.item.id for row in queue.entries] == [scheduled.id]
    assert queue.summary.total_due == 1


def test_empty_queue_has_zero_summary():
    queue = _queue([], [])
    assert queue.entries == ()
    assert queue.summary.total_due == 0
    assert queue.summary.recognition_due == 0
    assert queue.summary.production_due == 0
    assert queue.summary.overdue_count == 0


def test_limit_truncates_entries_but_summary_counts_all_due():
    items = [_item(f"item-{index:02d}") for index in range(5)]
    schedules = [
        _schedule(
            item.id,
            NOW - timedelta(minutes=index),
            skill_direction="recognition",
        )
        for index, item in enumerate(items)
    ]
    queue = _queue(schedules, items, limit=2)
    assert len(queue.entries) == 2
    assert queue.summary.total_due == 5
    assert [row.item.id for row in queue.entries] == ["item-04", "item-03"]


@pytest.mark.parametrize("limit", [0, -1, MAX_QUEUE_LIMIT + 1])
def test_invalid_limit_is_rejected(limit: int):
    with pytest.raises(InvalidReviewQueueRequestError, match="limit"):
        _queue([], [], limit=limit)


def test_timezone_boundary_compares_in_utc():
    utc_midnight = datetime(2026, 1, 1, tzinfo=UTC)
    item = _item("tz-item")
    schedule = _schedule(item.id, utc_midnight)
    before = _queue([schedule], [item], now=utc_midnight - timedelta(seconds=1))
    assert before.entries == ()
    at_utc = _queue([schedule], [item], now=utc_midnight)
    assert [row.item.id for row in at_utc.entries] == [item.id]
    jst_same_instant = datetime(2026, 1, 1, 9, 0, tzinfo=JST)
    at_jst = _queue([schedule], [item], now=jst_same_instant)
    assert [row.item.id for row in at_jst.entries] == [item.id]
    jst_before = _queue(
        [schedule],
        [item],
        now=datetime(2026, 1, 1, 8, 59, 59, tzinfo=JST),
    )
    assert jst_before.entries == ()


def test_stable_ordering_is_deterministic():
    item_b = _item("item-b")
    item_a = _item("item-a")
    schedules = [
        _schedule(item_b.id, NOW, skill_direction="recognition"),
        _schedule(item_a.id, NOW, skill_direction="production"),
        _schedule(item_a.id, NOW, skill_direction="recognition"),
    ]
    first = _queue(schedules, [item_a, item_b])
    second = _queue(list(reversed(schedules)), [item_b, item_a])
    assert [(row.item.id, row.skill_direction) for row in first.entries] == [
        (item_a.id, "production"),
        (item_a.id, "recognition"),
        (item_b.id, "recognition"),
    ]
    assert first.entries == second.entries


def test_missing_item_for_schedule_is_not_silently_dropped():
    schedule = _schedule("missing-item", NOW)
    with pytest.raises(MissingReviewQueueItemError, match="missing-item"):
        build_review_queue([schedule], items_by_id={}, now=NOW)


def test_naive_now_is_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        build_review_queue([], items_by_id={}, now=datetime(2026, 1, 1, 12, 0))


def test_overdue_seconds_and_days_match_elapsed_time():
    due_at = NOW - timedelta(days=2, hours=12)
    seconds, days = compute_overdue(due_at, NOW)
    assert seconds == timedelta(days=2, hours=12).total_seconds()
    assert days == 2.5


def test_available_exercise_types_match_entry_direction():
    item = _item("vocab")
    rec = _schedule(item.id, NOW, skill_direction="recognition")
    prod = _schedule(item.id, NOW, skill_direction="production")
    queue = _queue([rec, prod], [item])
    rec_entry = next(
        row for row in queue.entries if row.skill_direction == "recognition"
    )
    prod_entry = next(
        row for row in queue.entries if row.skill_direction == "production"
    )
    assert rec_entry.available_exercise_types == available_exercise_types_for(
        item, "recognition"
    )
    assert prod_entry.available_exercise_types == available_exercise_types_for(
        item, "production"
    )
    assert rec_entry.available_exercise_types
    assert all(
        skill_direction_for(exercise_type) == "recognition"
        for exercise_type in rec_entry.available_exercise_types
    )
    assert prod_entry.available_exercise_types
    assert all(
        skill_direction_for(exercise_type) == "production"
        for exercise_type in prod_entry.available_exercise_types
    )


def test_queue_payload_does_not_include_answer_fields():
    item = _item("vocab")
    queue = _queue([_schedule(item.id, NOW)], [item])
    dumped = queue.model_dump()
    payload = str(dumped)
    for forbidden in ("correct_answer", "expected_answer", "answer_key"):
        assert forbidden not in payload


def test_domain_module_does_not_depend_on_fastapi_sqlalchemy_or_openai():
    import app.domain.review_queue as module

    tree = ast.parse(inspect.getsource(module))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".", 1)[0])
    assert names.isdisjoint({"fastapi", "sqlalchemy", "openai"}), names
    assert "datetime.now" not in inspect.getsource(module)
