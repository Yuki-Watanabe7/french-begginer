"""Tutor 最小 API（Issue #112）の HTTP 契約テスト。"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_tutor_store
from app.main import app
from app.repositories.sqlite import TutorSqliteStore

PAST = datetime(2020, 1, 1, tzinfo=UTC)


@pytest.fixture
def store() -> TutorSqliteStore:
    return TutorSqliteStore.in_memory()


@pytest.fixture
def client(store: TutorSqliteStore) -> Iterator[TestClient]:
    app.dependency_overrides[get_tutor_store] = lambda: store
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _create_source(client: TestClient, **overrides) -> dict:
    payload = {"title": "手入力ソース", "content": "Il s'agit d'un article."}
    payload.update(overrides)
    res = client.post("/api/tutor/sources", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def _create_item(client: TestClient, **overrides) -> dict:
    payload = {
        "item_type": "expression",
        "canonical_form": "il s'agit de",
        "meaning_ja": "〜が問題である",
    }
    payload.update(overrides)
    res = client.post("/api/tutor/items", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def test_create_and_get_source(client: TestClient):
    created = _create_source(client)
    assert created["title"] == "手入力ソース"
    assert created["content"] == "Il s'agit d'un article."
    assert created["source_type"] == "manual_text"
    assert created["id"]

    res = client.get(f"/api/tutor/sources/{created['id']}")
    assert res.status_code == 200
    assert res.json()["id"] == created["id"]
    assert res.json()["content"] == created["content"]


def test_get_source_not_found(client: TestClient):
    res = client.get("/api/tutor/sources/missing-source")
    assert res.status_code == 404
    assert "SourceDocument" in res.json()["detail"]


def test_create_source_rejects_empty_title(client: TestClient):
    res = client.post("/api/tutor/sources", json={"title": "", "content": "bonjour"})
    assert res.status_code == 422


def test_create_and_get_learning_item(client: TestClient):
    source = _create_source(client)
    created = _create_item(
        client,
        source_refs=[{"source_document_id": source["id"]}],
        level="A2",
    )
    item = created["item"]
    assert item["canonical_form"] == "il s'agit de"
    assert item["source_refs"][0]["source_document_id"] == source["id"]
    assert created["learner_state"] is None
    assert created["review_schedule"] is None

    res = client.get(f"/api/tutor/items/{item['id']}")
    assert res.status_code == 200
    body = res.json()
    assert body["item"]["id"] == item["id"]
    assert body["learner_state"] is None
    assert body["review_schedule"] is None


def test_create_item_rejects_unknown_source_ref(client: TestClient):
    res = client.post(
        "/api/tutor/items",
        json={
            "item_type": "vocabulary",
            "canonical_form": "bonjour",
            "meaning_ja": "こんにちは",
            "source_refs": [{"source_document_id": "missing-source"}],
        },
    )
    assert res.status_code == 422
    assert "SourceDocument" in res.json()["detail"]


def test_get_item_not_found(client: TestClient):
    res = client.get("/api/tutor/items/missing-item")
    assert res.status_code == 404
    assert "LearningItem" in res.json()["detail"]


def test_review_persists_event_and_updates_state_and_schedule(
    client: TestClient, store: TutorSqliteStore
):
    item_id = _create_item(client)["item"]["id"]
    occurred_at = PAST.isoformat()
    res = client.post(
        f"/api/tutor/items/{item_id}/reviews",
        json={
            "exercise_type": "fr_to_ja",
            "result": "correct",
            "occurred_at": occurred_at,
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()

    assert body["event"]["learning_item_id"] == item_id
    assert body["event"]["result"] == "correct"
    assert body["event"]["exercise_type"] == "fr_to_ja"
    assert body["learner_state"]["attempt_count"] == 1
    assert body["learner_state"]["correct_count"] == 1
    assert body["learner_state"]["mastery_score"] == 1.0
    assert body["review_schedule"]["interval_days"] == 1.0
    assert body["review_schedule"]["review_count"] == 1

    events = store.learning_events.list_by_item(item_id)
    assert len(events) == 1
    assert events[0].result == "correct"
    state = store.learner_states.get(item_id)
    assert state is not None
    assert state.attempt_count == 1
    schedule = store.review_schedules.get(item_id)
    assert schedule is not None
    assert schedule.due_at == PAST + timedelta(days=1)

    detail = client.get(f"/api/tutor/items/{item_id}").json()
    assert detail["learner_state"]["attempt_count"] == 1
    assert detail["review_schedule"]["interval_days"] == 1.0


def test_review_missing_item_returns_404(client: TestClient):
    res = client.post(
        "/api/tutor/items/missing-item/reviews",
        json={"exercise_type": "fr_to_ja", "result": "correct"},
    )
    assert res.status_code == 404
    assert "LearningItem" in res.json()["detail"]


def test_review_invalid_result_returns_422(client: TestClient):
    item_id = _create_item(client)["item"]["id"]
    res = client.post(
        f"/api/tutor/items/{item_id}/reviews",
        json={"exercise_type": "fr_to_ja", "result": "maybe"},
    )
    assert res.status_code == 422


def test_review_invalid_exercise_type_returns_422(client: TestClient):
    item_id = _create_item(client)["item"]["id"]
    res = client.post(
        f"/api/tutor/items/{item_id}/reviews",
        json={"exercise_type": "unknown_drill", "result": "correct"},
    )
    assert res.status_code == 422


def test_review_naive_occurred_at_returns_422(client: TestClient):
    item_id = _create_item(client)["item"]["id"]
    res = client.post(
        f"/api/tutor/items/{item_id}/reviews",
        json={
            "exercise_type": "fr_to_ja",
            "result": "correct",
            "occurred_at": "2020-01-01T00:00:00",
        },
    )
    assert res.status_code == 422


def test_review_duplicate_event_id_returns_409(client: TestClient):
    item_id = _create_item(client)["item"]["id"]
    payload = {
        "id": "evt-dup",
        "exercise_type": "fr_to_ja",
        "result": "correct",
        "occurred_at": PAST.isoformat(),
    }
    first = client.post(f"/api/tutor/items/{item_id}/reviews", json=payload)
    assert first.status_code == 201, first.text
    second = client.post(f"/api/tutor/items/{item_id}/reviews", json=payload)
    assert second.status_code == 409
    assert "LearningEvent" in second.json()["detail"]


def test_due_reviews_returns_overdue_items_without_now_query(client: TestClient):
    due_item_id = _create_item(client, canonical_form="due", meaning_ja="期限到来")[
        "item"
    ]["id"]
    future_item_id = _create_item(client, canonical_form="future", meaning_ja="未到来")[
        "item"
    ]["id"]

    overdue = client.post(
        f"/api/tutor/items/{due_item_id}/reviews",
        json={
            "exercise_type": "fr_to_ja",
            "result": "correct",
            "occurred_at": PAST.isoformat(),
        },
    )
    assert overdue.status_code == 201
    future = client.post(
        f"/api/tutor/items/{future_item_id}/reviews",
        json={"exercise_type": "fr_to_ja", "result": "correct"},
    )
    assert future.status_code == 201

    res = client.get("/api/tutor/reviews/due")
    assert res.status_code == 200
    ids = [row["item"]["id"] for row in res.json()]
    assert due_item_id in ids
    assert future_item_id not in ids
    assert res.json()[0]["review_schedule"]["due_at"]

    ignored = client.get("/api/tutor/reviews/due?now=2099-01-01T00:00:00Z")
    assert ignored.status_code == 200
    ignored_ids = [row["item"]["id"] for row in ignored.json()]
    assert due_item_id in ignored_ids
    assert future_item_id not in ignored_ids


def test_openapi_declares_tutor_request_and_response_schemas():
    with TestClient(app) as client:
        res = client.get("/openapi.json")
    assert res.status_code == 200
    spec = res.json()
    paths = spec["paths"]
    assert "/api/tutor/sources" in paths
    assert "/api/tutor/sources/{source_id}" in paths
    assert "/api/tutor/items" in paths
    assert "/api/tutor/items/{item_id}" in paths
    assert "/api/tutor/items/{item_id}/reviews" in paths
    assert "/api/tutor/reviews/due" in paths

    due_params = paths["/api/tutor/reviews/due"]["get"].get("parameters") or []
    assert not any(param.get("name") == "now" for param in due_params)

    schemas = spec["components"]["schemas"]
    for name in (
        "CreateSourceRequest",
        "CreateLearningItemRequest",
        "CreateReviewRequest",
        "LearningItemDetailResponse",
        "ReviewResponse",
        "DueReviewResponse",
        "SourceDocument",
    ):
        assert name in schemas, name

    questions_paths = {
        "/api/questions/next",
        "/api/questions/session",
        "/api/answers/check",
        "/api/nouns/next",
        "/api/nouns/check",
    }
    assert questions_paths <= set(paths)


def test_existing_question_api_is_unchanged(client: TestClient):
    res = client.get("/api/questions/next")
    assert res.status_code == 200
    data = res.json()
    assert "verb" in data
    assert "tense" in data
    assert "pronoun" in data


def test_tutor_router_has_no_sql_or_domain_rules():
    import inspect

    import app.api.tutor as tutor_api

    source = inspect.getsource(tutor_api)
    assert "sqlalchemy" not in source
    assert "TutorSqliteStore" not in source
    assert "select(" not in source
    assert "apply_review_event" not in source
    assert "schedule_next_review" not in source
