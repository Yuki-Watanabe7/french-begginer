"""Tutor 基盤の vertical slice 統合テスト（Issue #113）。

synthetic fixture で Source -> Item -> Event -> State -> Schedule ->
due query を1本の学習ループとして通す。LLM は使わない。
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_tutor_service
from app.domain.noun import NOUNS
from app.main import app
from app.persistence.models import ReviewScheduleRow
from app.repositories.sqlite import TutorSqliteStore
from app.services.tutor_service import build_tutor_service

SOURCE_CONTENT = "Je me suis rendu compte qu'il fallait changer de stratégie."
ITEM_FORM = "se rendre compte de"
ITEM_MEANING = "〜に気づく"
NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
JST = timezone(timedelta(hours=9))


@dataclass
class FrozenClock:
    now: datetime

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(NOW)


@pytest.fixture
def store() -> TutorSqliteStore:
    return TutorSqliteStore.in_memory()


@pytest.fixture
def client(store: TutorSqliteStore, clock: FrozenClock) -> Iterator[TestClient]:
    app.dependency_overrides[get_tutor_service] = lambda: build_tutor_service(
        store, clock=clock
    )
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _create_fixture_source(client: TestClient) -> dict:
    res = client.post(
        "/api/tutor/sources",
        json={"title": "手入力ソース", "content": SOURCE_CONTENT},
    )
    assert res.status_code == 201, res.text
    return res.json()


def _create_fixture_item(client: TestClient, source_id: str, **overrides) -> dict:
    payload = {
        "item_type": "expression",
        "canonical_form": ITEM_FORM,
        "meaning_ja": ITEM_MEANING,
        "source_refs": [{"source_document_id": source_id}],
    }
    payload.update(overrides)
    res = client.post("/api/tutor/items", json=payload)
    assert res.status_code == 201, res.text
    return res.json()["item"]


def _review(
    client: TestClient,
    item_id: str,
    *,
    result: str = "correct",
    occurred_at: datetime | None = None,
    event_id: str | None = None,
    exercise_type: str = "fr_to_ja",
) -> dict:
    payload: dict[str, object] = {
        "exercise_type": exercise_type,
        "result": result,
    }
    if occurred_at is not None:
        payload["occurred_at"] = occurred_at.isoformat()
    if event_id is not None:
        payload["id"] = event_id
    res = client.post(f"/api/tutor/items/{item_id}/reviews", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def _due_ids(client: TestClient) -> list[str]:
    res = client.get("/api/tutor/reviews/due")
    assert res.status_code == 200, res.text
    return [row["item"]["id"] for row in res.json()]


def test_vertical_slice_source_to_due_to_rereview(tmp_path: Path):
    """必須 vertical slice: Source -> Item -> review -> due 前後 -> 再review。

    同一ループを file DB で完走したあと再 open し、永続性も確認する。
    """
    db_path = tmp_path / "tutor.db"
    file_store = TutorSqliteStore(f"sqlite:///{db_path}")
    file_clock = FrozenClock(NOW)
    app.dependency_overrides[get_tutor_service] = lambda: build_tutor_service(
        file_store, clock=file_clock
    )
    try:
        with TestClient(app) as http:
            source = _create_fixture_source(http)
            assert source["content"] == SOURCE_CONTENT
            assert source["source_type"] == "manual_text"

            item = _create_fixture_item(http, source["id"])
            item_id = item["id"]
            assert item["canonical_form"] == ITEM_FORM
            assert item["item_type"] == "expression"
            assert item["meaning_ja"] == ITEM_MEANING
            assert item["source_refs"][0]["source_document_id"] == source["id"]

            first = _review(http, item_id, result="correct")
            assert first["event"]["learning_item_id"] == item_id
            assert first["event"]["result"] == "correct"
            assert first["event"]["occurred_at"].startswith("2026-08-23T12:00:00")
            assert first["learner_state"]["attempt_count"] == 1
            assert first["learner_state"]["correct_count"] == 1
            assert first["learner_state"]["consecutive_correct"] == 1
            assert first["learner_state"]["mastery_score"] == 1.0
            assert first["review_schedule"]["interval_days"] == 1.0
            assert first["review_schedule"]["review_count"] == 1
            assert first["review_schedule"]["lapse_count"] == 0

            events = file_store.learning_events.list_by_item(item_id)
            assert len(events) == 1
            assert events[0].result == "correct"
            assert file_store.learner_states.get(item_id) is not None
            schedule = file_store.review_schedules.get(item_id, "recognition")
            assert schedule is not None
            assert schedule.due_at == NOW + timedelta(days=1)

            assert item_id not in _due_ids(http)

            file_clock.now = NOW + timedelta(days=1) - timedelta(seconds=1)
            assert item_id not in _due_ids(http)

            file_clock.now = NOW + timedelta(days=1)
            assert item_id in _due_ids(http)

            second = _review(http, item_id, result="correct")
            assert second["learner_state"]["attempt_count"] == 2
            assert second["learner_state"]["correct_count"] == 2
            assert second["learner_state"]["consecutive_correct"] == 2
            assert second["review_schedule"]["interval_days"] == 3.0
            assert second["review_schedule"]["review_count"] == 2
            assert second["review_schedule"]["due_at"].startswith("2026-08-27T12:00:00")

            history = file_store.learning_events.list_by_item(item_id)
            assert [event.result for event in history] == ["correct", "correct"]
            assert history[0].id != history[1].id

            file_clock.now = NOW + timedelta(days=1)
            assert item_id not in _due_ids(http)
    finally:
        app.dependency_overrides.clear()
        file_store.engine.dispose()

    reopened = TutorSqliteStore(f"sqlite:///{db_path}")
    loaded_item = reopened.learning_items.get(item_id)
    assert loaded_item is not None
    assert loaded_item.canonical_form == ITEM_FORM
    loaded_source = reopened.source_documents.get(source["id"])
    assert loaded_source is not None
    assert loaded_source.content == SOURCE_CONTENT
    loaded_events = reopened.learning_events.list_by_item(item_id)
    assert len(loaded_events) == 2
    loaded_state = reopened.learner_states.get(item_id)
    assert loaded_state is not None
    assert loaded_state.attempt_count == 2
    assert loaded_state.consecutive_correct == 2
    loaded_schedule = reopened.review_schedules.get(item_id, "recognition")
    assert loaded_schedule is not None
    assert loaded_schedule.interval_days == 3.0
    assert loaded_schedule.due_at == NOW + timedelta(days=4)
    reopened.engine.dispose()


def test_incorrect_review_increases_lapse_and_shortens_interval(client: TestClient):
    source = _create_fixture_source(client)
    item_id = _create_fixture_item(client, source["id"])["id"]

    first = _review(client, item_id, result="correct")
    assert first["review_schedule"]["interval_days"] == 1.0
    second = _review(client, item_id, result="correct")
    assert second["review_schedule"]["interval_days"] == 3.0
    assert second["review_schedule"]["lapse_count"] == 0

    lapse = _review(client, item_id, result="incorrect")
    assert lapse["learner_state"]["incorrect_count"] == 1
    assert lapse["learner_state"]["consecutive_correct"] == 0
    assert lapse["learner_state"]["mastery_score"] == pytest.approx(2 / 3)
    assert lapse["review_schedule"]["interval_days"] == 1.0
    assert lapse["review_schedule"]["lapse_count"] == 1
    assert lapse["review_schedule"]["review_count"] == 3


def test_multiple_reviews_preserve_event_history(
    client: TestClient, store: TutorSqliteStore
):
    source = _create_fixture_source(client)
    item_id = _create_fixture_item(client, source["id"])["id"]
    results = ("correct", "incorrect", "correct", "correct")
    for i, result in enumerate(results):
        _review(client, item_id, result=result, event_id=f"evt-{i}")

    events = store.learning_events.list_by_item(item_id)
    assert [event.id for event in events] == [f"evt-{i}" for i in range(4)]
    assert [event.result for event in events] == list(results)
    state = store.learner_states.get(item_id)
    assert state is not None
    assert state.attempt_count == 4
    assert state.correct_count == 3
    assert state.incorrect_count == 1


def test_review_missing_item_returns_404(client: TestClient):
    res = client.post(
        "/api/tutor/items/missing-item/reviews",
        json={"exercise_type": "fr_to_ja", "result": "correct"},
    )
    assert res.status_code == 404
    assert "LearningItem" in res.json()["detail"]


def test_duplicate_event_is_rejected_without_double_apply(
    client: TestClient, store: TutorSqliteStore
):
    source = _create_fixture_source(client)
    item_id = _create_fixture_item(client, source["id"])["id"]
    payload = {
        "id": "evt-dup",
        "exercise_type": "fr_to_ja",
        "result": "correct",
    }
    first = client.post(f"/api/tutor/items/{item_id}/reviews", json=payload)
    assert first.status_code == 201, first.text
    second = client.post(f"/api/tutor/items/{item_id}/reviews", json=payload)
    assert second.status_code == 409

    events = store.learning_events.list_by_item(item_id)
    assert len(events) == 1
    state = store.learner_states.get(item_id)
    assert state is not None
    assert state.attempt_count == 1
    assert state.correct_count == 1


def test_due_query_uses_timezone_boundary(client: TestClient, clock: FrozenClock):
    source = _create_fixture_source(client)
    item_id = _create_fixture_item(client, source["id"])["id"]
    occurred_at = datetime(2026, 8, 23, 21, 0, tzinfo=JST)
    review = _review(client, item_id, occurred_at=occurred_at)
    assert review["event"]["occurred_at"].startswith("2026-08-23T12:00:00")
    assert review["review_schedule"]["due_at"].startswith("2026-08-24T12:00:00")

    clock.now = datetime(2026, 8, 24, 20, 59, 59, tzinfo=JST)
    assert item_id not in _due_ids(client)

    clock.now = datetime(2026, 8, 24, 21, 0, tzinfo=JST)
    assert item_id in _due_ids(client)


def test_future_due_is_excluded_until_due_at(client: TestClient, clock: FrozenClock):
    source = _create_fixture_source(client)
    item_id = _create_fixture_item(client, source["id"])["id"]
    _review(client, item_id, result="correct")

    clock.now = NOW + timedelta(days=1) - timedelta(microseconds=1)
    assert item_id not in _due_ids(client)
    clock.now = NOW + timedelta(days=1)
    assert item_id in _due_ids(client)


def test_suspended_and_mastered_items_are_not_due(
    client: TestClient, clock: FrozenClock
):
    source = _create_fixture_source(client)
    active_id = _create_fixture_item(client, source["id"])["id"]
    suspended_id = _create_fixture_item(
        client,
        source["id"],
        canonical_form="mettre en œuvre",
        meaning_ja="実行する",
        status="suspended",
    )["id"]
    mastered_id = _create_fixture_item(
        client,
        source["id"],
        canonical_form="il s'agit de",
        meaning_ja="〜が問題である",
        status="mastered",
    )["id"]

    for item_id in (active_id, suspended_id, mastered_id):
        _review(client, item_id, result="correct")

    clock.now = NOW + timedelta(days=1)
    due_ids = _due_ids(client)
    assert due_ids == [active_id]
    assert suspended_id not in due_ids
    assert mastered_id not in due_ids


def test_schedule_write_failure_rolls_back_event_and_state(
    store: TutorSqliteStore, monkeypatch: pytest.MonkeyPatch
):
    """event / state / schedule は同一TX。schedule 失敗時は3者とも残らない。"""
    service = build_tutor_service(store, clock=lambda: NOW)
    item = service.create_item(
        item_type="expression",
        canonical_form=ITEM_FORM,
        meaning_ja=ITEM_MEANING,
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


def test_existing_quiz_and_tts_contracts_are_unchanged(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    question = client.get("/api/questions/next")
    assert question.status_code == 200
    body = question.json()
    assert {"verb", "tense", "pronoun"} <= set(body)

    check = client.post(
        "/api/answers/check",
        json={
            "verb": "être",
            "tense": "présent",
            "pronoun": "je",
            "answer": "suis",
        },
    )
    assert check.status_code == 200
    assert check.json()["correct"] is True
    assert check.json()["expected"] == "suis"

    noun = client.get("/api/nouns/next")
    assert noun.status_code == 200
    assert noun.json()["noun"] in NOUNS

    noun_check = client.post(
        "/api/nouns/check",
        json={"noun": "livre", "answer": "masculine"},
    )
    assert noun_check.status_code == 200
    assert noun_check.json()["correct"] is True

    article = client.get("/api/nouns/article/next")
    assert article.status_code == 200
    assert "noun" in article.json()

    article_check = client.post(
        "/api/nouns/article/check",
        json={"noun": "livre", "answer": "un livre"},
    )
    assert article_check.status_code == 200
    assert article_check.json()["correct"] is True

    tts = client.get("/api/tts/speak?text=bonjour")
    assert tts.status_code == 503
    assert "OPENAI_API_KEY" in tts.json()["detail"]
