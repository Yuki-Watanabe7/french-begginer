"""今日の学習 Plan / Session API（Issue #178）の HTTP 契約テスト。"""

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_tutor_store
from app.main import app
from app.repositories.sqlite import TutorSqliteStore

PAST = datetime(2020, 1, 1, tzinfo=UTC)
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
    "rank_score",
    "total_score",
    "components",
}


@pytest.fixture
def store() -> TutorSqliteStore:
    return TutorSqliteStore.in_memory()


@pytest.fixture
def client(store: TutorSqliteStore) -> Iterator[TestClient]:
    app.dependency_overrides[get_tutor_store] = lambda: store
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _create_item(client: TestClient, **overrides) -> dict:
    payload = {
        "item_type": "vocabulary",
        "canonical_form": "livre",
        "meaning_ja": "本",
    }
    payload.update(overrides)
    res = client.post("/api/tutor/items", json=payload)
    assert res.status_code == 201, res.text
    return res.json()["item"]


def _create_vocab_pool(client: TestClient) -> list[dict]:
    specs = (
        ("livre", "本"),
        ("maison", "家"),
        ("chat", "猫"),
        ("chien", "犬"),
    )
    return [
        _create_item(client, canonical_form=form, meaning_ja=meaning)
        for form, meaning in specs
    ]


def _make_due(
    client: TestClient, item_id: str, *, exercise_type: str = "meaning_recognition"
) -> None:
    res = client.post(
        f"/api/tutor/items/{item_id}/reviews",
        json={
            "exercise_type": exercise_type,
            "result": "incorrect",
            "occurred_at": PAST.isoformat(),
        },
    )
    assert res.status_code == 201, res.text


def _answer_for(item: dict, exercise: dict) -> str:
    if exercise["exercise_type"] == "meaning_recognition":
        return item["meaning_ja"]
    return item["canonical_form"]


def test_today_plan_returns_review_and_new_counts(client: TestClient):
    pool = _create_vocab_pool(client)
    _make_due(client, pool[0]["id"], exercise_type="meaning_recognition")
    res = client.get(
        "/api/tutor/today",
        params={"question_count": 10, "max_new_count": 3},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["review_count"] == 1
    assert body["new_count"] == 3
    assert body["total_count"] == 4
    assert body["deferred_due_count"] == 0
    assert body["policy_version"]
    assert body["explanation_summary"]
    assert body["entries"][0]["activity_kind"] == "review"
    assert body["entries"][0]["skill_direction"] == "recognition"
    assert "復習" in body["entries"][0]["explanation"]
    assert body["summary_reason_codes"]
    for entry in body["entries"]:
        assert _LEAKED_ANSWER_KEYS.isdisjoint(entry)


def test_today_plan_due_cap_and_deferred(client: TestClient):
    pool = _create_vocab_pool(client)
    for item in pool:
        _make_due(client, item["id"], exercise_type="meaning_recognition")
    res = client.get(
        "/api/tutor/today",
        params={"question_count": 2, "max_new_count": 3},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["review_count"] == 2
    assert body["new_count"] == 0
    assert body["deferred_due_count"] == 2


def test_today_plan_empty(client: TestClient):
    res = client.get("/api/tutor/today")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["entries"] == []
    assert body["total_count"] == 0
    assert body["review_count"] == 0
    assert body["new_count"] == 0


def test_today_session_generates_exercises_without_answers(client: TestClient):
    pool = _create_vocab_pool(client)
    _make_due(client, pool[0]["id"], exercise_type="ja_to_fr")
    res = client.post(
        "/api/tutor/today/sessions",
        json={"question_count": 10, "max_new_count": 3, "seed": "fixed"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["session_id"]
    assert body["generated_count"] == len(body["exercises"])
    assert body["generated_count"] == len(body["entries"])
    production = next(
        row
        for row in body["exercises"]
        if row["learning_item_id"] == pool[0]["id"]
        and row["skill_direction"] == "production"
    )
    assert production["skill_direction"] == "production"
    for row in body["exercises"]:
        assert _LEAKED_ANSWER_KEYS.isdisjoint(row)
        assert "correct_answer" not in row


def test_today_session_new_answer_creates_schedule(client: TestClient):
    pool = _create_vocab_pool(client)
    res = client.post(
        "/api/tutor/today/sessions",
        json={"question_count": 5, "max_new_count": 3, "seed": "fixed"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    new_entry = next(
        row for row in body["entries"] if row["activity_kind"] == "new_practice"
    )
    exercise = next(
        row
        for row in body["exercises"]
        if row["learning_item_id"] == new_entry["learning_item_id"]
    )
    item = next(row for row in pool if row["id"] == new_entry["learning_item_id"])
    before = client.get(f"/api/tutor/items/{item['id']}").json()["review_schedules"]
    assert before == []
    answered = client.post(
        f"/api/tutor/items/{item['id']}/exercises/{exercise['exercise_type']}/answer",
        json={"answer": _answer_for(item, exercise)},
    )
    assert answered.status_code == 201, answered.text
    after = {
        row["skill_direction"]: row
        for row in client.get(f"/api/tutor/items/{item['id']}").json()[
            "review_schedules"
        ]
    }
    assert new_entry["skill_direction"] in after
    assert (
        answered.json()["review_schedule"]["skill_direction"]
        == new_entry["skill_direction"]
    )


def test_today_session_review_updates_only_matching_direction(client: TestClient):
    pool = _create_vocab_pool(client)
    item_id = pool[0]["id"]
    _make_due(client, item_id, exercise_type="meaning_recognition")
    _make_due(client, item_id, exercise_type="ja_to_fr")
    session = client.post(
        "/api/tutor/today/sessions",
        json={"question_count": 10, "max_new_count": 0, "seed": "fixed"},
    )
    assert session.status_code == 200, session.text
    production = next(
        row
        for row in session.json()["exercises"]
        if row["skill_direction"] == "production"
    )
    before = {
        row["skill_direction"]: row
        for row in client.get(f"/api/tutor/items/{item_id}").json()["review_schedules"]
    }
    answered = client.post(
        f"/api/tutor/items/{item_id}/exercises/{production['exercise_type']}/answer",
        json={"answer": pool[0]["canonical_form"]},
    )
    assert answered.status_code == 201, answered.text
    after = {
        row["skill_direction"]: row
        for row in client.get(f"/api/tutor/items/{item_id}").json()["review_schedules"]
    }
    assert after["recognition"]["due_at"] == before["recognition"]["due_at"]
    assert after["production"]["due_at"] != before["production"]["due_at"]


def test_today_session_refresh_skips_answered_due(client: TestClient):
    pool = _create_vocab_pool(client)
    _make_due(client, pool[0]["id"], exercise_type="meaning_recognition")
    first = client.post(
        "/api/tutor/today/sessions",
        json={"question_count": 10, "max_new_count": 0, "seed": "fixed"},
    )
    assert first.status_code == 200, first.text
    review = next(
        row for row in first.json()["entries"] if row["activity_kind"] == "review"
    )
    exercise = next(
        row
        for row in first.json()["exercises"]
        if row["learning_item_id"] == review["learning_item_id"]
    )
    item = next(row for row in pool if row["id"] == review["learning_item_id"])
    answered = client.post(
        f"/api/tutor/items/{item['id']}/exercises/{exercise['exercise_type']}/answer",
        json={"answer": _answer_for(item, exercise)},
    )
    assert answered.status_code == 201, answered.text
    second = client.post(
        "/api/tutor/today/sessions",
        json={"question_count": 10, "max_new_count": 0, "seed": "fixed"},
    )
    assert second.status_code == 200, second.text
    assert all(
        not (
            row["learning_item_id"] == review["learning_item_id"]
            and row["activity_kind"] == "review"
        )
        for row in second.json()["entries"]
    )


def test_today_session_does_not_persist(client: TestClient, store: TutorSqliteStore):
    pool = _create_vocab_pool(client)
    event_count_before = len(store.learning_events.list_by_item(pool[0]["id"]))
    res = client.post("/api/tutor/today/sessions", json={"question_count": 3})
    assert res.status_code == 200, res.text
    session_id = res.json()["session_id"]
    assert client.get(f"/api/tutor/today/sessions/{session_id}").status_code == 404
    assert len(store.learning_events.list_by_item(pool[0]["id"])) == event_count_before


def test_today_validation(client: TestClient):
    assert (
        client.get("/api/tutor/today", params={"question_count": 0}).status_code == 422
    )
    assert (
        client.get("/api/tutor/today", params={"question_count": 21}).status_code == 422
    )
    assert (
        client.get("/api/tutor/today", params={"max_new_count": -1}).status_code == 422
    )
    assert (
        client.post("/api/tutor/today/sessions", json={"question_count": 0}).status_code
        == 422
    )
    assert (
        client.post(
            "/api/tutor/today/sessions", json={"now": PAST.isoformat()}
        ).status_code
        == 422
    )


def test_existing_practice_and_review_apis_remain(client: TestClient):
    pool = _create_vocab_pool(client)
    practice = client.post("/api/tutor/practice/sessions", json={"question_count": 3})
    assert practice.status_code == 200, practice.text
    assert practice.json()["generated_count"] >= 1
    review = client.post("/api/tutor/review/sessions", json={"question_count": 3})
    assert review.status_code == 200, review.text
    assert review.json()["generated_count"] == 0
    _make_due(client, pool[0]["id"], exercise_type="ja_to_fr")
    review_due = client.post("/api/tutor/review/sessions", json={"question_count": 3})
    assert review_due.status_code == 200, review_due.text
    assert review_due.json()["generated_count"] == 1


def test_today_endpoints_are_exposed_without_now_query():
    with TestClient(app) as http:
        spec = http.get("/openapi.json").json()
    paths = spec["paths"]
    assert "/api/tutor/today" in paths
    assert "/api/tutor/today/sessions" in paths
    assert "/api/tutor/practice/sessions" in paths
    assert "/api/tutor/review/sessions" in paths
    assert "/api/tutor/reviews/today" not in paths
    today_get = paths["/api/tutor/today"]["get"]
    param_names = {row["name"] for row in today_get.get("parameters", [])}
    assert "now" not in param_names
    session_post = paths["/api/tutor/today/sessions"]["post"]
    params = session_post.get("parameters") or []
    assert not any(param.get("name") == "now" for param in params)
