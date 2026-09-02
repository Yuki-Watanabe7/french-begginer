"""TutorService（Issue #112）のユースケーステスト。"""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.domain.tutor import SourceDocument, SourceRef
from app.persistence.models import LearnerStateRow, ReviewScheduleRow
from app.repositories.sqlite import TutorSqliteStore
from app.services.exceptions import (
    InvalidSourceRefError,
    TutorConflictError,
    TutorNotFoundError,
)
from app.services.tutor_service import TutorService, build_tutor_service

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


@pytest.fixture
def store() -> TutorSqliteStore:
    return TutorSqliteStore.in_memory()


@pytest.fixture
def service(store: TutorSqliteStore) -> TutorService:
    return build_tutor_service(store, clock=lambda: NOW)


def test_create_and_get_source(service: TutorService):
    created = service.create_source(title="記事", content="Il s'agit d'un test.")
    loaded = service.get_source(created.id)
    assert loaded == created
    assert loaded.source_type == "manual_text"
    assert loaded.language == "fr"


def test_get_source_missing_raises_not_found(service: TutorService):
    with pytest.raises(TutorNotFoundError, match="SourceDocument"):
        service.get_source("missing-source")


def test_list_sources_empty(service: TutorService):
    assert service.list_sources() == []


def test_list_sources_newest_first_and_stable_for_same_created_at(
    store: TutorSqliteStore, service: TutorService
):
    same_time = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
    store.source_documents.create(
        SourceDocument(
            id="src-old",
            title="old",
            content="old",
            created_at=same_time - timedelta(seconds=1),
        )
    )
    store.source_documents.create(
        SourceDocument(id="src-b", title="B", content="b", created_at=same_time)
    )
    store.source_documents.create(
        SourceDocument(id="src-a", title="A", content="a", created_at=same_time)
    )

    listed = service.list_sources()
    assert [doc.id for doc in listed] == ["src-a", "src-b", "src-old"]
    assert [doc.id for doc in service.list_sources(limit=2)] == ["src-a", "src-b"]


def test_create_item_without_source_refs(service: TutorService):
    item = service.create_item(
        item_type="expression",
        canonical_form="il s'agit de",
        meaning_ja="〜が問題である",
    )
    detail = service.get_item(item.id)
    assert detail.item == item
    assert detail.learner_state is None
    assert detail.review_schedule is None
    assert detail.review_schedules == []


def test_create_item_with_existing_source_ref(
    store: TutorSqliteStore, service: TutorService
):
    source = store.source_documents.create(
        SourceDocument(title="src", content="bonjour")
    )
    item = service.create_item(
        item_type="vocabulary",
        canonical_form="bonjour",
        meaning_ja="こんにちは",
        source_refs=[SourceRef(source_document_id=source.id)],
    )
    assert item.source_refs[0].source_document_id == source.id


def test_create_item_rejects_unknown_source_ref(service: TutorService):
    with pytest.raises(InvalidSourceRefError, match="missing-source"):
        service.create_item(
            item_type="vocabulary",
            canonical_form="bonjour",
            meaning_ja="こんにちは",
            source_refs=[SourceRef(source_document_id="missing-source")],
        )


def test_get_item_missing_raises_not_found(service: TutorService):
    with pytest.raises(TutorNotFoundError, match="LearningItem"):
        service.get_item("missing-item")


def test_list_items_returns_active_only(service: TutorService):
    active = service.create_item(
        item_type="vocabulary",
        canonical_form="livre",
        meaning_ja="本",
    )
    service.create_item(
        item_type="vocabulary",
        canonical_form="eau",
        meaning_ja="水",
        status="suspended",
    )
    listed = service.list_items()
    assert [item.id for item in listed] == [active.id]


def test_list_items_empty(service: TutorService):
    assert service.list_items() == []


def test_record_review_updates_event_state_and_schedule(
    store: TutorSqliteStore, service: TutorService
):
    item = service.create_item(
        item_type="expression",
        canonical_form="il s'agit de",
        meaning_ja="〜が問題である",
    )
    occurred_at = NOW - timedelta(days=2)
    record = service.record_review(
        item.id,
        exercise_type="fr_to_ja",
        result="correct",
        occurred_at=occurred_at,
    )

    assert record.event.learning_item_id == item.id
    assert record.event.result == "correct"
    assert record.learner_state.attempt_count == 1
    assert record.learner_state.correct_count == 1
    assert record.learner_state.last_reviewed_at == occurred_at
    assert record.review_schedule.due_at == occurred_at + timedelta(days=1)
    assert record.review_schedule.interval_days == 1.0
    assert store.learning_events.list_by_item(item.id) == [record.event]
    assert store.learner_states.get(item.id) == record.learner_state
    assert store.review_schedules.get(item.id, "recognition") == record.review_schedule

    detail = service.get_item(item.id)
    assert detail.learner_state == record.learner_state
    assert detail.review_schedule == record.review_schedule
    assert detail.review_schedules == [record.review_schedule]


def test_record_review_omitted_occurred_at_uses_clock(service: TutorService):
    item = service.create_item(
        item_type="expression",
        canonical_form="merci",
        meaning_ja="ありがとう",
    )
    record = service.record_review(
        item.id, exercise_type="ja_to_fr", result="incorrect"
    )
    assert record.event.occurred_at == NOW
    assert record.learner_state.last_reviewed_at == NOW
    assert record.review_schedule.due_at == NOW + timedelta(days=1)
    assert record.review_schedule.skill_direction == "production"


def test_record_review_missing_item_raises_not_found(service: TutorService):
    with pytest.raises(TutorNotFoundError, match="LearningItem"):
        service.record_review(
            "missing-item", exercise_type="fr_to_ja", result="correct"
        )


def test_record_review_duplicate_event_id_raises_conflict(
    store: TutorSqliteStore, service: TutorService
):
    item = service.create_item(
        item_type="expression",
        canonical_form="merci",
        meaning_ja="ありがとう",
    )
    service.record_review(
        item.id,
        exercise_type="fr_to_ja",
        result="correct",
        event_id="evt-1",
    )
    with pytest.raises(TutorConflictError, match="LearningEvent"):
        service.record_review(
            item.id,
            exercise_type="fr_to_ja",
            result="incorrect",
            event_id="evt-1",
        )
    detail = service.get_item(item.id)
    assert detail.learner_state is not None
    assert detail.learner_state.attempt_count == 1
    assert detail.learner_state.correct_count == 1
    assert detail.review_schedule is not None
    assert detail.review_schedule.review_count == 1
    assert len(store.learning_events.list_by_item(item.id)) == 1


def test_record_review_state_failure_rolls_back_event_and_schedule(
    store: TutorSqliteStore,
    service: TutorService,
    monkeypatch: pytest.MonkeyPatch,
):
    item = service.create_item(
        item_type="expression",
        canonical_form="merci",
        meaning_ja="ありがとう",
    )
    original_merge = Session.merge

    def fail_state_merge(self: Session, instance: object, **kwargs: object) -> object:
        if isinstance(instance, LearnerStateRow):
            raise RuntimeError("state write failed")
        return original_merge(self, instance, **kwargs)

    monkeypatch.setattr(Session, "merge", fail_state_merge)

    with pytest.raises(RuntimeError, match="state write failed"):
        service.record_review(item.id, exercise_type="fr_to_ja", result="correct")

    assert store.learning_events.list_by_item(item.id) == []
    assert store.learner_states.get(item.id) is None
    assert store.review_schedules.get(item.id, "recognition") is None


def test_record_review_schedule_failure_rolls_back_event_and_state(
    store: TutorSqliteStore,
    service: TutorService,
    monkeypatch: pytest.MonkeyPatch,
):
    item = service.create_item(
        item_type="expression",
        canonical_form="merci",
        meaning_ja="ありがとう",
    )
    original_merge = Session.merge

    def fail_schedule_merge(
        self: Session, instance: object, **kwargs: object
    ) -> object:
        if isinstance(instance, ReviewScheduleRow):
            raise RuntimeError("schedule write failed")
        return original_merge(self, instance, **kwargs)

    monkeypatch.setattr(Session, "merge", fail_schedule_merge)

    with pytest.raises(RuntimeError, match="schedule write failed"):
        service.record_review(item.id, exercise_type="fr_to_ja", result="correct")

    assert store.learning_events.list_by_item(item.id) == []
    assert store.learner_states.get(item.id) is None
    assert store.review_schedules.get(item.id, "recognition") is None


def test_list_review_queue_uses_stored_schedule_without_replaying_history(
    store: TutorSqliteStore,
    service: TutorService,
):
    item = service.create_item(
        item_type="expression",
        canonical_form="bonjour",
        meaning_ja="こんにちは",
    )
    record = service.record_review(
        item.id,
        exercise_type="fr_to_ja",
        result="correct",
        occurred_at=NOW - timedelta(days=2),
    )
    assert record.review_schedule.due_at < NOW
    stored = record.review_schedule.model_copy(
        update={"due_at": NOW + timedelta(days=30)}
    )
    store.review_schedules.upsert(stored)

    queue = service.list_review_queue(NOW)
    assert queue.summary.total_due == 0
    assert queue.entries == ()
    assert store.learning_events.list_by_item(item.id) == [record.event]


def test_list_due_uses_injected_now_not_wall_clock(service: TutorService):
    item = service.create_item(
        item_type="expression",
        canonical_form="bonjour",
        meaning_ja="こんにちは",
    )
    service.record_review(
        item.id,
        exercise_type="fr_to_ja",
        result="correct",
        occurred_at=NOW - timedelta(days=1),
    )

    due_now = service.list_due(NOW)
    assert [row.item.id for row in due_now] == [item.id]
    assert due_now[0].review_schedule.due_at == NOW
    assert due_now[0].learner_state is not None

    not_yet = service.list_due(NOW - timedelta(seconds=1))
    assert not_yet == []


def test_list_due_without_now_uses_clock(service: TutorService):
    item = service.create_item(
        item_type="expression",
        canonical_form="bonjour",
        meaning_ja="こんにちは",
    )
    service.record_review(
        item.id,
        exercise_type="fr_to_ja",
        result="correct",
        occurred_at=NOW - timedelta(days=1),
    )
    due = service.list_due()
    assert [row.item.id for row in due] == [item.id]


def test_list_review_queue_excludes_future_and_includes_due_at_now(
    service: TutorService,
):
    due_item = service.create_item(
        item_type="vocabulary",
        canonical_form="due",
        meaning_ja="期限到来",
    )
    future_item = service.create_item(
        item_type="vocabulary",
        canonical_form="future",
        meaning_ja="未到来",
    )
    service.record_review(
        due_item.id,
        exercise_type="fr_to_ja",
        result="correct",
        occurred_at=NOW - timedelta(days=1),
    )
    service.record_review(
        future_item.id,
        exercise_type="fr_to_ja",
        result="correct",
        occurred_at=NOW,
    )

    queue = service.list_review_queue(NOW)
    assert [row.item.id for row in queue.entries] == [due_item.id]
    assert queue.entries[0].skill_direction == "recognition"
    assert queue.entries[0].overdue_seconds == 0
    assert queue.summary.total_due == 1
    assert queue.summary.overdue_count == 0
    assert service.list_review_queue(NOW - timedelta(seconds=1)).entries == ()


def test_list_review_queue_without_now_uses_clock(service: TutorService):
    item = service.create_item(
        item_type="vocabulary",
        canonical_form="bonjour",
        meaning_ja="こんにちは",
    )
    service.record_review(
        item.id,
        exercise_type="fr_to_ja",
        result="correct",
        occurred_at=NOW - timedelta(days=1),
    )
    queue = service.list_review_queue()
    assert [row.item.id for row in queue.entries] == [item.id]


def test_list_review_queue_keeps_recognition_and_production_separate(
    service: TutorService,
):
    item = service.create_item(
        item_type="vocabulary",
        canonical_form="livre",
        meaning_ja="本",
    )
    service.record_review(
        item.id,
        exercise_type="fr_to_ja",
        result="correct",
        occurred_at=NOW - timedelta(days=2),
    )
    service.record_review(
        item.id,
        exercise_type="ja_to_fr",
        result="incorrect",
        occurred_at=NOW - timedelta(days=1),
    )
    queue = service.list_review_queue(NOW)
    assert [row.skill_direction for row in queue.entries] == [
        "recognition",
        "production",
    ]
    assert queue.summary.recognition_due == 1
    assert queue.summary.production_due == 1
    assert queue.entries[0].learner_state is not None
    assert "recognition" in queue.entries[0].learner_state.by_direction
    assert "production" in queue.entries[1].learner_state.by_direction
    assert all(row.available_exercise_types for row in queue.entries)


def test_list_review_queue_returns_only_due_direction(service: TutorService):
    item = service.create_item(
        item_type="vocabulary",
        canonical_form="chat",
        meaning_ja="猫",
    )
    service.record_review(
        item.id,
        exercise_type="fr_to_ja",
        result="correct",
        occurred_at=NOW - timedelta(days=1),
    )
    service.record_review(
        item.id,
        exercise_type="ja_to_fr",
        result="correct",
        occurred_at=NOW,
    )
    queue = service.list_review_queue(NOW)
    assert [row.skill_direction for row in queue.entries] == ["recognition"]
    assert queue.summary.production_due == 0


def test_list_review_queue_excludes_suspended_mastered_and_unscheduled(
    service: TutorService,
):
    active = service.create_item(
        item_type="vocabulary",
        canonical_form="active",
        meaning_ja="学習中",
    )
    suspended = service.create_item(
        item_type="vocabulary",
        canonical_form="suspended",
        meaning_ja="停止",
        status="suspended",
    )
    mastered = service.create_item(
        item_type="vocabulary",
        canonical_form="mastered",
        meaning_ja="定着",
        status="mastered",
    )
    unscheduled = service.create_item(
        item_type="vocabulary",
        canonical_form="new",
        meaning_ja="未学習",
    )
    for item in (active, suspended, mastered):
        service.record_review(
            item.id,
            exercise_type="fr_to_ja",
            result="correct",
            occurred_at=NOW - timedelta(days=1),
        )
    queue = service.list_review_queue(NOW)
    assert [row.item.id for row in queue.entries] == [active.id]
    assert unscheduled.id not in [row.item.id for row in queue.entries]


def test_list_review_queue_limit_does_not_shrink_summary(service: TutorService):
    items = [
        service.create_item(
            item_type="vocabulary",
            canonical_form=f"mot-{index}",
            meaning_ja=f"語{index}",
        )
        for index in range(3)
    ]
    for index, item in enumerate(items):
        service.record_review(
            item.id,
            exercise_type="fr_to_ja",
            result="correct",
            occurred_at=NOW - timedelta(days=index + 1),
        )
    queue = service.list_review_queue(NOW, limit=1)
    assert len(queue.entries) == 1
    assert queue.summary.total_due == 3
    assert queue.entries[0].item.id == items[-1].id


def test_list_review_queue_empty(service: TutorService):
    queue = service.list_review_queue(NOW)
    assert queue.entries == ()
    assert queue.summary.total_due == 0


def test_list_review_queue_rejects_naive_datetime(service: TutorService):
    with pytest.raises(ValueError, match="timezone-aware"):
        service.list_review_queue(datetime(2026, 1, 1, 12, 0))


def test_list_due_phase0_contract_still_returns_due_items(service: TutorService):
    item = service.create_item(
        item_type="vocabulary",
        canonical_form="bonjour",
        meaning_ja="こんにちは",
    )
    service.record_review(
        item.id,
        exercise_type="fr_to_ja",
        result="correct",
        occurred_at=NOW - timedelta(days=1),
    )
    due = service.list_due(NOW)
    assert [row.item.id for row in due] == [item.id]
    assert due[0].review_schedule.skill_direction == "recognition"


def test_list_review_queue_timezone_boundary_uses_utc(service: TutorService):
    utc_midnight = datetime(2026, 1, 1, tzinfo=UTC)
    jst = timezone(timedelta(hours=9))
    item = service.create_item(
        item_type="vocabulary",
        canonical_form="minuit",
        meaning_ja="真夜中",
    )
    service.record_review(
        item.id,
        exercise_type="fr_to_ja",
        result="correct",
        occurred_at=utc_midnight - timedelta(days=1),
    )
    at_jst = service.list_review_queue(datetime(2026, 1, 1, 9, 0, tzinfo=jst))
    assert [row.item.id for row in at_jst.entries] == [item.id]
    before_jst = service.list_review_queue(datetime(2026, 1, 1, 8, 59, 59, tzinfo=jst))
    assert before_jst.entries == ()
