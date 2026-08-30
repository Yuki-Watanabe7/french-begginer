"""PracticeSessionService（Issue #150）のユースケーステスト。"""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.tutor import (
    EvidenceSpan,
    LearningItem,
    SourceDocument,
    SourceRef,
)
from app.repositories.sqlite import TutorSqliteStore
from app.services.exceptions import InvalidPracticeFilterError, TutorNotFoundError
from app.services.practice_session_service import build_practice_session_service

CREATED = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def store() -> TutorSqliteStore:
    return TutorSqliteStore.in_memory()


@pytest.fixture
def sessions(store: TutorSqliteStore):
    return build_practice_session_service(store)


def _vocab_pool(store: TutorSqliteStore) -> list[LearningItem]:
    specs = (("livre", "本"), ("maison", "家"), ("chat", "猫"), ("chien", "犬"))
    items: list[LearningItem] = []
    for index, (form, meaning) in enumerate(specs):
        items.append(
            store.learning_items.create(
                LearningItem(
                    item_type="vocabulary",
                    canonical_form=form,
                    meaning_ja=meaning,
                    created_at=CREATED + timedelta(seconds=index),
                )
            )
        )
    return items


def test_create_session_from_all_active_items(store: TutorSqliteStore, sessions):
    _vocab_pool(store)
    session = sessions.create_session(question_count=5, seed="fixed")
    assert session.generated_count == 5
    assert session.requested_count == 5
    assert session.session_id
    keys = [
        (row.spec.learning_item_id, row.spec.exercise_type) for row in session.exercises
    ]
    assert len(keys) == len(set(keys))


def test_missing_source_returns_not_found(sessions):
    with pytest.raises(TutorNotFoundError) as exc:
        sessions.create_session(source_id="missing-source")
    assert exc.value.entity_type == "SourceDocument"


def test_missing_item_returns_not_found(store: TutorSqliteStore, sessions):
    items = _vocab_pool(store)
    with pytest.raises(TutorNotFoundError) as exc:
        sessions.create_session(item_ids=[items[0].id, "missing-item"])
    assert exc.value.entity_type == "LearningItem"
    assert exc.value.entity_id == "missing-item"


def test_source_id_and_item_ids_together_raise(store: TutorSqliteStore, sessions):
    source = store.source_documents.create(
        SourceDocument(title="A", content="Le livre.")
    )
    with pytest.raises(InvalidPracticeFilterError):
        sessions.create_session(source_id=source.id, item_ids=["x"])


def test_source_id_session_uses_items_from_that_source(
    store: TutorSqliteStore, sessions
):
    content = "Le livre est sur la table."
    source = store.source_documents.create(
        SourceDocument(title="A", content=content, created_at=CREATED)
    )
    other = store.source_documents.create(
        SourceDocument(title="B", content="Le chat.", created_at=CREATED)
    )
    start = content.index("livre")
    store.learning_items.create(
        LearningItem(
            item_type="vocabulary",
            canonical_form="livre",
            meaning_ja="本",
            source_refs=[
                SourceRef(
                    source_document_id=source.id,
                    evidence_span=EvidenceSpan(start=start, end=start + 5),
                )
            ],
        )
    )
    store.learning_items.create(
        LearningItem(
            item_type="vocabulary",
            canonical_form="chat",
            meaning_ja="猫",
            source_refs=[SourceRef(source_document_id=other.id)],
        )
    )
    store.learning_items.create(
        LearningItem(
            item_type="vocabulary",
            canonical_form="maison",
            meaning_ja="家",
        )
    )
    session = sessions.create_session(
        source_id=source.id, question_count=10, seed="fixed"
    )
    item_ids = {row.spec.learning_item_id for row in session.exercises}
    items = {item.id: item for item in store.learning_items.list()}
    assert all(items[item_id].canonical_form == "livre" for item_id in item_ids)
