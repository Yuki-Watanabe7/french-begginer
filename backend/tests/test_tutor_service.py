"""TutorService（Issue #112）のユースケーステスト。"""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.tutor import SourceDocument, SourceRef
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


def test_record_review_duplicate_event_id_raises_conflict(service: TutorService):
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
