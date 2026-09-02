"""ReviewScheduleRebuilder（Issue #166）のユースケーステスト。"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.domain.review_scheduler import SCHEDULER_VERSION
from app.domain.tutor import LearningItem, ReviewSchedule
from app.repositories.sqlite import TutorSqliteStore
from app.services.review_schedule_rebuilder import (
    ReviewScheduleRebuilder,
    build_review_schedule_rebuilder,
)
from app.services.tutor_service import build_tutor_service

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


def _item(**overrides) -> LearningItem:
    values = {
        "item_type": "expression",
        "canonical_form": "il s'agit de",
        "meaning_ja": "〜が問題である",
    }
    values.update(overrides)
    return LearningItem(**values)


@pytest.fixture
def store() -> TutorSqliteStore:
    return TutorSqliteStore.in_memory()


@pytest.fixture
def rebuilder(store: TutorSqliteStore) -> ReviewScheduleRebuilder:
    return build_review_schedule_rebuilder(
        learning_items=store.learning_items,
        learning_events=store.learning_events,
        review_schedules=store.review_schedules,
    )


def _record_both_directions(store: TutorSqliteStore, item: LearningItem) -> None:
    tutor = build_tutor_service(store, clock=lambda: NOW)
    tutor.record_review(
        item.id,
        exercise_type="fr_to_ja",
        result="correct",
        occurred_at=NOW - timedelta(days=3),
    )
    tutor.record_review(
        item.id,
        exercise_type="ja_to_fr",
        result="incorrect",
        occurred_at=NOW - timedelta(days=2),
    )


def test_rebuild_from_missing_schedule(
    store: TutorSqliteStore, rebuilder: ReviewScheduleRebuilder
):
    item = store.learning_items.create(_item())
    _record_both_directions(store, item)
    original = store.review_schedules.get(item.id, "recognition")
    assert original is not None
    store.review_schedules.replace_for_item(
        item.id,
        [
            sched
            for sched in store.review_schedules.list_for_item(item.id)
            if sched.skill_direction == "production"
        ],
    )
    assert store.review_schedules.get(item.id, "recognition") is None

    found = rebuilder.detect_inconsistencies(item.id)
    assert [item.kind for item in found] == ["missing_schedule"]
    assert found[0].skill_direction == "recognition"

    rebuilt = rebuilder.rebuild_for_item(item.id)
    assert [schedule.skill_direction for schedule in rebuilt] == [
        "recognition",
        "production",
    ]
    restored = store.review_schedules.get(item.id, "recognition")
    assert restored == original
    assert rebuilder.detect_inconsistencies(item.id) == []


def test_rebuild_recognition_only_missing_leaves_production(
    store: TutorSqliteStore, rebuilder: ReviewScheduleRebuilder
):
    item = store.learning_items.create(_item())
    _record_both_directions(store, item)
    production = store.review_schedules.get(item.id, "production")
    assert production is not None
    store.review_schedules.replace_for_item(item.id, [production])

    rebuilt = rebuilder.rebuild_for_item(item.id)
    assert store.review_schedules.get(item.id, "production") == production
    recognition = next(
        schedule for schedule in rebuilt if schedule.skill_direction == "recognition"
    )
    assert recognition.review_count == 1
    assert recognition.lapse_count == 0


def test_rebuild_production_only_missing(
    store: TutorSqliteStore, rebuilder: ReviewScheduleRebuilder
):
    item = store.learning_items.create(_item())
    _record_both_directions(store, item)
    recognition = store.review_schedules.get(item.id, "recognition")
    assert recognition is not None
    store.review_schedules.replace_for_item(item.id, [recognition])

    rebuilder.rebuild_for_item(item.id)
    restored = store.review_schedules.get(item.id, "production")
    assert restored is not None
    assert restored.review_count == 1
    assert restored.lapse_count == 1
    assert restored.due_at == NOW - timedelta(days=1)


def test_rebuild_replay_matches_review_count_lapse_and_due_at(
    store: TutorSqliteStore, rebuilder: ReviewScheduleRebuilder
):
    item = store.learning_items.create(_item())
    tutor = build_tutor_service(store, clock=lambda: NOW)
    first = tutor.record_review(
        item.id,
        exercise_type="fr_to_ja",
        result="correct",
        occurred_at=NOW - timedelta(days=4),
    )
    second = tutor.record_review(
        item.id,
        exercise_type="fr_to_ja",
        result="incorrect",
        occurred_at=NOW - timedelta(days=3),
    )
    expected = store.review_schedules.get(item.id, "recognition")
    assert expected is not None
    store.review_schedules.replace_for_item(item.id, [])

    rebuilt = rebuilder.rebuild_for_item(item.id)
    assert len(rebuilt) == 1
    schedule = rebuilt[0]
    assert schedule.review_count == 2
    assert schedule.lapse_count == 1
    assert schedule.due_at == second.event.occurred_at + timedelta(days=1)
    assert schedule.interval_days == 1.0
    assert schedule == expected
    assert first.review_schedule.review_count == 1


def test_rebuild_stale_scheduler_version(
    store: TutorSqliteStore, rebuilder: ReviewScheduleRebuilder
):
    item = store.learning_items.create(_item())
    _record_both_directions(store, item)
    current = store.review_schedules.get(item.id, "recognition")
    assert current is not None
    stale = current.model_copy(update={"scheduler_version": "v0-legacy"})
    production = store.review_schedules.get(item.id, "production")
    assert production is not None
    store.review_schedules.replace_for_item(item.id, [stale, production])

    found = rebuilder.detect_inconsistencies(item.id)
    assert [item.kind for item in found] == ["stale_scheduler_version"]
    rebuilt = rebuilder.rebuild_for_item(item.id)
    recognition = next(
        schedule for schedule in rebuilt if schedule.skill_direction == "recognition"
    )
    assert recognition.scheduler_version == SCHEDULER_VERSION
    assert rebuilder.detect_inconsistencies(item.id) == []


def test_rebuild_is_idempotent(
    store: TutorSqliteStore, rebuilder: ReviewScheduleRebuilder
):
    item = store.learning_items.create(_item())
    _record_both_directions(store, item)
    first = rebuilder.rebuild_for_item(item.id)
    second = rebuilder.rebuild_for_item(item.id)
    assert first == second
    assert store.review_schedules.list_for_item(item.id) == first


def test_rebuild_all_repairs_multiple_items(
    store: TutorSqliteStore, rebuilder: ReviewScheduleRebuilder
):
    first = store.learning_items.create(
        _item(canonical_form="bonjour", meaning_ja="こんにちは")
    )
    second = store.learning_items.create(
        _item(canonical_form="merci", meaning_ja="ありがとう")
    )
    _record_both_directions(store, first)
    tutor = build_tutor_service(store, clock=lambda: NOW)
    tutor.record_review(
        second.id,
        exercise_type="ja_to_fr",
        result="correct",
        occurred_at=NOW - timedelta(days=1),
    )
    store.review_schedules.replace_for_item(first.id, [])
    store.review_schedules.replace_for_item(second.id, [])

    rebuilt = rebuilder.rebuild_all()
    assert set(rebuilt) == {first.id, second.id}
    assert store.review_schedules.get(first.id, "recognition") is not None
    assert store.review_schedules.get(second.id, "production") is not None


def test_rebuild_survives_db_reopen(tmp_path: Path):
    db_path = tmp_path / "tutor-rebuild.db"
    url = f"sqlite:///{db_path}"
    store = TutorSqliteStore(url)
    service = build_review_schedule_rebuilder(
        learning_items=store.learning_items,
        learning_events=store.learning_events,
        review_schedules=store.review_schedules,
    )
    item = store.learning_items.create(_item())
    _record_both_directions(store, item)
    store.review_schedules.replace_for_item(item.id, [])
    rebuilt = service.rebuild_for_item(item.id)
    store.engine.dispose()

    reopened = TutorSqliteStore(url)
    loaded = reopened.review_schedules.list_for_item(item.id)
    assert loaded == rebuilt
    reopened.engine.dispose()


def test_replace_for_item_failure_leaves_previous_schedules(
    store: TutorSqliteStore, monkeypatch: pytest.MonkeyPatch
):
    item = store.learning_items.create(_item())
    _record_both_directions(store, item)
    previous = store.review_schedules.list_for_item(item.id)
    replacement = [
        ReviewSchedule(
            learning_item_id=item.id,
            skill_direction="recognition",
            due_at=NOW + timedelta(days=14),
            interval_days=14.0,
            review_count=9,
            scheduler_version=SCHEDULER_VERSION,
        )
    ]

    def fail_commit(self: Session) -> None:
        raise RuntimeError("replace failed")

    monkeypatch.setattr(Session, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="replace failed"):
        store.review_schedules.replace_for_item(item.id, replacement)

    monkeypatch.undo()
    assert store.review_schedules.list_for_item(item.id) == previous


def test_rebuild_requires_existing_item(rebuilder: ReviewScheduleRebuilder):
    with pytest.raises(ValueError, match="LearningItem が存在しない"):
        rebuilder.rebuild_for_item("missing-item")


def test_detect_requires_existing_item(rebuilder: ReviewScheduleRebuilder):
    with pytest.raises(ValueError, match="LearningItem が存在しない"):
        rebuilder.detect_inconsistencies("missing-item")


def test_rebuild_with_no_events_clears_schedules(
    store: TutorSqliteStore, rebuilder: ReviewScheduleRebuilder
):
    item = store.learning_items.create(_item())
    store.review_schedules.upsert(
        ReviewSchedule(
            learning_item_id=item.id,
            skill_direction="recognition",
            due_at=NOW,
            interval_days=1.0,
            review_count=1,
        )
    )
    assert rebuilder.rebuild_for_item(item.id) == []
    assert store.review_schedules.list_for_item(item.id) == []
    found = rebuilder.detect_inconsistencies(item.id)
    assert found == []
