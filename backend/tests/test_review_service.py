"""ReviewService（Issue #111）のユースケーステスト。"""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.review_scheduler import SCHEDULER_VERSION
from app.domain.tutor import LearningEvent, LearningItem, apply_review_event
from app.repositories.sqlite import TutorSqliteStore
from app.services.review_service import ReviewService

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


def _item(**overrides) -> LearningItem:
    values = {
        "item_type": "expression",
        "canonical_form": "il s'agit de",
        "meaning_ja": "〜が問題である",
    }
    values.update(overrides)
    return LearningItem(**values)


def _event(item_id: str, **overrides) -> LearningEvent:
    values = {
        "learning_item_id": item_id,
        "exercise_type": "fr_to_ja",
        "result": "correct",
        "occurred_at": NOW - timedelta(days=1),
    }
    values.update(overrides)
    return LearningEvent(**values)


@pytest.fixture
def store() -> TutorSqliteStore:
    return TutorSqliteStore.in_memory()


@pytest.fixture
def service(store: TutorSqliteStore) -> ReviewService:
    return ReviewService(
        learning_items=store.learning_items,
        review_schedules=store.review_schedules,
    )


def _schedule_event(
    store: TutorSqliteStore,
    service: ReviewService,
    item: LearningItem,
    event: LearningEvent,
):
    store.learning_items.create(item)
    state = apply_review_event(None, event)
    return service.schedule_after_review(state, event)


def test_schedule_after_review_sets_next_due_for_first_review(
    store: TutorSqliteStore, service: ReviewService
):
    item = _item()
    event = _event(item.id)
    schedule = _schedule_event(store, service, item, event)

    assert schedule.due_at == event.occurred_at + timedelta(days=1)
    assert schedule.interval_days == 1.0
    assert schedule.review_count == 1
    assert schedule.lapse_count == 0
    assert schedule.scheduler_version == SCHEDULER_VERSION
    assert store.review_schedules.get(item.id, "recognition") == schedule


def test_schedule_after_review_updates_counts_across_reviews(
    store: TutorSqliteStore, service: ReviewService
):
    item = _item()
    store.learning_items.create(item)

    first_event = _event(item.id, result="correct", occurred_at=NOW - timedelta(days=4))
    first_state = apply_review_event(None, first_event)
    first = service.schedule_after_review(first_state, first_event)
    assert first.review_count == 1
    assert first.lapse_count == 0
    assert first.interval_days == 1.0

    second_event = _event(
        item.id, result="incorrect", occurred_at=NOW - timedelta(days=3)
    )
    second_state = apply_review_event(first_state, second_event)
    second = service.schedule_after_review(second_state, second_event)
    assert second.review_count == 2
    assert second.lapse_count == 1
    assert second.interval_days == 1.0
    assert store.review_schedules.get(item.id, "recognition") == second


def test_list_due_returns_only_due_items_in_stable_order(
    store: TutorSqliteStore, service: ReviewService
):
    earlier = _item(id="item-z", canonical_form="earlier", meaning_ja="早い")
    later_same_due = _item(id="item-a", canonical_form="later-id", meaning_ja="同刻")
    future = _item(id="item-m", canonical_form="future", meaning_ja="未到来")
    store.learning_items.create(earlier)
    store.learning_items.create(later_same_due)
    store.learning_items.create(future)

    earlier_event = _event(
        earlier.id, occurred_at=NOW - timedelta(days=2), result="correct"
    )
    same_due_event = _event(
        later_same_due.id, occurred_at=NOW - timedelta(days=1), result="correct"
    )
    future_event = _event(future.id, occurred_at=NOW, result="correct")

    service.schedule_after_review(
        apply_review_event(None, earlier_event), earlier_event
    )
    service.schedule_after_review(
        apply_review_event(None, same_due_event), same_due_event
    )
    service.schedule_after_review(apply_review_event(None, future_event), future_event)

    due = service.list_due(NOW)
    assert [schedule.learning_item_id for schedule in due] == [
        earlier.id,
        later_same_due.id,
    ]
    assert all(schedule.due_at <= NOW for schedule in due)


def test_list_due_excludes_suspended_and_mastered(
    store: TutorSqliteStore, service: ReviewService
):
    active = _item(id="active", canonical_form="active", meaning_ja="学習中")
    suspended = _item(
        id="suspended",
        canonical_form="suspended",
        meaning_ja="停止",
        status="suspended",
    )
    mastered = _item(
        id="mastered",
        canonical_form="mastered",
        meaning_ja="定着",
        status="mastered",
    )
    for item in (active, suspended, mastered):
        event = _event(item.id, occurred_at=NOW - timedelta(days=2))
        store.learning_items.create(item)
        service.schedule_after_review(apply_review_event(None, event), event)

    due = service.list_due(NOW)
    assert [schedule.learning_item_id for schedule in due] == [active.id]
    assert store.review_schedules.get(suspended.id, "recognition") is not None
    assert store.review_schedules.get(mastered.id, "recognition") is not None


def test_list_due_with_fixed_now_is_deterministic(
    store: TutorSqliteStore, service: ReviewService
):
    item = _item()
    event = _event(item.id, occurred_at=NOW - timedelta(days=1))
    _schedule_event(store, service, item, event)

    first = service.list_due(NOW)
    second = service.list_due(NOW)
    assert first == second
    assert first[0].due_at == NOW


def test_schedule_after_review_requires_existing_learning_item(service: ReviewService):
    event = _event("missing-item")
    state = apply_review_event(None, event)
    with pytest.raises(ValueError, match="LearningItem が存在しない"):
        service.schedule_after_review(state, event)


def test_list_due_rejects_naive_datetime(service: ReviewService):
    with pytest.raises(ValueError, match="timezone-aware"):
        service.list_due(datetime(2026, 1, 1, 12, 0))


def test_schedule_after_review_updates_only_matching_direction(
    store: TutorSqliteStore, service: ReviewService
):
    item = _item()
    store.learning_items.create(item)

    rec_event = _event(
        item.id,
        result="correct",
        exercise_type="fr_to_ja",
        occurred_at=NOW - timedelta(days=4),
    )
    rec_state = apply_review_event(None, rec_event)
    service.schedule_after_review(rec_state, rec_event)
    rec2_event = _event(
        item.id,
        result="correct",
        exercise_type="meaning_recognition",
        occurred_at=NOW - timedelta(days=3),
    )
    rec2_state = apply_review_event(rec_state, rec2_event)
    rec2 = service.schedule_after_review(rec2_state, rec2_event)
    assert rec2.interval_days == 3.0
    assert rec2.review_count == 2
    assert rec2.skill_direction == "recognition"

    prod_event = _event(
        item.id,
        result="incorrect",
        exercise_type="ja_to_fr",
        occurred_at=NOW - timedelta(days=2),
    )
    mixed_state = apply_review_event(rec2_state, prod_event)
    prod = service.schedule_after_review(mixed_state, prod_event)

    assert prod.skill_direction == "production"
    assert prod.lapse_count == 1
    assert prod.review_count == 1
    assert prod.interval_days == 1.0
    loaded_rec = store.review_schedules.get(item.id, "recognition")
    assert loaded_rec == rec2
    assert loaded_rec is not None
    assert loaded_rec.lapse_count == 0
    assert loaded_rec.interval_days == 3.0
    assert loaded_rec.review_count == 2
    listed = store.review_schedules.list_for_item(item.id)
    assert [row.skill_direction for row in listed] == ["recognition", "production"]


def test_list_due_can_filter_by_direction(
    store: TutorSqliteStore, service: ReviewService
):
    item = _item()
    store.learning_items.create(item)
    rec_event = _event(
        item.id,
        occurred_at=NOW - timedelta(days=2),
        exercise_type="fr_to_ja",
    )
    prod_event = _event(
        item.id,
        occurred_at=NOW - timedelta(days=2),
        exercise_type="ja_to_fr",
        result="incorrect",
    )
    rec_state = apply_review_event(None, rec_event)
    service.schedule_after_review(rec_state, rec_event)
    service.schedule_after_review(apply_review_event(rec_state, prod_event), prod_event)

    both = service.list_due(NOW)
    assert [row.skill_direction for row in both] == ["production", "recognition"]
    rec_only = service.list_due(NOW, "recognition")
    assert [row.skill_direction for row in rec_only] == ["recognition"]
    prod_only = service.list_due(NOW, "production")
    assert [row.skill_direction for row in prod_only] == ["production"]
