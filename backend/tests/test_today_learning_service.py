"""TodayLearningService（Issue #178）のユースケーステスト。"""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.tutor import LearningItem, SourceDocument, SourceRef
from app.repositories.sqlite import TutorSqliteStore
from app.services.exceptions import InvalidTodayLearningError
from app.services.exercise_service import build_exercise_service
from app.services.today_learning_service import build_today_learning_service
from app.services.tutor_service import build_tutor_service

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


@pytest.fixture
def store() -> TutorSqliteStore:
    return TutorSqliteStore.in_memory()


@pytest.fixture
def tutor(store: TutorSqliteStore):
    return build_tutor_service(store, clock=lambda: NOW)


@pytest.fixture
def today(store: TutorSqliteStore):
    return build_today_learning_service(store, clock=lambda: NOW)


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


def _make_due(tutor, item: LearningItem, *, direction: str = "recognition") -> None:
    exercise_type = "meaning_recognition" if direction == "recognition" else "ja_to_fr"
    tutor.record_review(
        item.id,
        exercise_type=exercise_type,
        result="incorrect",
        occurred_at=NOW - timedelta(days=2),
    )


def test_plan_returns_review_and_new_counts(tutor, today):
    pool = _vocab_pool(tutor)
    _make_due(tutor, pool[0], direction="recognition")
    plan = today.get_plan(question_count=10, max_new_count=3)
    assert plan.review_count == 1
    assert plan.new_count == 3
    assert plan.total_count == 4
    assert plan.deferred_due_count == 0
    assert plan.entries[0].activity_kind == "review"
    assert plan.entries[0].skill_direction == "recognition"
    assert plan.entries[0].explanation
    assert "rank_score" not in plan.entries[0].model_dump()


def test_due_priority_and_new_cap(tutor, today):
    pool = _vocab_pool(tutor)
    extra = tutor.create_item(
        item_type="vocabulary", canonical_form="eau", meaning_ja="水"
    )
    for item in pool:
        _make_due(tutor, item, direction="recognition")
        _make_due(tutor, item, direction="production")
    plan = today.get_plan(question_count=5, max_new_count=2)
    assert plan.review_count == 5
    assert plan.new_count == 0
    assert extra.id not in {row.learning_item_id for row in plan.entries}


def test_deferred_due_count(tutor, today):
    pool = _vocab_pool(tutor)
    for item in pool:
        _make_due(tutor, item, direction="recognition")
    plan = today.get_plan(question_count=2, max_new_count=3)
    assert plan.review_count == 2
    assert plan.deferred_due_count == 2


def test_empty_plan(today):
    plan = today.get_plan()
    assert plan.entries == ()
    assert plan.total_count == 0
    assert plan.explanation_summary


def test_session_reuses_exercise_and_keeps_direction(tutor, today, store):
    pool = _vocab_pool(tutor)
    _make_due(tutor, pool[0], direction="production")
    before_events = [
        event
        for item in store.learning_items.list()
        for event in store.learning_events.list_by_item(item.id)
    ]
    session = today.create_session(question_count=10, max_new_count=3, seed="fixed")
    production = next(
        row
        for row in session.exercises
        if row.spec.learning_item_id == pool[0].id
        and row.spec.skill_direction == "production"
    )
    assert production.spec.skill_direction == "production"
    after_events = [
        event
        for item in store.learning_items.list()
        for event in store.learning_events.list_by_item(item.id)
    ]
    assert after_events == before_events
    public = session.to_public_exercises()
    assert all("correct_answer" not in row.model_dump() for row in public)


def test_new_answer_creates_schedule(tutor, today, store):
    _vocab_pool(tutor)
    session = today.create_session(question_count=5, max_new_count=3, seed="fixed")
    new_entry = next(
        row for row in session.entries if row.activity_kind == "new_practice"
    )
    exercise = next(
        row
        for row in session.exercises
        if row.spec.learning_item_id == new_entry.learning_item_id
    )
    assert (
        store.review_schedules.get(
            new_entry.learning_item_id, new_entry.skill_direction
        )
        is None
    )
    exercises = build_exercise_service(store, tutor)
    record = exercises.submit_answer(
        new_entry.learning_item_id,
        exercise.spec.exercise_type,
        exercise.answer_key.expected_answers[0],
        occurred_at=NOW,
    )
    assert record.review_schedule.skill_direction == new_entry.skill_direction
    assert (
        store.review_schedules.get(
            new_entry.learning_item_id, new_entry.skill_direction
        )
        is not None
    )
    other = (
        "production" if new_entry.skill_direction == "recognition" else "recognition"
    )
    assert store.review_schedules.get(new_entry.learning_item_id, other) is None


def test_inactive_item_is_not_planned(tutor, today):
    _vocab_pool(tutor)
    tutor.create_item(
        item_type="vocabulary",
        canonical_form="pont",
        meaning_ja="橋",
        status="suspended",
    )
    plan = today.get_plan(question_count=10, max_new_count=5)
    assert all(row.canonical_form != "pont" for row in plan.entries)


def test_session_refresh_drops_answered_due(tutor, today, store):
    pool = _vocab_pool(tutor)
    _make_due(tutor, pool[0], direction="recognition")
    first = today.create_session(question_count=10, max_new_count=0, seed="fixed")
    review = next(row for row in first.entries if row.activity_kind == "review")
    exercise = next(
        row
        for row in first.exercises
        if row.spec.learning_item_id == review.learning_item_id
    )
    exercises = build_exercise_service(store, tutor)
    exercises.submit_answer(
        review.learning_item_id,
        exercise.spec.exercise_type,
        exercise.answer_key.expected_answers[0],
        occurred_at=NOW,
    )
    second = today.create_session(question_count=10, max_new_count=0, seed="fixed")
    assert all(
        not (
            row.learning_item_id == review.learning_item_id
            and row.activity_kind == "review"
        )
        for row in second.entries
    )


def test_source_titles_on_plan(tutor, today, store):
    source = store.source_documents.create(
        SourceDocument(title="Café", content="Le livre est sur la table.")
    )
    tutor.create_item(
        item_type="vocabulary",
        canonical_form="livre",
        meaning_ja="本",
        source_refs=[SourceRef(source_document_id=source.id)],
    )
    tutor.create_item(item_type="vocabulary", canonical_form="maison", meaning_ja="家")
    tutor.create_item(item_type="vocabulary", canonical_form="chat", meaning_ja="猫")
    tutor.create_item(item_type="vocabulary", canonical_form="chien", meaning_ja="犬")
    plan = today.get_plan(question_count=5, max_new_count=3)
    titled = [row for row in plan.entries if row.canonical_form == "livre"]
    assert titled
    assert "Café" in titled[0].source_titles


def test_invalid_question_count_raises(today):
    with pytest.raises(InvalidTodayLearningError):
        today.get_plan(question_count=0)
    with pytest.raises(InvalidTodayLearningError):
        today.create_session(question_count=21)
    with pytest.raises(InvalidTodayLearningError):
        today.get_plan(max_new_count=-1)
