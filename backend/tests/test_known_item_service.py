"""explicit known の保存と、Today / Review への接続（Issue #201）。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domain.known_item_policy import decide_auto_skip
from app.domain.tutor import AnswerOutcome, ExerciseType, LearningItem
from app.persistence.datetime_codec import dump_utc
from app.persistence.db import create_db_engine
from app.persistence.models import Base, LearningItemRow
from app.persistence.schema import (
    CURRENT_SCHEMA_VERSION,
    get_schema_version,
    init_schema,
)
from app.repositories.sqlite import TutorSqliteStore
from app.services.exceptions import TutorNotFoundError
from app.services.review_session_service import build_review_session_service
from app.services.today_learning_service import build_today_learning_service
from app.services.tutor_service import TutorService, build_tutor_service

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)


@pytest.fixture
def store() -> TutorSqliteStore:
    return TutorSqliteStore.in_memory()


@pytest.fixture
def tutor(store: TutorSqliteStore) -> TutorService:
    return build_tutor_service(store, clock=lambda: NOW)


@pytest.fixture
def today(store: TutorSqliteStore):
    return build_today_learning_service(store, clock=lambda: NOW)


def test_explicit_known_excludes_new_plan_and_undo_restores(
    tutor: TutorService, today
) -> None:
    known = _item(tutor, "livre", "本")
    other = _item(tutor, "maison", "家")
    tutor.mark_known(known.id)

    hidden = today.get_plan(question_count=5, max_new_count=2)
    assert _new_ids(hidden) == {other.id}
    assert hidden.new_count == 1

    tutor.clear_known(known.id)
    restored = today.get_plan(question_count=5, max_new_count=2)
    assert _new_ids(restored) == {known.id, other.id}
    assert restored.new_count == 2


def test_mark_known_keeps_status_history_and_schedule(
    store: TutorSqliteStore, tutor: TutorService
) -> None:
    item = _item(tutor, "chat", "猫")
    _review(tutor, item.id, "meaning_recognition", "incorrect", days=3)
    before = tutor.get_item(item.id)
    learning_events = len(store.learning_events.list_by_item(item.id))

    record = tutor.mark_known(item.id)

    after = tutor.get_item(item.id)
    assert record.explicit_known is True
    assert record.updated_at == NOW
    assert after.item.status == "active"
    assert after.item == before.item
    assert after.learner_state == before.learner_state
    assert after.review_schedules == before.review_schedules
    assert len(store.learning_events.list_by_item(item.id)) == learning_events
    assert [event.action for event in store.known_items.list_events(item.id)] == [
        "mark_known"
    ]


def test_mark_known_does_not_change_mastered_status(tutor: TutorService) -> None:
    item = tutor.create_item(
        item_type="vocabulary",
        canonical_form="chien",
        meaning_ja="犬",
        status="mastered",
    )
    tutor.mark_known(item.id)
    assert tutor.get_item(item.id).item.status == "mastered"


def test_repeated_mark_does_not_append_another_event(
    store: TutorSqliteStore, tutor: TutorService
) -> None:
    item = _item(tutor, "eau", "水")
    first = tutor.mark_known(item.id)
    second = tutor.mark_known(item.id)
    assert second == first
    assert len(store.known_items.list_events(item.id)) == 1


def test_missing_item_is_not_found(tutor: TutorService) -> None:
    with pytest.raises(TutorNotFoundError):
        tutor.mark_known("missing")


def test_known_due_item_stays_in_review_and_leaves_new_plan(
    store: TutorSqliteStore, tutor: TutorService, today
) -> None:
    due = _item(tutor, "pain", "パン")
    fresh = _item(tutor, "vin", "ワイン")
    _review(tutor, due.id, "meaning_recognition", "incorrect", days=3)
    before = tutor.get_item(due.id)
    tutor.mark_known(due.id)

    plan = today.get_plan(question_count=5, max_new_count=2)
    assert any(
        entry.learning_item_id == due.id and entry.activity_kind == "review"
        for entry in plan.entries
    )
    assert due.id not in _new_ids(plan)
    assert fresh.id in _new_ids(plan)

    queue = tutor.list_review_queue()
    assert any(entry.item.id == due.id for entry in queue.entries)
    session = build_review_session_service(store, tutor).create_session(
        question_count=5
    )
    assert any(
        exercise.learning_item_id == due.id
        for exercise in session.to_public_exercises()
    )
    assert tutor.get_item(due.id).item.status == "active"
    assert tutor.get_item(due.id).review_schedules == before.review_schedules


def test_one_correct_does_not_auto_skip_the_other_direction(
    store: TutorSqliteStore, tutor: TutorService, today
) -> None:
    item = _item(tutor, "livre", "本")
    _review(tutor, item.id, "meaning_recognition", "correct", hours=12)
    decision = decide_auto_skip(
        skill_direction="recognition",
        events=store.learning_events.list_by_item_and_direction(item.id, "recognition"),
        now=NOW,
    )
    assert decision.skip_new is False
    new_entries = [
        entry
        for entry in today.get_plan(question_count=5, max_new_count=2).entries
        if entry.learning_item_id == item.id and entry.activity_kind == "new_practice"
    ]
    assert [entry.skill_direction for entry in new_entries] == ["production"]


def test_sufficient_history_does_not_consume_a_new_slot(
    store: TutorSqliteStore, tutor: TutorService, today
) -> None:
    practiced = _item(tutor, "livre", "本")
    fresh = _item(tutor, "maison", "家")
    for days in (10, 6, 2):
        _review(tutor, practiced.id, "meaning_recognition", "correct", days=days)
        _review(tutor, practiced.id, "ja_to_fr", "correct", days=days)
    for direction in ("recognition", "production"):
        decision = decide_auto_skip(
            skill_direction=direction,
            events=store.learning_events.list_by_item_and_direction(
                practiced.id, direction
            ),
            now=NOW,
        )
        assert decision.skip_new is True
    plan = today.get_plan(question_count=5, max_new_count=1)
    assert _new_ids(plan) == {fresh.id}
    assert practiced.id not in {entry.learning_item_id for entry in plan.entries}


def test_recent_incorrect_does_not_auto_skip(
    store: TutorSqliteStore, tutor: TutorService
) -> None:
    item = _item(tutor, "livre", "本")
    for days in (12, 8, 4, 2):
        _review(tutor, item.id, "meaning_recognition", "correct", days=days)
    _review(tutor, item.id, "meaning_recognition", "incorrect", hours=12)
    decision = decide_auto_skip(
        skill_direction="recognition",
        events=store.learning_events.list_by_item_and_direction(item.id, "recognition"),
        now=NOW,
    )
    assert decision.skip_new is False
    assert decision.reason_code == "RECENT_INCORRECT"


def test_high_recognition_does_not_skip_low_production(
    store: TutorSqliteStore, tutor: TutorService, today
) -> None:
    item = _item(tutor, "livre", "本")
    for days in (10, 6, 2):
        _review(tutor, item.id, "meaning_recognition", "correct", days=days)
    recognition = decide_auto_skip(
        skill_direction="recognition",
        events=store.learning_events.list_by_item_and_direction(item.id, "recognition"),
        now=NOW,
    )
    production = decide_auto_skip(
        skill_direction="production",
        events=store.learning_events.list_by_item_and_direction(item.id, "production"),
        now=NOW,
    )
    assert recognition.skip_new is True
    assert production.skip_new is False
    new_entries = [
        entry
        for entry in today.get_plan(question_count=5, max_new_count=2).entries
        if entry.learning_item_id == item.id and entry.activity_kind == "new_practice"
    ]
    assert [entry.skill_direction for entry in new_entries] == ["production"]


def test_explicit_known_survives_reopen(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'known.db'}"
    store = TutorSqliteStore(url)
    service = build_tutor_service(store, clock=_stepping_clock())
    item = _item(service, "livre", "本")
    service.mark_known(item.id)
    service.clear_known(item.id)
    service.mark_known(item.id)
    store.engine.dispose()

    reopened = TutorSqliteStore(url)
    record = build_tutor_service(reopened, clock=lambda: NOW).get_known(item.id)
    assert record.explicit_known is True
    assert [event.action for event in reopened.known_items.list_events(item.id)] == [
        "mark_known",
        "clear_known",
        "mark_known",
    ]
    reopened.engine.dispose()


def test_schema_upgrades_from_v4_and_keeps_learning_items(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'v4.db'}"
    engine = create_db_engine(url)
    item = LearningItem(
        item_type="vocabulary",
        canonical_form="livre",
        meaning_ja="本",
    )
    with engine.begin() as conn:
        Base.metadata.create_all(conn)
        conn.execute(text("DROP TABLE IF EXISTS known_item_events"))
        conn.execute(text("DROP TABLE IF EXISTS known_item_overrides"))
        conn.execute(
            text(
                "INSERT INTO schema_migrations (version, applied_at) "
                "VALUES (:version, :applied_at)"
            ),
            {"version": 4, "applied_at": dump_utc(NOW)},
        )
    with Session(engine) as session:
        session.add(LearningItemRow.from_domain(item))
        session.commit()
    init_schema(engine)
    assert get_schema_version(engine) == CURRENT_SCHEMA_VERSION
    with engine.connect() as conn:
        assert conn.dialect.has_table(conn, "known_item_overrides")
        assert conn.dialect.has_table(conn, "known_item_events")
    engine.dispose()

    store = TutorSqliteStore(url)
    loaded = store.learning_items.get(item.id)
    assert loaded is not None
    assert loaded.canonical_form == "livre"
    assert loaded.status == "active"
    assert store.known_items.get(item.id) is None
    store.engine.dispose()


def _item(tutor: TutorService, form: str, meaning: str) -> LearningItem:
    return tutor.create_item(
        item_type="vocabulary",
        canonical_form=form,
        meaning_ja=meaning,
    )


def _stepping_clock():
    step = {"n": 0}

    def clock() -> datetime:
        current = NOW + timedelta(seconds=step["n"])
        step["n"] += 1
        return current

    return clock


def _review(
    tutor: TutorService,
    item_id: str,
    exercise_type: ExerciseType,
    result: AnswerOutcome,
    *,
    days: int = 0,
    hours: int = 0,
) -> None:
    tutor.record_review(
        item_id,
        exercise_type=exercise_type,
        result=result,
        occurred_at=NOW - timedelta(days=days, hours=hours),
    )


def _new_ids(plan) -> set[str]:
    return {
        entry.learning_item_id
        for entry in plan.entries
        if entry.activity_kind == "new_practice"
    }
