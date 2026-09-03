"""学習 → 期限到来 → 今日の復習 → 再schedule の vertical slice。

Issue #167 / Phase 4。Phase 3 で蓄積した LearningEvent と direction 別
ReviewSchedule から、due になった項目だけが「今日の復習」へ現れ、
回答後に該当 direction の次回予定へ進むことを HTTP API + SQLite で
一本につなぐ。実時間待ちと実 LLM は使わない。
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import (
    get_learning_item_extractor,
    get_tutor_service,
    get_tutor_store,
)
from app.domain.exercise import tokenize_canonical_form
from app.domain.exercise_generation import DEFAULT_GENERATION_SEED, generate_exercise
from app.domain.noun import NOUNS
from app.domain.tutor import SourceDocument
from app.main import app
from app.persistence.models import ReviewScheduleRow
from app.repositories.sqlite import TutorSqliteStore
from app.services.extraction_prompt import EXTRACTION_VERSION
from app.services.extraction_schema import ExtractedCandidate, ExtractedEvidenceSpan
from app.services.extractors import ExtractorResult
from app.services.review_schedule_rebuilder import build_review_schedule_rebuilder
from app.services.tutor_service import build_tutor_service

SOURCE_TITLE = "Article test"
SOURCE_CONTENT = "Je me suis rendu compte qu'il fallait changer de stratégie."
SOURCE_NOTE = "se rendre compte が気になった"
NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
JST = timezone(timedelta(hours=9))
PRODUCTION_LAG = timedelta(hours=6)

_LEAKED_ANSWER_KEYS = {
    "expected",
    "expected_answer",
    "expected_answers",
    "answer",
    "answer_key",
    "correct",
    "correct_answer",
    "correct_option",
    "correct_index",
    "correct_option_index",
    "metadata",
}


@dataclass
class FrozenClock:
    now: datetime

    def __call__(self) -> datetime:
        return self.now


@dataclass
class FakeLearningItemExtractor:
    result: ExtractorResult | None = None
    seen_sources: list[SourceDocument] = field(default_factory=list)

    def extract(self, source: SourceDocument) -> ExtractorResult:
        self.seen_sources.append(source)
        assert self.result is not None
        return self.result


def _span_for(fragment: str) -> ExtractedEvidenceSpan:
    start = SOURCE_CONTENT.index(fragment)
    return ExtractedEvidenceSpan(start=start, end=start + len(fragment))


def _extracted(
    *,
    item_type: str,
    canonical_form: str,
    meaning_ja: str,
    fragment: str,
    confidence: float = 0.9,
    **overrides,
) -> ExtractedCandidate:
    values = {
        "item_type": item_type,
        "canonical_form": canonical_form,
        "meaning_ja": meaning_ja,
        "evidence_span": _span_for(fragment),
        "confidence": confidence,
    }
    values.update(overrides)
    return ExtractedCandidate(**values)


def _phase4_fixture_candidates() -> tuple[ExtractedCandidate, ...]:
    """Issue #167 推奨 fixture。expression の両 direction を発生させる。"""
    return (
        _extracted(
            item_type="expression",
            canonical_form="se rendre compte de",
            meaning_ja="〜に気づく",
            fragment="rendu compte",
            explanation_ja="よく出る表現",
            level="A2",
            confidence=0.95,
        ),
        _extracted(
            item_type="vocabulary",
            canonical_form="stratégie",
            meaning_ja="戦略",
            fragment="stratégie",
            confidence=0.8,
        ),
        _extracted(
            item_type="grammar",
            canonical_form="il fallait",
            meaning_ja="〜しなければならなかった",
            fragment="il fallait",
            explanation_ja="義務の過去",
            level="A2",
            confidence=0.85,
        ),
        _extracted(
            item_type="conjugation",
            canonical_form="changer",
            meaning_ja="変える",
            fragment="changer",
            confidence=0.7,
        ),
    )


def _result() -> ExtractorResult:
    return ExtractorResult(
        candidates=_phase4_fixture_candidates(),
        provider="openai",
        model="gpt-4o-mini",
        extraction_version=EXTRACTION_VERSION,
    )


def _bind(
    store: TutorSqliteStore,
    fake: FakeLearningItemExtractor,
    clock: FrozenClock,
) -> None:
    app.dependency_overrides[get_tutor_store] = lambda: store
    app.dependency_overrides[get_learning_item_extractor] = lambda: fake
    app.dependency_overrides[get_tutor_service] = lambda: build_tutor_service(
        store, clock=clock
    )


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(NOW)


@pytest.fixture
def store() -> TutorSqliteStore:
    return TutorSqliteStore.in_memory()


@pytest.fixture
def fake() -> FakeLearningItemExtractor:
    return FakeLearningItemExtractor(result=_result())


@pytest.fixture
def client(
    store: TutorSqliteStore, fake: FakeLearningItemExtractor, clock: FrozenClock
) -> Iterator[TestClient]:
    _bind(store, fake, clock)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _post_source(client: TestClient) -> dict:
    res = client.post(
        "/api/tutor/sources",
        json={
            "title": SOURCE_TITLE,
            "content": SOURCE_CONTENT,
            "language": "fr",
            "metadata": {"note": SOURCE_NOTE},
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


def _extract(client: TestClient, source_id: str) -> dict:
    res = client.post(f"/api/tutor/sources/{source_id}/candidates/extract")
    assert res.status_code == 200, res.text
    return res.json()


def _by_form(rows: list[dict]) -> dict[str, dict]:
    return {row["canonical_form"]: row for row in rows}


def _accept(client: TestClient, candidate_id: str) -> dict:
    res = client.post(f"/api/tutor/candidates/{candidate_id}/accept")
    assert res.status_code == 200, res.text
    return res.json()


def _accept_fixture(client: TestClient, *forms: str) -> dict[str, dict]:
    source = _post_source(client)
    created = _extract(client, source["id"])["created"]
    by_form = _by_form(created)
    return {form: _accept(client, by_form[form]["id"])["item"] for form in forms}


def _assert_no_answer_leak(body: dict) -> None:
    assert _LEAKED_ANSWER_KEYS.isdisjoint(body)


def _generated(store: TutorSqliteStore, item_id: str, exercise_type: str):
    item = store.learning_items.get(item_id)
    assert item is not None
    sources = {}
    for ref in item.source_refs:
        document = store.source_documents.get(ref.source_document_id)
        if document is not None:
            sources[document.id] = document
    result = generate_exercise(
        item,
        exercise_type,
        pool=store.learning_items.list(),
        seed=DEFAULT_GENERATION_SEED,
        sources=sources,
    )
    assert result.exercise is not None, result.skip_reason
    return result.exercise


def _answer(
    client: TestClient,
    store: TutorSqliteStore,
    item_id: str,
    exercise_type: str,
    *,
    correct: bool = True,
    occurred_at: datetime | None = None,
    event_id: str | None = None,
) -> dict:
    generated = _generated(store, item_id, exercise_type)
    expected = generated.answer_key.expected_answers[0]
    if correct:
        if generated.spec.response_kind == "reconstruction":
            payload_answer: str | list[str] = list(tokenize_canonical_form(expected))
        else:
            payload_answer = expected
    else:
        payload_answer = "wrong-answer"
    payload: dict[str, object] = {"answer": payload_answer}
    if occurred_at is not None:
        payload["occurred_at"] = occurred_at.isoformat()
    if event_id is not None:
        payload["id"] = event_id
    res = client.post(
        f"/api/tutor/items/{item_id}/exercises/{exercise_type}/answer",
        json=payload,
    )
    assert res.status_code == 201, res.text
    return res.json()


def _record_review(
    client: TestClient,
    item_id: str,
    *,
    exercise_type: str,
    result: str = "correct",
    occurred_at: datetime | None = None,
    event_id: str | None = None,
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


def _queue(client: TestClient) -> dict:
    res = client.get("/api/tutor/reviews/queue")
    assert res.status_code == 200, res.text
    return res.json()


def _queue_keys(body: dict) -> list[tuple[str, str]]:
    return [(row["item"]["id"], row["skill_direction"]) for row in body["entries"]]


def _item_detail(client: TestClient, item_id: str) -> dict:
    res = client.get(f"/api/tutor/items/{item_id}")
    assert res.status_code == 200, res.text
    return res.json()


def _schedules_by_direction(detail: dict) -> dict[str, dict]:
    return {row["skill_direction"]: row for row in detail["review_schedules"]}


def _create_vocab(client: TestClient, form: str, meaning: str, **overrides) -> dict:
    payload = {
        "item_type": "vocabulary",
        "canonical_form": form,
        "meaning_ja": meaning,
    }
    payload.update(overrides)
    res = client.post("/api/tutor/items", json=payload)
    assert res.status_code == 201, res.text
    return res.json()["item"]


def test_phase4_practice_to_due_review_to_reschedule_vertical_slice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """必須 vertical slice: 学習 → due 前後 → 今日の復習 → 再schedule → 再open。

    推奨文の expression を recognition / production の別 schedule で動かし、
    片方向の回答がもう片方を壊さないことを確認する。
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    db_path = tmp_path / "tutor-phase4.db"
    file_store = TutorSqliteStore(f"sqlite:///{db_path}")
    fake = FakeLearningItemExtractor(result=_result())
    file_clock = FrozenClock(NOW)
    _bind(file_store, fake, file_clock)
    try:
        with TestClient(app) as http:
            created = _post_source(http)
            source_id = created["id"]
            extracted = _extract(http, source_id)
            by_form = _by_form(extracted["created"])
            expression = _accept(http, by_form["se rendre compte de"]["id"])["item"]
            vocab = _accept(http, by_form["stratégie"]["id"])["item"]
            expression_id = expression["id"]
            assert expression["canonical_form"] == "se rendre compte de"
            assert expression["item_type"] == "expression"

            practice = http.post(
                "/api/tutor/practice/sessions",
                json={
                    "source_id": source_id,
                    "question_count": 6,
                    "seed": "phase4",
                },
            )
            assert practice.status_code == 200, practice.text
            practice_body = practice.json()
            assert practice_body["generated_count"] >= 2
            directions = {row["skill_direction"] for row in practice_body["exercises"]}
            assert "recognition" in directions
            assert "production" in directions
            for row in practice_body["exercises"]:
                _assert_no_answer_leak(row)

            rec = _answer(
                http,
                file_store,
                expression_id,
                "meaning_recognition",
                event_id="evt-learn-recognition",
            )
            assert rec["correct"] is True
            assert rec["event"]["metadata"]["skill_direction"] == "recognition"
            rec_state = rec["learner_state"]["by_direction"]
            assert rec_state["recognition"]["correct_count"] == 1
            assert rec_state["recognition"]["attempt_count"] == 1
            assert "production" not in rec_state
            assert rec["review_schedule"]["skill_direction"] == "recognition"
            assert rec["review_schedule"]["interval_days"] == 1.0
            rec_due_at = NOW + timedelta(days=1)
            assert rec["review_schedule"]["due_at"].startswith("2026-08-24T12:00:00")

            file_clock.now = NOW + PRODUCTION_LAG
            prod = _answer(
                http,
                file_store,
                expression_id,
                "cloze",
                event_id="evt-learn-production",
            )
            assert prod["correct"] is True
            assert prod["event"]["metadata"]["skill_direction"] == "production"
            prod_state = prod["learner_state"]["by_direction"]
            assert prod_state["production"]["correct_count"] == 1
            assert prod_state["recognition"]["consecutive_correct"] == 1
            assert prod["review_schedule"]["skill_direction"] == "production"
            assert prod["review_schedule"]["interval_days"] == 1.0
            prod_due_at = NOW + PRODUCTION_LAG + timedelta(days=1)
            assert prod["review_schedule"]["due_at"].startswith("2026-08-24T18:00:00")

            detail = _item_detail(http, expression_id)
            schedules = _schedules_by_direction(detail)
            assert set(schedules) == {"recognition", "production"}
            assert schedules["recognition"]["review_count"] == 1
            assert schedules["production"]["review_count"] == 1

            empty = _queue(http)
            assert empty["summary"]["total_due"] == 0
            assert empty["entries"] == []

            file_clock.now = rec_due_at - timedelta(microseconds=1)
            assert _queue(http)["summary"]["total_due"] == 0

            file_clock.now = rec_due_at
            rec_only = _queue(http)
            assert rec_only["summary"] == {
                "total_due": 1,
                "recognition_due": 1,
                "production_due": 0,
                "overdue_count": 0,
            }
            assert _queue_keys(rec_only) == [(expression_id, "recognition")]
            assert vocab["id"] not in {row["item"]["id"] for row in rec_only["entries"]}

            file_clock.now = prod_due_at
            both = _queue(http)
            assert both["summary"]["total_due"] == 2
            assert both["summary"]["recognition_due"] == 1
            assert both["summary"]["production_due"] == 1
            assert _queue_keys(both) == [
                (expression_id, "recognition"),
                (expression_id, "production"),
            ]
            assert (
                both["entries"][0]["overdue_seconds"]
                > both["entries"][1]["overdue_seconds"]
            )

            review = http.post(
                "/api/tutor/review/sessions",
                json={"question_count": 5, "seed": "phase4-review"},
            )
            assert review.status_code == 200, review.text
            review_body = review.json()
            exercises = review_body["exercises"]
            assert review_body["generated_count"] == 2
            assert review_body["skipped_entries"] == []
            for row in exercises:
                _assert_no_answer_leak(row)
            assert [row["learning_item_id"] for row in exercises] == [
                expression_id,
                expression_id,
            ]
            assert [row["skill_direction"] for row in exercises] == [
                "recognition",
                "production",
            ]
            assert exercises[0]["exercise_type"] == "meaning_recognition"
            assert exercises[1]["exercise_type"] == "cloze"

            before_prod = _schedules_by_direction(_item_detail(http, expression_id))[
                "production"
            ]
            rec_review = _answer(
                http,
                file_store,
                expression_id,
                "meaning_recognition",
                event_id="evt-review-recognition",
            )
            assert rec_review["correct"] is True
            assert rec_review["review_schedule"]["skill_direction"] == "recognition"
            assert rec_review["review_schedule"]["interval_days"] == 3.0
            assert rec_review["review_schedule"]["review_count"] == 2
            assert rec_review["review_schedule"]["lapse_count"] == 0
            rec_after = rec_review["learner_state"]["by_direction"]
            assert rec_after["recognition"]["consecutive_correct"] == 2
            assert rec_after["production"]["incorrect_count"] == 0
            after_prod = _schedules_by_direction(_item_detail(http, expression_id))[
                "production"
            ]
            assert after_prod["due_at"] == before_prod["due_at"]
            assert after_prod["interval_days"] == before_prod["interval_days"]
            assert after_prod["lapse_count"] == before_prod["lapse_count"]
            remaining = _queue(http)
            assert _queue_keys(remaining) == [(expression_id, "production")]

            prod_review = _answer(
                http,
                file_store,
                expression_id,
                "cloze",
                correct=False,
                event_id="evt-review-production",
            )
            assert prod_review["correct"] is False
            assert prod_review["review_schedule"]["skill_direction"] == "production"
            assert prod_review["review_schedule"]["interval_days"] == 1.0
            assert prod_review["review_schedule"]["lapse_count"] == 1
            assert prod_review["review_schedule"]["review_count"] == 2
            prod_after = prod_review["learner_state"]["by_direction"]
            assert prod_after["production"]["incorrect_count"] == 1
            assert prod_after["production"]["consecutive_correct"] == 0
            assert prod_after["recognition"]["consecutive_correct"] == 2
            rec_unmoved = _schedules_by_direction(_item_detail(http, expression_id))[
                "recognition"
            ]
            assert rec_unmoved["interval_days"] == 3.0
            assert rec_unmoved["lapse_count"] == 0
            assert rec_unmoved["review_count"] == 2
            assert _queue(http)["summary"]["total_due"] == 0
    finally:
        app.dependency_overrides.clear()
        file_store.engine.dispose()

    reopened = TutorSqliteStore(f"sqlite:///{db_path}")
    fake_reopen = FakeLearningItemExtractor(result=_result())
    reopen_clock = FrozenClock(prod_due_at)
    _bind(reopened, fake_reopen, reopen_clock)
    try:
        with TestClient(app) as http:
            loaded = _item_detail(http, expression_id)
            state = loaded["learner_state"]
            assert state["attempt_count"] == 4
            assert state["correct_count"] == 3
            assert state["incorrect_count"] == 1
            by_direction = state["by_direction"]
            assert by_direction["recognition"]["correct_count"] == 2
            assert by_direction["production"]["incorrect_count"] == 1
            schedules = _schedules_by_direction(loaded)
            assert schedules["recognition"]["interval_days"] == 3.0
            assert schedules["production"]["lapse_count"] == 1
            events = reopened.learning_events.list_by_item(expression_id)
            by_id = {event.id: event for event in events}
            assert set(by_id) == {
                "evt-learn-recognition",
                "evt-learn-production",
                "evt-review-recognition",
                "evt-review-production",
            }
            assert by_id["evt-review-recognition"].result == "correct"
            assert by_id["evt-review-production"].result == "incorrect"
            assert _queue(http)["summary"]["total_due"] == 0
    finally:
        app.dependency_overrides.clear()
        reopened.engine.dispose()


def test_phase4_clock_timezone_overdue_and_date_boundary(
    client: TestClient, clock: FrozenClock, store: TutorSqliteStore
):
    """injected clock / timezone-aware UTC / 日付跨ぎ / overdue 古い順。"""
    items = _accept_fixture(client, "se rendre compte de", "stratégie")
    expression_id = items["se rendre compte de"]["id"]
    _answer(client, store, expression_id, "meaning_recognition")

    due_at = NOW + timedelta(days=1)
    clock.now = due_at - timedelta(microseconds=1)
    assert _queue(client)["summary"]["total_due"] == 0
    clock.now = due_at
    at_due = _queue(client)
    assert _queue_keys(at_due) == [(expression_id, "recognition")]
    assert at_due["entries"][0]["overdue_seconds"] == 0
    clock.now = due_at + timedelta(seconds=1)
    after = _queue(client)
    assert after["entries"][0]["overdue_seconds"] == 1.0

    occurred_jst = datetime(2026, 8, 23, 21, 0, tzinfo=JST)
    older = _create_vocab(client, "livre", "本")
    newer = _create_vocab(client, "maison", "家")
    _record_review(
        client,
        older["id"],
        exercise_type="ja_to_fr",
        occurred_at=occurred_jst - timedelta(days=3),
    )
    _record_review(
        client,
        newer["id"],
        exercise_type="ja_to_fr",
        occurred_at=occurred_jst - timedelta(days=1),
    )
    older_schedule = _schedules_by_direction(_item_detail(client, older["id"]))[
        "production"
    ]
    assert older_schedule["interval_days"] == 1.0
    assert older_schedule["due_at"].startswith("2026-08-21T12:00:00")

    clock.now = datetime(2026, 8, 24, 20, 59, 59, tzinfo=JST)
    before_boundary = _queue_keys(_queue(client))
    assert (expression_id, "recognition") not in before_boundary

    clock.now = datetime(2026, 8, 24, 21, 0, tzinfo=JST)
    crossed = _queue(client)
    keys = _queue_keys(crossed)
    assert keys[0] == (older["id"], "production")
    assert keys[1] == (newer["id"], "production")
    assert (expression_id, "recognition") in keys
    assert older_schedule["interval_days"] == 1.0
    assert crossed["summary"]["overdue_count"] >= 2

    clock.now = datetime(2026, 8, 24, 0, 0, tzinfo=UTC)
    date_cross = _queue(client)
    assert (older["id"], "production") in _queue_keys(date_cross)


def test_phase4_schedule_write_failure_and_rebuild_returns_to_queue(
    client: TestClient,
    store: TutorSqliteStore,
    clock: FrozenClock,
    monkeypatch: pytest.MonkeyPatch,
):
    """schedule 失敗は Event/State を残さず、欠損は replay で due queue へ戻す。"""
    items = _accept_fixture(client, "se rendre compte de", "stratégie")
    expression_id = items["se rendre compte de"]["id"]
    _answer(
        client,
        store,
        expression_id,
        "meaning_recognition",
        event_id="evt-rebuild-rec",
    )
    clock.now = NOW + PRODUCTION_LAG
    _answer(
        client,
        store,
        expression_id,
        "cloze",
        event_id="evt-rebuild-prod",
    )
    original_rec = store.review_schedules.get(expression_id, "recognition")
    original_prod = store.review_schedules.get(expression_id, "production")
    assert original_rec is not None
    assert original_prod is not None

    original_merge = Session.merge

    def fail_schedule_merge(
        self: Session, instance: object, **kwargs: object
    ) -> object:
        if isinstance(instance, ReviewScheduleRow):
            raise RuntimeError("schedule write failed")
        return original_merge(self, instance, **kwargs)

    monkeypatch.setattr(Session, "merge", fail_schedule_merge)
    generated = _generated(store, expression_id, "meaning_recognition")
    with pytest.raises(RuntimeError, match="schedule write failed"):
        client.post(
            f"/api/tutor/items/{expression_id}/exercises/meaning_recognition/answer",
            json={
                "answer": generated.answer_key.expected_answers[0],
                "id": "evt-should-rollback",
            },
        )
    monkeypatch.undo()
    event_ids = [
        event.id for event in store.learning_events.list_by_item(expression_id)
    ]
    assert "evt-should-rollback" not in event_ids
    state = store.learner_states.get(expression_id)
    assert state is not None
    assert state.by_direction["recognition"].attempt_count == 1
    assert store.review_schedules.get(expression_id, "recognition") == original_rec

    store.review_schedules.replace_for_item(expression_id, [original_prod])
    clock.now = NOW + PRODUCTION_LAG + timedelta(days=1)
    missing = _queue(client)
    assert _queue_keys(missing) == [(expression_id, "production")]
    rebuilder = build_review_schedule_rebuilder(
        learning_items=store.learning_items,
        learning_events=store.learning_events,
        review_schedules=store.review_schedules,
    )
    found = rebuilder.detect_inconsistencies(expression_id)
    assert [item.kind for item in found] == ["missing_schedule"]
    rebuilt = rebuilder.rebuild_for_item(expression_id)
    assert {row.skill_direction for row in rebuilt} == {
        "recognition",
        "production",
    }
    restored = store.review_schedules.get(expression_id, "recognition")
    assert restored == original_rec
    restored_queue = _queue(client)
    assert _queue_keys(restored_queue) == [
        (expression_id, "recognition"),
        (expression_id, "production"),
    ]


def test_phase4_excludes_inactive_unscheduled_duplicate_and_skip(
    client: TestClient, store: TutorSqliteStore, clock: FrozenClock
):
    """inactive / 未schedule は due にせず、skip と duplicate で予定を進めない。"""
    items = _accept_fixture(client, "se rendre compte de", "stratégie", "il fallait")
    expression_id = items["se rendre compte de"]["id"]
    grammar_id = items["il fallait"]["id"]
    _answer(client, store, expression_id, "meaning_recognition")

    unscheduled = _create_vocab(client, "bonjour", "こんにちは")
    suspended = _create_vocab(client, "chat", "猫", status="suspended")
    mastered = _create_vocab(client, "chien", "犬", status="mastered")
    past = NOW - timedelta(days=2)
    _record_review(client, suspended["id"], exercise_type="ja_to_fr", occurred_at=past)
    _record_review(client, mastered["id"], exercise_type="ja_to_fr", occurred_at=past)
    _record_review(
        client,
        grammar_id,
        exercise_type="meaning_recognition",
        occurred_at=past,
    )

    clock.now = NOW + timedelta(days=1)
    due = _queue(client)
    keys = _queue_keys(due)
    assert (expression_id, "recognition") in keys
    assert (grammar_id, "recognition") in keys
    assert (unscheduled["id"], "recognition") not in keys
    assert (unscheduled["id"], "production") not in keys
    assert (suspended["id"], "production") not in keys
    assert (mastered["id"], "production") not in keys

    before_grammar = store.review_schedules.get(grammar_id, "recognition")
    assert before_grammar is not None
    before_events = len(store.learning_events.list_by_item(grammar_id))
    session = client.post(
        "/api/tutor/review/sessions",
        json={"question_count": 20, "seed": "phase4-skip"},
    )
    assert session.status_code == 200, session.text
    skipped = {
        row["learning_item_id"]: row for row in session.json()["skipped_entries"]
    }
    assert skipped[grammar_id]["skip_reason"] == "generation_not_implemented"
    assert skipped[grammar_id]["skill_direction"] == "recognition"
    after_grammar = store.review_schedules.get(grammar_id, "recognition")
    assert after_grammar == before_grammar
    assert len(store.learning_events.list_by_item(grammar_id)) == before_events

    first = _answer(
        client,
        store,
        expression_id,
        "meaning_recognition",
        event_id="evt-dup-review",
    )
    assert first["review_schedule"]["review_count"] == 2
    generated = _generated(store, expression_id, "meaning_recognition")
    dup = client.post(
        f"/api/tutor/items/{expression_id}/exercises/meaning_recognition/answer",
        json={
            "answer": generated.answer_key.expected_answers[0],
            "id": "evt-dup-review",
        },
    )
    assert dup.status_code == 409
    state = store.learner_states.get(expression_id)
    assert state is not None
    assert state.by_direction["recognition"].attempt_count == 2
    assert len(store.learning_events.list_by_item(expression_id)) == 2


def test_phase4_existing_quiz_and_tts_contracts_are_unchanged(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    question = client.get("/api/questions/next")
    assert question.status_code == 200
    assert {"verb", "tense", "pronoun"} <= set(question.json())

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

    source = _post_source(client)
    extracted = _extract(client, source["id"])
    assert len(extracted["created"]) == 4
    listed = client.get("/api/tutor/sources")
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == source["id"]
    practice = client.post(
        "/api/tutor/practice/sessions",
        json={"source_id": source["id"], "question_count": 5},
    )
    assert practice.status_code == 200
    empty_review = client.get("/api/tutor/reviews/queue")
    assert empty_review.status_code == 200
    assert empty_review.json()["summary"]["total_due"] == 0


def test_phase4_does_not_expose_ranking_or_today_endpoints():
    with TestClient(app) as http:
        spec = http.get("/openapi.json").json()
    paths = spec["paths"]
    assert "/api/tutor/reviews/queue" in paths
    assert "/api/tutor/review/sessions" in paths
    assert "/api/tutor/practice/sessions" in paths
    queue_get = paths["/api/tutor/reviews/queue"]["get"]
    param_names = {row["name"] for row in queue_get.get("parameters", [])}
    assert "now" not in param_names
    forbidden = (
        "/api/tutor/reviews/today",
        "/api/tutor/recommendations",
        "/api/tutor/ranking",
        "/api/tutor/exercises",
    )
    for path in forbidden:
        assert path not in paths, path
