"""LearningStateService（Issue #110 / #161）のユースケーステスト。"""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.domain.tutor import LearningEvent, LearningItem, apply_review_event
from app.persistence.models import LearnerStateRow
from app.repositories.exceptions import DuplicateEntityError
from app.repositories.sqlite import TutorSqliteStore
from app.services.learning_state_service import LearningStateService


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


EVENT_SEQUENCE = (
    "correct",
    "correct",
    "incorrect",
    "correct",
    "incorrect",
    "incorrect",
    "correct",
)


@pytest.fixture
def store() -> TutorSqliteStore:
    return TutorSqliteStore.in_memory()


@pytest.fixture
def service(store: TutorSqliteStore) -> LearningStateService:
    return LearningStateService(
        learning_items=store.learning_items,
        learning_events=store.learning_events,
        learner_states=store.learner_states,
        progress=store.learning_progress,
    )


def test_record_event_creates_learner_state_from_first_event(
    store: TutorSqliteStore, service: LearningStateService
):
    item = _item()
    store.learning_items.create(item)
    occurred_at = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
    event = _event(item.id, occurred_at=occurred_at, result="correct")

    state = service.record_event(event)

    assert state.attempt_count == 1
    assert state.correct_count == 1
    assert state.incorrect_count == 0
    assert state.consecutive_correct == 1
    assert state.last_reviewed_at == occurred_at
    assert state.mastery_score == 1.0
    assert store.learner_states.get(item.id) == state
    assert store.learning_events.list_by_item(item.id) == [event]


def test_record_event_updates_counters_for_correct_and_incorrect(
    store: TutorSqliteStore, service: LearningStateService
):
    item = _item()
    store.learning_items.create(item)

    first = service.record_event(_event(item.id, result="correct"))
    assert first.attempt_count == 1
    assert first.correct_count == 1
    assert first.incorrect_count == 0
    assert first.consecutive_correct == 1
    assert first.mastery_score == 1.0

    second = service.record_event(_event(item.id, result="incorrect"))
    assert second.attempt_count == 2
    assert second.correct_count == 1
    assert second.incorrect_count == 1
    assert second.consecutive_correct == 0
    assert second.mastery_score == pytest.approx(0.5)


def test_consecutive_correct_increments_and_resets(
    store: TutorSqliteStore, service: LearningStateService
):
    item = _item()
    store.learning_items.create(item)

    service.record_event(_event(item.id, result="correct"))
    service.record_event(_event(item.id, result="correct"))
    two = store.learner_states.get(item.id)
    assert two is not None
    assert two.consecutive_correct == 2

    service.record_event(_event(item.id, result="incorrect"))
    reset = store.learner_states.get(item.id)
    assert reset is not None
    assert reset.consecutive_correct == 0

    service.record_event(_event(item.id, result="correct"))
    resumed = store.learner_states.get(item.id)
    assert resumed is not None
    assert resumed.consecutive_correct == 1


def test_last_reviewed_at_is_the_latest_event_time(
    store: TutorSqliteStore, service: LearningStateService
):
    item = _item()
    store.learning_items.create(item)
    t0 = datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
    t1 = datetime(2026, 3, 1, 11, 0, tzinfo=UTC)
    service.record_event(_event(item.id, occurred_at=t0, result="correct"))
    state = service.record_event(_event(item.id, occurred_at=t1, result="incorrect"))
    assert state.last_reviewed_at == t1


def test_mastery_update_is_deterministic_for_the_same_event_sequence(
    store: TutorSqliteStore, service: LearningStateService
):
    item = _item()
    store.learning_items.create(item)
    events = [
        _event(
            item.id,
            result=result,
            occurred_at=datetime(2026, 3, 1, hour, tzinfo=UTC),
            exercise_type="ja_to_fr",
        )
        for hour, result in enumerate(EVENT_SEQUENCE, start=8)
    ]

    for event in events:
        service.record_event(event)

    folded = None
    for event in events:
        folded = apply_review_event(folded, event)
    assert folded is not None

    persisted = store.learner_states.get(item.id)
    assert persisted == folded
    assert persisted is not None
    assert persisted.attempt_count == 7
    assert persisted.correct_count == 4
    assert persisted.incorrect_count == 3
    assert persisted.consecutive_correct == 1
    assert persisted.mastery_score == pytest.approx(4 / 7)


def test_duplicate_event_id_is_rejected_and_does_not_double_apply(
    store: TutorSqliteStore, service: LearningStateService
):
    item = _item()
    store.learning_items.create(item)
    event = _event(item.id, result="correct")

    first = service.record_event(event)
    with pytest.raises(DuplicateEntityError):
        service.record_event(event)

    loaded = store.learner_states.get(item.id)
    assert loaded == first
    assert loaded is not None
    assert loaded.attempt_count == 1
    assert loaded.by_direction["recognition"].attempt_count == 1
    assert len(store.learning_events.list_by_item(item.id)) == 1


def test_exercise_type_is_persisted_on_the_event(
    store: TutorSqliteStore, service: LearningStateService
):
    item = _item()
    store.learning_items.create(item)
    event = _event(item.id, exercise_type="verb_conjugation", result="incorrect")

    service.record_event(event)

    saved = store.learning_events.list_by_item(item.id)
    assert len(saved) == 1
    assert saved[0].exercise_type == "verb_conjugation"
    assert saved[0].result == "incorrect"


def test_record_event_requires_existing_learning_item(
    service: LearningStateService,
):
    with pytest.raises(ValueError, match="LearningItem が存在しない"):
        service.record_event(_event("missing-item"))


def test_state_upsert_failure_rolls_back_event(
    store: TutorSqliteStore,
    service: LearningStateService,
    monkeypatch: pytest.MonkeyPatch,
):
    item = _item()
    store.learning_items.create(item)
    event = _event(item.id)

    original_merge = Session.merge

    def fail_state_merge(self: Session, instance: object, **kwargs: object) -> object:
        if isinstance(instance, LearnerStateRow):
            raise RuntimeError("state write failed")
        return original_merge(self, instance, **kwargs)

    monkeypatch.setattr(Session, "merge", fail_state_merge)

    with pytest.raises(RuntimeError, match="state write failed"):
        service.record_event(event)

    assert store.learning_events.list_by_item(item.id) == []
    assert store.learner_states.get(item.id) is None


def test_recompute_learner_state_rebuilds_from_event_history(
    store: TutorSqliteStore, service: LearningStateService
):
    item = _item()
    store.learning_items.create(item)
    events = [
        _event(item.id, result="correct"),
        _event(item.id, result="correct"),
        _event(item.id, result="incorrect"),
    ]
    for event in events:
        service.record_event(event)

    store.learner_states.upsert(
        apply_review_event(None, _event(item.id, result="correct"))
    )
    stale = store.learner_states.get(item.id)
    assert stale is not None
    assert stale.attempt_count == 1

    rebuilt = service.recompute_learner_state(item.id)
    assert rebuilt is not None
    assert rebuilt.attempt_count == 3
    assert rebuilt.correct_count == 2
    assert rebuilt.incorrect_count == 1
    assert rebuilt.consecutive_correct == 0
    assert rebuilt.mastery_score == pytest.approx(2 / 3)
    assert store.learner_states.get(item.id) == rebuilt
    recognition = rebuilt.by_direction["recognition"]
    assert recognition.attempt_count == 3
    assert recognition.correct_count == 2


def test_record_event_updates_recognition_independently(
    store: TutorSqliteStore, service: LearningStateService
):
    item = _item()
    store.learning_items.create(item)
    state = service.record_event(
        _event(item.id, exercise_type="meaning_recognition", result="correct")
    )
    assert state.by_direction["recognition"].correct_count == 1
    assert "production" not in state.by_direction
    assert state.correct_count == 1


def test_record_event_updates_production_independently(
    store: TutorSqliteStore, service: LearningStateService
):
    item = _item()
    store.learning_items.create(item)
    state = service.record_event(
        _event(item.id, exercise_type="ja_to_fr", result="incorrect")
    )
    assert state.by_direction["production"].incorrect_count == 1
    assert "recognition" not in state.by_direction
    assert state.incorrect_count == 1


def test_record_event_keeps_independent_mastery_per_direction(
    store: TutorSqliteStore, service: LearningStateService
):
    item = _item()
    store.learning_items.create(item)
    service.record_event(
        _event(item.id, exercise_type="meaning_recognition", result="correct")
    )
    state = service.record_event(
        _event(item.id, exercise_type="ja_to_fr", result="incorrect")
    )
    assert state.attempt_count == 2
    assert state.mastery_score == pytest.approx(0.5)
    assert state.by_direction["recognition"].mastery_score == 1.0
    assert state.by_direction["production"].mastery_score == 0.0


def test_recompute_learner_state_rebuilds_by_direction(
    store: TutorSqliteStore, service: LearningStateService
):
    item = _item()
    store.learning_items.create(item)
    events = [
        _event(item.id, exercise_type="meaning_recognition", result="correct"),
        _event(item.id, exercise_type="ja_to_fr", result="incorrect"),
        _event(item.id, exercise_type="cloze", result="correct"),
    ]
    for event in events:
        service.record_event(event)

    current = store.learner_states.get(item.id)
    assert current is not None
    store.learner_states.upsert(current.model_copy(update={"by_direction": {}}))
    stale = store.learner_states.get(item.id)
    assert stale is not None
    assert stale.by_direction == {}

    rebuilt = service.recompute_learner_state(item.id)
    assert rebuilt is not None
    folded = None
    for event in events:
        folded = apply_review_event(folded, event)
    assert rebuilt == folded
    assert rebuilt.by_direction["recognition"].correct_count == 1
    assert rebuilt.by_direction["production"].attempt_count == 2
    assert rebuilt.attempt_count == 3


def test_legacy_event_without_mappable_type_is_not_assigned_a_direction():
    event = LearningEvent.model_construct(
        id="evt-legacy",
        learning_item_id="item-1",
        event_type="review",
        exercise_type="legacy_unknown",
        result="correct",
        occurred_at=datetime(2026, 3, 1, 9, 0, tzinfo=UTC),
        response_time_ms=None,
        metadata={"skill_direction": "production"},
    )
    state = apply_review_event(None, event)
    assert state.attempt_count == 1
    assert state.by_direction == {}


def test_by_direction_survives_db_reopen(tmp_path: Path):
    db_path = tmp_path / "tutor-direction.db"
    url = f"sqlite:///{db_path}"
    store = TutorSqliteStore(url)
    service = LearningStateService(
        learning_items=store.learning_items,
        learning_events=store.learning_events,
        learner_states=store.learner_states,
        progress=store.learning_progress,
    )
    item = _item()
    store.learning_items.create(item)
    service.record_event(
        _event(item.id, exercise_type="meaning_recognition", result="correct")
    )
    service.record_event(_event(item.id, exercise_type="ja_to_fr", result="incorrect"))
    store.engine.dispose()

    reopened = TutorSqliteStore(url)
    loaded = reopened.learner_states.get(item.id)
    assert loaded is not None
    assert loaded.attempt_count == 2
    assert loaded.by_direction["recognition"].correct_count == 1
    assert loaded.by_direction["production"].incorrect_count == 1
    assert loaded.by_direction["recognition"].mastery_score == 1.0
    assert loaded.by_direction["production"].mastery_score == 0.0
    reopened.engine.dispose()


def test_recompute_learner_state_returns_none_when_no_events(
    store: TutorSqliteStore, service: LearningStateService
):
    item = _item()
    store.learning_items.create(item)
    assert service.recompute_learner_state(item.id) is None
    assert store.learner_states.get(item.id) is None
