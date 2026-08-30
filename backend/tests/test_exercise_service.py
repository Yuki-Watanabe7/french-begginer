"""ExerciseService（Issue #149）のユースケーステスト。"""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.exercise import EXERCISE_VERSION
from app.domain.exercise_generation import generate_exercise
from app.domain.tutor import (
    EvidenceSpan,
    LearningItem,
    SourceDocument,
    SourceRef,
)
from app.repositories.sqlite import TutorSqliteStore
from app.services.exceptions import (
    TutorConflictError,
    TutorNotFoundError,
    TutorUnsupportedExerciseError,
)
from app.services.exercise_service import build_exercise_service
from app.services.tutor_service import build_tutor_service

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)


@pytest.fixture
def store() -> TutorSqliteStore:
    return TutorSqliteStore.in_memory()


@pytest.fixture
def exercises(store: TutorSqliteStore):
    tutor = build_tutor_service(store, clock=lambda: NOW)
    return build_exercise_service(store, tutor)


def _vocab_pool(store: TutorSqliteStore) -> list[LearningItem]:
    meanings = (("livre", "本"), ("maison", "家"), ("chat", "猫"), ("chien", "犬"))
    items: list[LearningItem] = []
    for form, meaning in meanings:
        items.append(
            store.learning_items.create(
                LearningItem(
                    item_type="vocabulary",
                    canonical_form=form,
                    meaning_ja=meaning,
                )
            )
        )
    return items


def test_correct_and_incorrect_each_append_one_event_and_update_state(
    store: TutorSqliteStore, exercises
):
    items = _vocab_pool(store)
    target = items[0]

    later = NOW + timedelta(seconds=1)
    correct = exercises.submit_answer(target.id, "ja_to_fr", "livre", occurred_at=NOW)
    assert correct.evaluation.correct is True
    assert correct.learner_state.attempt_count == 1
    assert correct.learner_state.correct_count == 1
    assert correct.review_schedule.review_count == 1
    assert correct.event.metadata["exercise_version"] == EXERCISE_VERSION
    assert correct.event.metadata["skill_direction"] == "production"
    assert correct.event.metadata["generation_method"] == "deterministic"
    assert correct.event.exercise_type == "ja_to_fr"

    wrong = exercises.submit_answer(target.id, "ja_to_fr", "maison", occurred_at=later)
    assert wrong.evaluation.correct is False
    assert wrong.learner_state.attempt_count == 2
    assert wrong.learner_state.correct_count == 1
    assert wrong.learner_state.incorrect_count == 1
    assert wrong.review_schedule.review_count == 2
    assert wrong.review_schedule.lapse_count == 1

    events = store.learning_events.list_by_item(target.id)
    assert len(events) == 2
    assert [event.result for event in events] == ["correct", "incorrect"]


def test_duplicate_event_id_does_not_double_apply(store: TutorSqliteStore, exercises):
    items = _vocab_pool(store)
    target = items[0]
    first = exercises.submit_answer(target.id, "ja_to_fr", "livre", event_id="evt-dup")
    assert first.learner_state.attempt_count == 1

    with pytest.raises(TutorConflictError, match="LearningEvent"):
        exercises.submit_answer(target.id, "ja_to_fr", "livre", event_id="evt-dup")

    assert store.learner_states.get(target.id).attempt_count == 1
    assert len(store.learning_events.list_by_item(target.id)) == 1


def test_missing_item_raises_not_found(exercises):
    with pytest.raises(TutorNotFoundError, match="LearningItem"):
        exercises.get_exercise("missing-item", "ja_to_fr")
    with pytest.raises(TutorNotFoundError, match="LearningItem"):
        exercises.submit_answer("missing-item", "ja_to_fr", "livre")


def test_inactive_item_is_unsupported(store: TutorSqliteStore, exercises):
    item = store.learning_items.create(
        LearningItem(
            item_type="vocabulary",
            canonical_form="livre",
            meaning_ja="本",
            status="suspended",
        )
    )
    with pytest.raises(TutorUnsupportedExerciseError) as exc:
        exercises.get_exercise(item.id, "ja_to_fr")
    assert exc.value.skip_reason == "inactive_item"
    assert store.learning_events.list_by_item(item.id) == []


def test_cloze_event_keeps_source_document_id(store: TutorSqliteStore, exercises):
    content = "Je me suis rendu compte qu'il fallait changer de stratégie."
    fragment = "rendu compte"
    start = content.index(fragment)
    source = store.source_documents.create(
        SourceDocument(title="fixture", content=content)
    )
    item = store.learning_items.create(
        LearningItem(
            item_type="expression",
            canonical_form="se rendre compte de",
            meaning_ja="〜に気づく",
            explanation_ja="気づく、という表現",
            source_refs=[
                SourceRef(
                    source_document_id=source.id,
                    evidence_span=EvidenceSpan(start=start, end=start + len(fragment)),
                )
            ],
        )
    )
    record = exercises.submit_answer(item.id, "cloze", fragment)
    assert record.evaluation.correct is True
    assert record.event.metadata["generation_method"] == "source_cloze"
    assert record.event.metadata["source_document_id"] == source.id
    assert record.explanation_ja == "気づく、という表現"
    assert record.source_context is not None
    assert "____" in record.source_context


def test_verb_conjugation_records_adapter_method(store: TutorSqliteStore, exercises):
    item = store.learning_items.create(
        LearningItem(
            item_type="conjugation",
            canonical_form="parler",
            meaning_ja="話す",
            metadata={"lemma": "parler", "tense": "présent"},
        )
    )
    generated = generate_exercise(item, "verb_conjugation", seed="tutor-exercise")
    assert generated.exercise is not None
    expected = generated.exercise.answer_key.expected_answers[0]
    record = exercises.submit_answer(item.id, "verb_conjugation", expected)
    assert record.evaluation.correct is True
    assert record.event.metadata["generation_method"] == "conjugation_adapter"
    assert record.event.exercise_type == "verb_conjugation"
