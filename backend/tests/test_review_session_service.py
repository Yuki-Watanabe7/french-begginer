"""ReviewSessionService（Issue #164）のユースケーステスト。"""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.tutor import LearningItem
from app.repositories.sqlite import TutorSqliteStore
from app.services.exceptions import InvalidReviewSessionError
from app.services.review_session_service import build_review_session_service
from app.services.tutor_service import build_tutor_service

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


@pytest.fixture
def store() -> TutorSqliteStore:
    return TutorSqliteStore.in_memory()


@pytest.fixture
def tutor(store: TutorSqliteStore):
    return build_tutor_service(store, clock=lambda: NOW)


@pytest.fixture
def sessions(store: TutorSqliteStore, tutor):
    return build_review_session_service(store, tutor)


def _vocab_pool(tutor) -> list[LearningItem]:
    specs = (("livre", "本"), ("maison", "家"), ("chat", "猫"), ("chien", "犬"))
    return [
        tutor.create_item(
            item_type="vocabulary",
            canonical_form=form,
            meaning_ja=meaning,
        )
        for form, meaning in specs
    ]


def _make_due(tutor, item: LearningItem, *, direction: str = "production") -> None:
    exercise_type = "ja_to_fr" if direction == "production" else "meaning_recognition"
    tutor.record_review(
        item.id,
        exercise_type=exercise_type,
        result="correct",
        occurred_at=NOW - timedelta(days=1),
    )


def test_create_session_from_due_entries_only(store: TutorSqliteStore, tutor, sessions):
    pool = _vocab_pool(tutor)
    _make_due(tutor, pool[0], direction="production")
    tutor.record_review(
        pool[1].id,
        exercise_type="ja_to_fr",
        result="correct",
        occurred_at=NOW,
    )
    before_events = [
        event
        for item in store.learning_items.list()
        for event in store.learning_events.list_by_item(item.id)
    ]
    session = sessions.create_session(question_count=5, seed="fixed")
    item_ids = {row.spec.learning_item_id for row in session.exercises}
    assert item_ids == {pool[0].id}
    assert all(row.spec.skill_direction == "production" for row in session.exercises)
    after_events = [
        event
        for item in store.learning_items.list()
        for event in store.learning_events.list_by_item(item.id)
    ]
    assert after_events == before_events
    due_after = tutor.list_review_queue(NOW)
    assert [row.item.id for row in due_after.entries] == [pool[0].id]


def test_skip_does_not_advance_schedule(store: TutorSqliteStore, tutor, sessions):
    grammar = tutor.create_item(
        item_type="grammar",
        canonical_form="il faut",
        meaning_ja="〜しなければならない",
    )
    tutor.record_review(
        grammar.id,
        exercise_type="cloze",
        result="incorrect",
        occurred_at=NOW - timedelta(days=1),
    )
    before = store.review_schedules.list_for_item(grammar.id)
    session = sessions.create_session(question_count=5, seed="fixed")
    skipped = {row.learning_item_id: row for row in session.skipped_entries}
    assert skipped[grammar.id].skip_reason == "missing_source_evidence"
    assert session.generated_count == 0
    after = store.review_schedules.list_for_item(grammar.id)
    assert after == before
    assert store.learning_events.list_by_item(grammar.id)
    # skip では新しい event を足さない
    assert len(store.learning_events.list_by_item(grammar.id)) == 1


def test_answering_updates_only_matching_direction(
    store: TutorSqliteStore, tutor, sessions
):
    pool = _vocab_pool(tutor)
    item = pool[0]
    tutor.record_review(
        item.id,
        exercise_type="meaning_recognition",
        result="correct",
        occurred_at=NOW - timedelta(days=2),
    )
    tutor.record_review(
        item.id,
        exercise_type="ja_to_fr",
        result="incorrect",
        occurred_at=NOW - timedelta(days=1),
    )
    session = sessions.create_session(question_count=10, seed="fixed")
    production = next(
        row for row in session.exercises if row.spec.skill_direction == "production"
    )
    recognition_before = store.review_schedules.get(item.id, "recognition")
    production_before = store.review_schedules.get(item.id, "production")
    assert recognition_before is not None
    assert production_before is not None

    from app.services.exercise_service import build_exercise_service

    exercises = build_exercise_service(store, tutor)
    record = exercises.submit_answer(
        item.id,
        production.spec.exercise_type,
        production.answer_key.expected_answers[0],
        occurred_at=NOW,
    )
    assert record.review_schedule.skill_direction == "production"
    recognition_after = store.review_schedules.get(item.id, "recognition")
    production_after = store.review_schedules.get(item.id, "production")
    assert recognition_after == recognition_before
    assert production_after is not None
    assert production_after.due_at != production_before.due_at
    assert production_after.due_at > NOW


def test_empty_due_queue_returns_empty_session(sessions):
    session = sessions.create_session(question_count=5)
    assert session.exercises == ()
    assert session.skipped_entries == ()
    assert session.generated_count == 0


def test_invalid_question_count_raises(sessions):
    with pytest.raises(InvalidReviewSessionError):
        sessions.create_session(question_count=0)
    with pytest.raises(InvalidReviewSessionError):
        sessions.create_session(question_count=21)
