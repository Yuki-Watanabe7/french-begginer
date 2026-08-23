"""Tutor永続化層（Issue #109）の Repository / SQLite 実装テスト。"""

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.domain.tutor import (
    LearnerState,
    LearningEvent,
    LearningItem,
    MasteryStats,
    ReviewSchedule,
    SourceDocument,
    SourceRef,
    utcnow,
)
from app.persistence.datetime_codec import dump_utc
from app.persistence.schema import (
    CURRENT_SCHEMA_VERSION,
    SchemaVersionError,
    get_schema_version,
    init_schema,
)
from app.repositories.exceptions import DuplicateEntityError, ReferentialIntegrityError
from app.repositories.sqlite import TutorSqliteStore


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
    }
    values.update(overrides)
    return LearningEvent(**values)


def _schedule(item_id: str, due_at: datetime, **overrides) -> ReviewSchedule:
    values = {
        "learning_item_id": item_id,
        "due_at": due_at,
        "interval_days": 1.0,
    }
    values.update(overrides)
    return ReviewSchedule(**values)


@pytest.fixture
def store() -> TutorSqliteStore:
    return TutorSqliteStore.in_memory()


def test_source_document_create_get_list(store: TutorSqliteStore):
    earlier = utcnow() - timedelta(minutes=1)
    later = utcnow()
    first = SourceDocument(title="A", content="bonjour", created_at=later)
    second = SourceDocument(title="B", content="merci", created_at=earlier)

    store.source_documents.create(first)
    store.source_documents.create(second)

    assert store.source_documents.get(first.id) == first
    listed = store.source_documents.list()
    assert [doc.id for doc in listed] == [second.id, first.id]


def test_learning_item_create_and_get_are_persisted(store: TutorSqliteStore):
    item = _item(
        source_refs=[SourceRef(source_document_id="doc-1")],
        explanation_ja="よく使う表現",
        level="A2",
    )
    store.learning_items.create(item)

    loaded = store.learning_items.get(item.id)
    assert loaded == item
    assert loaded is not None
    assert loaded.source_refs[0].source_document_id == "doc-1"


def test_learning_item_list_orders_by_created_at(store: TutorSqliteStore):
    older = _item(canonical_form="merci", meaning_ja="ありがとう", created_at=utcnow())
    newer = _item(
        canonical_form="bonjour",
        meaning_ja="こんにちは",
        created_at=utcnow() + timedelta(seconds=1),
    )
    store.learning_items.create(newer)
    store.learning_items.create(older)
    assert [item.id for item in store.learning_items.list()] == [older.id, newer.id]


def test_duplicate_learning_item_id_is_rejected(store: TutorSqliteStore):
    item = _item()
    store.learning_items.create(item)
    with pytest.raises(DuplicateEntityError):
        store.learning_items.create(item)


def test_learning_events_append_and_list_in_occurred_at_order(
    store: TutorSqliteStore,
):
    item = _item()
    store.learning_items.create(item)

    t0 = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    t1 = datetime(2026, 1, 1, 11, 0, tzinfo=UTC)
    t2 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    later = _event(item.id, occurred_at=t2, result="incorrect")
    earlier = _event(item.id, occurred_at=t0, result="correct")
    middle = _event(item.id, occurred_at=t1, result="correct")

    store.learning_events.append(later)
    store.learning_events.append(earlier)
    store.learning_events.append(middle)

    events = store.learning_events.list_by_item(item.id)
    assert [event.id for event in events] == [earlier.id, middle.id, later.id]
    assert [event.result for event in events] == ["correct", "correct", "incorrect"]


def test_list_by_item_does_not_include_other_items(store: TutorSqliteStore):
    item_a = _item(canonical_form="a", meaning_ja="A")
    item_b = _item(canonical_form="b", meaning_ja="B")
    store.learning_items.create(item_a)
    store.learning_items.create(item_b)
    store.learning_events.append(_event(item_a.id))
    store.learning_events.append(_event(item_b.id))

    events_a = store.learning_events.list_by_item(item_a.id)
    assert len(events_a) == 1
    assert events_a[0].learning_item_id == item_a.id


def test_append_event_requires_existing_learning_item(store: TutorSqliteStore):
    with pytest.raises(ReferentialIntegrityError):
        store.learning_events.append(_event("missing-item"))


def test_learner_state_upsert_and_get(store: TutorSqliteStore):
    item = _item()
    store.learning_items.create(item)

    first = LearnerState(learning_item_id=item.id)
    store.learner_states.upsert(first)
    assert store.learner_states.get(item.id) == first

    reviewed_at = utcnow()
    updated = LearnerState(
        learning_item_id=item.id,
        attempt_count=3,
        correct_count=2,
        incorrect_count=1,
        consecutive_correct=1,
        last_reviewed_at=reviewed_at,
        mastery_score=0.6,
        by_direction={
            "recognition": MasteryStats(
                attempt_count=2,
                correct_count=2,
                incorrect_count=0,
                consecutive_correct=2,
                last_reviewed_at=reviewed_at,
                mastery_score=0.9,
            )
        },
    )
    store.learner_states.upsert(updated)
    loaded = store.learner_states.get(item.id)
    assert loaded == updated
    assert loaded is not None
    assert loaded.by_direction["recognition"].mastery_score == 0.9


def test_review_schedule_upsert_and_list_due(store: TutorSqliteStore):
    now = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
    due_item = _item(canonical_form="due", meaning_ja="期限到来")
    equal_item = _item(canonical_form="equal", meaning_ja="ちょうど期限")
    future_item = _item(canonical_form="future", meaning_ja="未到来")
    for item in (due_item, equal_item, future_item):
        store.learning_items.create(item)

    store.review_schedules.upsert(
        _schedule(due_item.id, now - timedelta(hours=1), interval_days=0.5)
    )
    store.review_schedules.upsert(_schedule(equal_item.id, now, interval_days=1.0))
    store.review_schedules.upsert(
        _schedule(future_item.id, now + timedelta(hours=1), interval_days=2.0)
    )

    due = store.review_schedules.list_due(now)
    assert [schedule.learning_item_id for schedule in due] == [
        due_item.id,
        equal_item.id,
    ]

    updated = _schedule(due_item.id, now + timedelta(days=3), interval_days=3.0)
    store.review_schedules.upsert(updated)
    assert store.review_schedules.get(due_item.id) == updated
    assert [
        schedule.learning_item_id for schedule in store.review_schedules.list_due(now)
    ] == [equal_item.id]


def test_state_and_schedule_require_existing_learning_item(store: TutorSqliteStore):
    with pytest.raises(ReferentialIntegrityError):
        store.learner_states.upsert(LearnerState(learning_item_id="missing"))
    with pytest.raises(ReferentialIntegrityError):
        store.review_schedules.upsert(_schedule("missing", utcnow()))


def test_learning_item_delete_is_restricted_while_events_exist(
    store: TutorSqliteStore,
):
    """履歴消失を防ぐため LearningItem は FK RESTRICT で削除できない。"""
    item = _item()
    store.learning_items.create(item)
    store.learning_events.append(_event(item.id))

    with store.engine.connect() as conn:
        with pytest.raises(IntegrityError, match="FOREIGN KEY"):
            with conn.begin():
                conn.execute(
                    text("DELETE FROM learning_items WHERE id = :id"),
                    {"id": item.id},
                )


def test_datetime_roundtrip_normalizes_to_utc(store: TutorSqliteStore):
    jst = timezone(timedelta(hours=9))
    created_at = datetime(2026, 1, 2, 9, 0, tzinfo=jst)
    item = _item(created_at=created_at)
    store.learning_items.create(item)

    loaded = store.learning_items.get(item.id)
    assert loaded is not None
    assert loaded.created_at == datetime(2026, 1, 2, 0, 0, tzinfo=UTC)


def test_list_due_rejects_naive_datetime(store: TutorSqliteStore):
    with pytest.raises(ValueError, match="timezone-aware"):
        store.review_schedules.list_due(datetime(2026, 1, 1, 12, 0))


def test_list_due_excludes_suspended_and_mastered_items(store: TutorSqliteStore):
    now = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
    active = _item(canonical_form="active", meaning_ja="学習中")
    suspended = _item(canonical_form="suspended", meaning_ja="停止", status="suspended")
    mastered = _item(canonical_form="mastered", meaning_ja="定着", status="mastered")
    for item in (active, suspended, mastered):
        store.learning_items.create(item)
        store.review_schedules.upsert(_schedule(item.id, now - timedelta(hours=1)))

    due = store.review_schedules.list_due(now)
    assert [schedule.learning_item_id for schedule in due] == [active.id]


def test_temporary_file_db_is_isolated(tmp_path: Path):
    path_a = tmp_path / "a.db"
    path_b = tmp_path / "b.db"
    store_a = TutorSqliteStore(f"sqlite:///{path_a}")
    store_b = TutorSqliteStore(f"sqlite:///{path_b}")

    item = _item()
    store_a.learning_items.create(item)

    assert store_a.learning_items.get(item.id) is not None
    assert store_b.learning_items.get(item.id) is None
    assert path_a.exists()
    assert path_b.exists()


def test_in_memory_stores_do_not_share_data():
    store_a = TutorSqliteStore.in_memory()
    store_b = TutorSqliteStore.in_memory()
    item = _item()
    store_a.learning_items.create(item)
    assert store_b.learning_items.get(item.id) is None


def test_database_url_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    db_path = tmp_path / "env.db"
    monkeypatch.setenv("TUTOR_DATABASE_URL", f"sqlite:///{db_path}")
    store = TutorSqliteStore.from_env()
    store.learning_items.create(_item())
    assert db_path.exists()


def test_schema_version_is_recorded(store: TutorSqliteStore):
    assert get_schema_version(store.engine) == CURRENT_SCHEMA_VERSION


def test_init_schema_is_idempotent(store: TutorSqliteStore):
    init_schema(store.engine)
    assert get_schema_version(store.engine) == CURRENT_SCHEMA_VERSION
    store.learning_items.create(_item())
    init_schema(store.engine)
    assert len(store.learning_items.list()) == 1


def test_newer_schema_version_is_rejected(store: TutorSqliteStore):
    with store.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (:v, :at)"
            ),
            {"v": CURRENT_SCHEMA_VERSION + 1, "at": dump_utc(utcnow())},
        )
    with pytest.raises(SchemaVersionError):
        init_schema(store.engine)


def test_learning_item_repository_has_no_delete():
    assert not hasattr(TutorSqliteStore.in_memory().learning_items, "delete")


def test_get_missing_entities_returns_none(store: TutorSqliteStore):
    assert store.source_documents.get("missing") is None
    assert store.learning_items.get("missing") is None
    assert store.learner_states.get("missing") is None
    assert store.review_schedules.get("missing") is None
    assert store.learning_events.list_by_item("missing") == []
