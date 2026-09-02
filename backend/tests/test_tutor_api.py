"""Tutor 最小 API（Issue #112）の HTTP 契約テスト。"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_tutor_store
from app.api.tutor import SOURCE_CONTENT_PREVIEW_MAX_CHARS
from app.domain.tutor import SourceDocument
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


def test_list_sources_empty(client: TestClient):
    res = client.get("/api/tutor/sources")
    assert res.status_code == 200
    assert res.json() == []


def test_list_sources_returns_created_sources_newest_first(client: TestClient):
    first = _create_source(client, title="first", content="un")
    second = _create_source(client, title="second", content="deux")

    res = client.get("/api/tutor/sources")
    assert res.status_code == 200
    body = res.json()
    assert [row["id"] for row in body] == [second["id"], first["id"]]
    assert "content" not in body[0]
    assert body[0]["title"] == "second"
    assert body[0]["content_preview"] == "deux"
    assert body[0]["language"] == "fr"

    detail = client.get(f"/api/tutor/sources/{first['id']}")
    assert detail.status_code == 200
    assert detail.json()["content"] == "un"


def test_list_sources_order_is_stable_for_same_created_at(
    client: TestClient, store: TutorSqliteStore
):
    same_time = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
    store.source_documents.create(
        SourceDocument(id="src-b", title="B", content="b", created_at=same_time)
    )
    store.source_documents.create(
        SourceDocument(id="src-a", title="A", content="a", created_at=same_time)
    )

    res = client.get("/api/tutor/sources")
    assert res.status_code == 200
    assert [row["id"] for row in res.json()] == ["src-a", "src-b"]


def test_list_sources_truncates_content_preview(client: TestClient):
    content = "é" * (SOURCE_CONTENT_PREVIEW_MAX_CHARS + 20)
    created = _create_source(client, content=content)

    res = client.get("/api/tutor/sources")
    assert res.status_code == 200
    row = res.json()[0]
    assert row["id"] == created["id"]
    assert row["content_preview"] == content[:SOURCE_CONTENT_PREVIEW_MAX_CHARS]
    assert "content" not in row


def test_list_sources_honors_limit(client: TestClient):
    _create_source(client, title="a", content="a")
    _create_source(client, title="b", content="b")
    _create_source(client, title="c", content="c")

    res = client.get("/api/tutor/sources?limit=2")
    assert res.status_code == 200
    assert len(res.json()) == 2


def test_list_sources_rejects_invalid_limit(client: TestClient):
    assert client.get("/api/tutor/sources?limit=0").status_code == 422
    assert client.get("/api/tutor/sources?limit=-1").status_code == 422
    assert client.get("/api/tutor/sources?limit=101").status_code == 422
    assert client.get("/api/tutor/sources?limit=abc").status_code == 422


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
    assert created["review_schedules"] == []

    res = client.get(f"/api/tutor/items/{item['id']}")
    assert res.status_code == 200
    body = res.json()
    assert body["item"]["id"] == item["id"]
    assert body["learner_state"] is None
    assert body["review_schedule"] is None
    assert body["review_schedules"] == []


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
    assert body["review_schedule"]["skill_direction"] == "recognition"

    events = store.learning_events.list_by_item(item_id)
    assert len(events) == 1
    assert events[0].result == "correct"
    state = store.learner_states.get(item_id)
    assert state is not None
    assert state.attempt_count == 1
    schedule = store.review_schedules.get(item_id, "recognition")
    assert schedule is not None
    assert schedule.due_at == PAST + timedelta(days=1)

    detail = client.get(f"/api/tutor/items/{item_id}").json()
    assert detail["learner_state"]["attempt_count"] == 1
    assert detail["review_schedule"]["interval_days"] == 1.0
    assert detail["review_schedule"]["skill_direction"] == "recognition"
    assert [row["skill_direction"] for row in detail["review_schedules"]] == [
        "recognition"
    ]


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


def test_review_queue_empty_returns_zero_summary(client: TestClient):
    res = client.get("/api/tutor/reviews/queue")
    assert res.status_code == 200
    body = res.json()
    assert body == {
        "entries": [],
        "summary": {
            "total_due": 0,
            "recognition_due": 0,
            "production_due": 0,
            "overdue_count": 0,
        },
    }


def test_review_queue_returns_due_directions_without_now_query(client: TestClient):
    due_item_id = _create_item(client, canonical_form="due", meaning_ja="期限到来")[
        "item"
    ]["id"]
    future_item_id = _create_item(client, canonical_form="future", meaning_ja="未到来")[
        "item"
    ]["id"]
    unscheduled_id = _create_item(
        client, canonical_form="new", meaning_ja="未スケジュール"
    )["item"]["id"]

    overdue = client.post(
        f"/api/tutor/items/{due_item_id}/reviews",
        json={
            "exercise_type": "fr_to_ja",
            "result": "correct",
            "occurred_at": PAST.isoformat(),
        },
    )
    assert overdue.status_code == 201
    production = client.post(
        f"/api/tutor/items/{due_item_id}/reviews",
        json={
            "exercise_type": "ja_to_fr",
            "result": "incorrect",
            "occurred_at": PAST.isoformat(),
        },
    )
    assert production.status_code == 201
    future = client.post(
        f"/api/tutor/items/{future_item_id}/reviews",
        json={"exercise_type": "fr_to_ja", "result": "correct"},
    )
    assert future.status_code == 201

    res = client.get("/api/tutor/reviews/queue")
    assert res.status_code == 200
    body = res.json()
    ids = [row["item"]["id"] for row in body["entries"]]
    assert due_item_id in ids
    assert future_item_id not in ids
    assert unscheduled_id not in ids
    directions = [
        row["skill_direction"]
        for row in body["entries"]
        if row["item"]["id"] == due_item_id
    ]
    assert directions == ["production", "recognition"]
    assert body["summary"]["total_due"] >= 2
    assert body["summary"]["recognition_due"] >= 1
    assert body["summary"]["production_due"] >= 1
    rec = next(
        row
        for row in body["entries"]
        if row["item"]["id"] == due_item_id and row["skill_direction"] == "recognition"
    )
    assert rec["learner_state"]["by_direction"]["recognition"]["attempt_count"] >= 1
    assert rec["available_exercise_types"]
    assert "correct_answer" not in rec
    assert "expected" not in rec

    ignored = client.get("/api/tutor/reviews/queue?now=2099-01-01T00:00:00Z")
    assert ignored.status_code == 200
    ignored_ids = [row["item"]["id"] for row in ignored.json()["entries"]]
    assert due_item_id in ignored_ids
    assert future_item_id not in ignored_ids


def test_review_queue_limit_and_invalid_limit(client: TestClient):
    item_ids = []
    for index in range(3):
        item_id = _create_item(
            client, canonical_form=f"mot-{index}", meaning_ja=f"語{index}"
        )["item"]["id"]
        item_ids.append(item_id)
        reviewed = client.post(
            f"/api/tutor/items/{item_id}/reviews",
            json={
                "exercise_type": "fr_to_ja",
                "result": "correct",
                "occurred_at": PAST.isoformat(),
            },
        )
        assert reviewed.status_code == 201

    limited = client.get("/api/tutor/reviews/queue?limit=1")
    assert limited.status_code == 200
    body = limited.json()
    assert len(body["entries"]) == 1
    assert body["summary"]["total_due"] == 3
    assert client.get("/api/tutor/reviews/queue?limit=0").status_code == 422
    assert client.get("/api/tutor/reviews/queue?limit=-1").status_code == 422
    assert client.get("/api/tutor/reviews/queue?limit=101").status_code == 422
    assert client.get("/api/tutor/reviews/queue?limit=abc").status_code == 422


def test_review_queue_excludes_suspended_and_mastered(client: TestClient):
    active_id = _create_item(client, canonical_form="active", meaning_ja="学習中")[
        "item"
    ]["id"]
    suspended_id = _create_item(
        client,
        canonical_form="suspended",
        meaning_ja="停止",
        status="suspended",
    )["item"]["id"]
    mastered_id = _create_item(
        client,
        canonical_form="mastered",
        meaning_ja="定着",
        status="mastered",
    )["item"]["id"]
    for item_id in (active_id, suspended_id, mastered_id):
        res = client.post(
            f"/api/tutor/items/{item_id}/reviews",
            json={
                "exercise_type": "fr_to_ja",
                "result": "correct",
                "occurred_at": PAST.isoformat(),
            },
        )
        assert res.status_code == 201, res.text

    body = client.get("/api/tutor/reviews/queue").json()
    ids = [row["item"]["id"] for row in body["entries"]]
    assert active_id in ids
    assert suspended_id not in ids
    assert mastered_id not in ids


def test_existing_due_api_contract_is_unchanged(client: TestClient):
    item_id = _create_item(client, canonical_form="due", meaning_ja="期限到来")["item"][
        "id"
    ]
    reviewed = client.post(
        f"/api/tutor/items/{item_id}/reviews",
        json={
            "exercise_type": "fr_to_ja",
            "result": "correct",
            "occurred_at": PAST.isoformat(),
        },
    )
    assert reviewed.status_code == 201
    res = client.get("/api/tutor/reviews/due")
    assert res.status_code == 200
    assert isinstance(res.json(), list)
    assert res.json()[0]["item"]["id"] == item_id
    assert "entries" not in res.json()[0]
    assert "summary" not in res.json()[0]


def test_openapi_declares_tutor_request_and_response_schemas():
    with TestClient(app) as client:
        res = client.get("/openapi.json")
    assert res.status_code == 200
    spec = res.json()
    paths = spec["paths"]
    assert "/api/tutor/sources" in paths
    assert "get" in paths["/api/tutor/sources"]
    assert "/api/tutor/sources/{source_id}" in paths
    assert "/api/tutor/items" in paths
    assert "/api/tutor/items/{item_id}" in paths
    assert "/api/tutor/items/{item_id}/reviews" in paths
    assert "/api/tutor/reviews/due" in paths
    assert "/api/tutor/reviews/queue" in paths
    assert "/api/tutor/sources/{source_id}/candidates/extract" in paths
    assert "/api/tutor/sources/{source_id}/candidates" in paths
    assert "/api/tutor/candidates/{candidate_id}/accept" in paths
    assert "/api/tutor/candidates/{candidate_id}/reject" in paths

    due_params = paths["/api/tutor/reviews/due"]["get"].get("parameters") or []
    assert not any(param.get("name") == "now" for param in due_params)
    queue_params = paths["/api/tutor/reviews/queue"]["get"].get("parameters") or []
    assert not any(param.get("name") == "now" for param in queue_params)
    assert any(param.get("name") == "limit" for param in queue_params)

    schemas = spec["components"]["schemas"]
    for name in (
        "CreateSourceRequest",
        "CreateLearningItemRequest",
        "CreateReviewRequest",
        "LearningItemDetailResponse",
        "ReviewResponse",
        "DueReviewResponse",
        "ReviewQueue",
        "ReviewQueueEntry",
        "ReviewQueueSummary",
        "SourceDocument",
        "SourceSummary",
        "CandidateResponse",
        "ExtractCandidatesResponse",
        "AcceptCandidateResponse",
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
    assert "build_review_queue" not in source
    assert "apply_candidate_status" not in source
    assert "item_normalization_key" not in source
    assert "normalize_candidates" not in source
    assert "openai" not in source
    assert "OpenAILearningItemExtractor" not in source
