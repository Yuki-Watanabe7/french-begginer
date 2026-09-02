"""due queue から Review Practice Session を生成する API（Issue #164）。"""

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
    client: TestClient, item_id: str, *, exercise_type: str = "ja_to_fr"
) -> None:
    res = client.post(
        f"/api/tutor/items/{item_id}/reviews",
        json={
            "exercise_type": exercise_type,
            "result": "correct",
            "occurred_at": PAST.isoformat(),
        },
    )
    assert res.status_code == 201, res.text


def test_create_review_session_from_due_queue_only(client: TestClient):
    pool = _create_vocab_pool(client)
    _make_due(client, pool[0]["id"], exercise_type="ja_to_fr")
    res = client.post(
        "/api/tutor/review/sessions",
        json={"question_count": 5, "seed": "fixed"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["session_id"]
    assert body["requested_count"] == 5
    assert body["generated_count"] == 1
    assert len(body["exercises"]) == 1
    exercise = body["exercises"][0]
    assert exercise["learning_item_id"] == pool[0]["id"]
    assert exercise["skill_direction"] == "production"
    assert exercise["exercise_type"] == "ja_to_fr"
    assert _LEAKED_ANSWER_KEYS.isdisjoint(exercise)
    assert "now" not in body


def test_review_session_excludes_future_and_unscheduled(client: TestClient):
    pool = _create_vocab_pool(client)
    _make_due(client, pool[0]["id"], exercise_type="ja_to_fr")
    recent = client.post(
        f"/api/tutor/items/{pool[1]['id']}/reviews",
        json={
            "exercise_type": "ja_to_fr",
            "result": "correct",
            "occurred_at": datetime.now(UTC).isoformat(),
        },
    )
    assert recent.status_code == 201, recent.text
    res = client.post(
        "/api/tutor/review/sessions",
        json={"question_count": 10, "seed": "fixed"},
    )
    assert res.status_code == 200, res.text
    item_ids = {row["learning_item_id"] for row in res.json()["exercises"]}
    assert item_ids == {pool[0]["id"]}
    assert pool[2]["id"] not in item_ids


def test_review_session_keeps_direction(client: TestClient):
    pool = _create_vocab_pool(client)
    _make_due(client, pool[0]["id"], exercise_type="meaning_recognition")
    _make_due(client, pool[1]["id"], exercise_type="ja_to_fr")
    res = client.post(
        "/api/tutor/review/sessions",
        json={"question_count": 10, "seed": "fixed"},
    )
    assert res.status_code == 200, res.text
    by_item = {row["learning_item_id"]: row for row in res.json()["exercises"]}
    assert by_item[pool[0]["id"]]["skill_direction"] == "recognition"
    assert by_item[pool[0]["id"]]["exercise_type"] == "meaning_recognition"
    assert by_item[pool[1]["id"]]["skill_direction"] == "production"
    assert by_item[pool[1]["id"]]["exercise_type"] == "ja_to_fr"


def test_review_session_handles_both_directions(client: TestClient):
    pool = _create_vocab_pool(client)
    item_id = pool[0]["id"]
    _make_due(client, item_id, exercise_type="meaning_recognition")
    _make_due(client, item_id, exercise_type="ja_to_fr")
    res = client.post(
        "/api/tutor/review/sessions",
        json={"question_count": 10, "seed": "fixed"},
    )
    assert res.status_code == 200, res.text
    directions = [row["skill_direction"] for row in res.json()["exercises"]]
    assert set(directions) == {"recognition", "production"}
    assert all(row["learning_item_id"] == item_id for row in res.json()["exercises"])


def test_review_session_question_count_cap(client: TestClient):
    pool = _create_vocab_pool(client)
    for item in pool:
        _make_due(client, item["id"], exercise_type="ja_to_fr")
    res = client.post(
        "/api/tutor/review/sessions",
        json={"question_count": 2, "seed": "fixed"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["requested_count"] == 2
    assert body["generated_count"] == 2
    assert len(body["exercises"]) == 2


def test_review_session_skips_unsupported_entry(client: TestClient):
    pool = _create_vocab_pool(client)
    grammar = _create_item(
        client,
        item_type="grammar",
        canonical_form="il faut",
        meaning_ja="〜しなければならない",
    )
    _make_due(client, grammar["id"], exercise_type="cloze")
    _make_due(client, pool[0]["id"], exercise_type="ja_to_fr")
    before = client.get(f"/api/tutor/items/{grammar['id']}").json()["review_schedules"]
    res = client.post(
        "/api/tutor/review/sessions",
        json={"question_count": 5, "seed": "fixed"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    skipped = {row["learning_item_id"]: row for row in body["skipped_entries"]}
    assert skipped[grammar["id"]]["skip_reason"] == "missing_source_evidence"
    assert skipped[grammar["id"]]["skill_direction"] == "production"
    assert all(row["learning_item_id"] != grammar["id"] for row in body["exercises"])
    after = client.get(f"/api/tutor/items/{grammar['id']}").json()["review_schedules"]
    assert after == before


def test_review_session_seed_is_deterministic(client: TestClient):
    pool = _create_vocab_pool(client)
    for item in pool:
        _make_due(client, item["id"], exercise_type="ja_to_fr")
    first = client.post(
        "/api/tutor/review/sessions",
        json={"question_count": 5, "seed": "alpha"},
    )
    second = client.post(
        "/api/tutor/review/sessions",
        json={"question_count": 5, "seed": "alpha"},
    )
    assert first.status_code == 200
    assert second.status_code == 200

    def keys(body: dict) -> list[tuple[str, str]]:
        return [
            (row["learning_item_id"], row["exercise_type"]) for row in body["exercises"]
        ]

    assert keys(first.json()) == keys(second.json())


def test_review_session_empty_due_queue(client: TestClient):
    _create_vocab_pool(client)
    res = client.post("/api/tutor/review/sessions", json={"question_count": 5})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["exercises"] == []
    assert body["skipped_entries"] == []
    assert body["generated_count"] == 0
    assert body["requested_count"] == 5


def test_review_session_question_count_out_of_range(client: TestClient):
    assert (
        client.post(
            "/api/tutor/review/sessions", json={"question_count": 0}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/tutor/review/sessions", json={"question_count": 21}
        ).status_code
        == 422
    )


def test_review_session_does_not_persist(client: TestClient, store: TutorSqliteStore):
    pool = _create_vocab_pool(client)
    _make_due(client, pool[0]["id"], exercise_type="ja_to_fr")
    event_count_before = len(store.learning_events.list_by_item(pool[0]["id"]))
    res = client.post("/api/tutor/review/sessions", json={"question_count": 3})
    assert res.status_code == 200, res.text
    session_id = res.json()["session_id"]
    assert client.get(f"/api/tutor/review/sessions/{session_id}").status_code == 404
    assert len(store.learning_events.list_by_item(pool[0]["id"])) == event_count_before


def test_review_session_answer_updates_only_matching_direction(client: TestClient):
    pool = _create_vocab_pool(client)
    item_id = pool[0]["id"]
    _make_due(client, item_id, exercise_type="meaning_recognition")
    _make_due(client, item_id, exercise_type="ja_to_fr")
    session = client.post(
        "/api/tutor/review/sessions",
        json={"question_count": 10, "seed": "fixed"},
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
    assert answered.json()["review_schedule"]["skill_direction"] == "production"


def test_review_session_rejects_now_in_request(client: TestClient):
    res = client.post(
        "/api/tutor/review/sessions",
        json={"question_count": 5, "now": PAST.isoformat()},
    )
    assert res.status_code == 422


def test_generic_review_mix_and_today_are_not_exposed():
    with TestClient(app) as http:
        spec = http.get("/openapi.json").json()
    paths = spec["paths"]
    assert "/api/tutor/review/sessions" in paths
    assert "/api/tutor/reviews/today" not in paths
    assert "/api/tutor/recommendations" not in paths
    params = paths["/api/tutor/review/sessions"]["post"].get("parameters") or []
    assert not any(param.get("name") == "now" for param in params)
