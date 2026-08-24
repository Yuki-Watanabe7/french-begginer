"""Tutor永続化層（Issue #109）の Repository / SQLite 実装テスト。"""

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.tutor import (
    EvidenceSpan,
    LearnerState,
    LearningEvent,
    LearningItem,
    LearningItemCandidate,
    MasteryStats,
    ReviewSchedule,
    SourceDocument,
    SourceRef,
    utcnow,
)
from app.persistence.datetime_codec import dump_utc
from app.persistence.db import create_db_engine
from app.persistence.models import (
    Base,
    LearningItemCandidateRow,
    LearningItemRow,
    SchemaMigrationRow,
    SourceDocumentRow,
)
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


def _source(**overrides) -> SourceDocument:
    values = {
        "title": "Article",
        "content": "Oui, il s'agit de cela.",
    }
    values.update(overrides)
    return SourceDocument(**values)


def _candidate(source_id: str, **overrides) -> LearningItemCandidate:
    content = overrides.pop("source_content", "Oui, il s'agit de cela.")
    form = str(overrides.get("canonical_form", "il s'agit de"))
    start = content.index(form) if form in content else 0
    values = {
        "source_document_id": source_id,
        "item_type": "expression",
        "canonical_form": form,
        "meaning_ja": "〜が問題である",
        "evidence_span": EvidenceSpan(start=start, end=start + len(form)),
        "extraction_version": "extract-v1",
        "confidence": 0.91,
        "metadata": {"provider": "test", "model": "fixture"},
    }
    values.update(overrides)
    return LearningItemCandidate(**values)


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
    assert [doc.id for doc in listed] == [first.id, second.id]


def test_source_document_list_is_stable_for_same_created_at(store: TutorSqliteStore):
    same_time = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
    older = SourceDocument(
        id="src-old",
        title="old",
        content="old",
        created_at=same_time - timedelta(days=1),
    )
    a = SourceDocument(id="src-a", title="A", content="a", created_at=same_time)
    b = SourceDocument(id="src-b", title="B", content="b", created_at=same_time)
    newer = SourceDocument(
        id="src-new",
        title="new",
        content="new",
        created_at=same_time + timedelta(days=1),
    )
    store.source_documents.create(a)
    store.source_documents.create(newer)
    store.source_documents.create(older)
    store.source_documents.create(b)

    listed = store.source_documents.list()
    assert [doc.id for doc in listed] == ["src-new", "src-a", "src-b", "src-old"]
    assert [doc.id for doc in store.source_documents.list(limit=2)] == [
        "src-new",
        "src-a",
    ]


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


def test_learning_item_candidate_create_and_get_are_persisted(
    store: TutorSqliteStore,
):
    source = _source()
    store.source_documents.create(source)
    candidate = _candidate(
        source.id,
        explanation_ja="よく出る表現",
        level="A2",
    )
    store.learning_item_candidates.create(candidate)

    loaded = store.learning_item_candidates.get(candidate.id)
    assert loaded == candidate
    assert loaded is not None
    assert loaded.status == "candidate"
    assert loaded.extraction_version == "extract-v1"
    assert loaded.evidence_span.text is None
    assert source.content[loaded.evidence_span.start : loaded.evidence_span.end] == (
        "il s'agit de"
    )


def test_learning_item_candidate_list_by_source(store: TutorSqliteStore):
    source_a = _source(title="A", content="premier il s'agit de")
    source_b = _source(title="B", content="autre texte")
    store.source_documents.create(source_a)
    store.source_documents.create(source_b)

    older = _candidate(
        source_a.id,
        source_content=source_a.content,
        canonical_form="premier",
        meaning_ja="最初の",
        evidence_span=EvidenceSpan(start=0, end=7),
        created_at=utcnow(),
    )
    newer = _candidate(
        source_a.id,
        source_content=source_a.content,
        canonical_form="il s'agit de",
        meaning_ja="〜が問題である",
        created_at=utcnow() + timedelta(seconds=1),
    )
    other = _candidate(
        source_b.id,
        source_content=source_b.content,
        canonical_form="autre",
        meaning_ja="他の",
        evidence_span=EvidenceSpan(start=0, end=5),
    )
    store.learning_item_candidates.create(newer)
    store.learning_item_candidates.create(other)
    store.learning_item_candidates.create(older)

    listed = store.learning_item_candidates.list_by_source(source_a.id)
    assert [candidate.id for candidate in listed] == [older.id, newer.id]


def test_duplicate_learning_item_candidate_id_is_rejected(store: TutorSqliteStore):
    source = _source()
    store.source_documents.create(source)
    candidate = _candidate(source.id)
    store.learning_item_candidates.create(candidate)
    with pytest.raises(DuplicateEntityError):
        store.learning_item_candidates.create(candidate)


def test_candidate_create_requires_existing_source(store: TutorSqliteStore):
    with pytest.raises(ReferentialIntegrityError, match="SourceDocument"):
        store.learning_item_candidates.create(_candidate("missing-source"))


def test_candidate_status_update_is_persisted(store: TutorSqliteStore):
    source = _source()
    store.source_documents.create(source)
    candidate = _candidate(source.id)
    store.learning_item_candidates.create(candidate)

    accepted = store.learning_item_candidates.update_status(candidate.id, "accepted")
    assert accepted.status == "accepted"
    assert store.learning_item_candidates.get(candidate.id) == accepted

    with pytest.raises(ValueError, match="変更できない"):
        store.learning_item_candidates.update_status(candidate.id, "rejected")
    assert store.learning_item_candidates.get(candidate.id).status == "accepted"


def test_candidate_status_update_requires_existing_candidate(
    store: TutorSqliteStore,
):
    with pytest.raises(ReferentialIntegrityError, match="LearningItemCandidate"):
        store.learning_item_candidates.update_status("missing", "accepted")


def test_create_many_candidates_is_atomic(store: TutorSqliteStore):
    source = _source()
    store.source_documents.create(source)
    existing = _candidate(source.id)
    store.learning_item_candidates.create(existing)
    new = _candidate(
        source.id,
        canonical_form="premier",
        meaning_ja="最初の",
        evidence_span=EvidenceSpan(start=0, end=7),
        source_content=source.content,
    )
    duplicate = _candidate(source.id, id=existing.id)

    with pytest.raises(DuplicateEntityError):
        store.learning_item_candidates.create_many([new, duplicate])
    listed = store.learning_item_candidates.list_by_source(source.id)
    assert [candidate.id for candidate in listed] == [existing.id]


def test_create_many_empty_is_noop(store: TutorSqliteStore):
    assert store.learning_item_candidates.create_many([]) == []


def test_persist_accept_rolls_back_candidate_when_item_write_fails(
    store: TutorSqliteStore, monkeypatch: pytest.MonkeyPatch
):
    source = _source()
    store.source_documents.create(source)
    candidate = _candidate(source.id)
    store.learning_item_candidates.create(candidate)
    item = _item(
        source_refs=[
            SourceRef(
                source_document_id=source.id,
                evidence_span=candidate.evidence_span,
                confidence=candidate.confidence,
            )
        ]
    )
    accepted = candidate.model_copy(update={"status": "accepted"})
    original_add = Session.add

    def fail_item_add(self: Session, instance: object, _warn: bool = True) -> None:
        if isinstance(instance, LearningItemRow):
            raise RuntimeError("item write failed")
        original_add(self, instance, _warn=_warn)

    monkeypatch.setattr(Session, "add", fail_item_add)

    with pytest.raises(RuntimeError, match="item write failed"):
        store.candidate_promotions.persist_accept(accepted, item, create_item=True)

    assert store.learning_items.list() == []
    loaded = store.learning_item_candidates.get(candidate.id)
    assert loaded is not None
    assert loaded.status == "candidate"


def test_persist_accept_creates_item_and_accepts_candidate(store: TutorSqliteStore):
    source = _source()
    store.source_documents.create(source)
    candidate = _candidate(source.id)
    store.learning_item_candidates.create(candidate)
    item = _item(
        source_refs=[
            SourceRef(
                source_document_id=source.id,
                evidence_span=candidate.evidence_span,
                confidence=candidate.confidence,
            )
        ]
    )
    accepted = candidate.model_copy(update={"status": "accepted"})

    saved_candidate, saved_item = store.candidate_promotions.persist_accept(
        accepted, item, create_item=True
    )
    assert saved_candidate.status == "accepted"
    assert store.learning_item_candidates.get(candidate.id) == saved_candidate
    assert store.learning_items.get(item.id) == saved_item


def test_candidate_survives_reopen_without_affecting_existing_schema(
    tmp_path: Path,
):
    db_path = tmp_path / "tutor.db"
    url = f"sqlite:///{db_path}"
    store = TutorSqliteStore(url)
    source = _source()
    item = _item()
    store.source_documents.create(source)
    store.learning_items.create(item)
    candidate = _candidate(source.id)
    store.learning_item_candidates.create(candidate)
    store.engine.dispose()

    reopened = TutorSqliteStore(url)
    assert reopened.source_documents.get(source.id) == source
    assert reopened.learning_items.get(item.id) == item
    assert reopened.learning_item_candidates.get(candidate.id) == candidate
    assert inspect(reopened.engine).has_table("learning_items")
    assert inspect(reopened.engine).has_table("source_documents")
    reopened.engine.dispose()


def test_schema_upgrades_from_v1_and_preserves_existing_rows(tmp_path: Path):
    db_path = tmp_path / "legacy.db"
    url = f"sqlite:///{db_path}"
    engine = create_db_engine(url)
    v1_tables = [
        table
        for table in Base.metadata.sorted_tables
        if table.name != LearningItemCandidateRow.__tablename__
    ]
    Base.metadata.create_all(engine, tables=v1_tables)

    source = _source()
    item = _item()
    with Session(engine) as session:
        session.add(SchemaMigrationRow(version=1, applied_at=dump_utc(utcnow())))
        session.add(SourceDocumentRow.from_domain(source))
        session.add(LearningItemRow.from_domain(item))
        session.commit()
    assert get_schema_version(engine) == 1
    assert not inspect(engine).has_table(LearningItemCandidateRow.__tablename__)
    engine.dispose()

    store = TutorSqliteStore(url)
    assert get_schema_version(store.engine) == 2
    assert inspect(store.engine).has_table(LearningItemCandidateRow.__tablename__)
    assert store.source_documents.get(source.id) == source
    assert store.learning_items.get(item.id) == item

    candidate = _candidate(source.id)
    store.learning_item_candidates.create(candidate)
    assert store.learning_item_candidates.get(candidate.id) == candidate
    store.engine.dispose()


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
    assert not hasattr(TutorSqliteStore.in_memory().learning_item_candidates, "delete")


def test_get_missing_entities_returns_none(store: TutorSqliteStore):
    assert store.source_documents.get("missing") is None
    assert store.learning_items.get("missing") is None
    assert store.learning_item_candidates.get("missing") is None
    assert store.learner_states.get("missing") is None
    assert store.review_schedules.get("missing") is None
    assert store.learning_events.list_by_item("missing") == []
    assert store.learning_item_candidates.list_by_source("missing") == []
