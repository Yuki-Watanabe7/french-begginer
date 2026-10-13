"""explicit known API（Issue #201）の HTTP 契約テスト。"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_tutor_store
from app.domain.known_item_policy import POLICY_VERSION
from app.main import app
from app.repositories.sqlite import TutorSqliteStore

PAST = datetime.now(UTC) - timedelta(days=3)


@pytest.fixture
def store() -> TutorSqliteStore:
    return TutorSqliteStore.in_memory()


@pytest.fixture
def client(store: TutorSqliteStore) -> Iterator[TestClient]:
    app.dependency_overrides[get_tutor_store] = lambda: store
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_mark_known_is_idempotent_and_undo_restores(client: TestClient) -> None:
    item = _create_item(client, canonical_form="livre", meaning_ja="本")
    other = _create_item(client, canonical_form="maison", meaning_ja="家")

    missing = client.get(f"/api/tutor/items/{item['id']}/known")
    assert missing.status_code == 200
    assert missing.json()["explicit_known"] is False
    assert missing.json()["updated_at"] is None

    marked = client.post(f"/api/tutor/items/{item['id']}/known")
    assert marked.status_code == 200, marked.text
    body = marked.json()
    assert set(body) == {
        "learning_item_id",
        "explicit_known",
        "updated_at",
        "policy_version",
    }
    assert body["explicit_known"] is True
    assert body["policy_version"] == POLICY_VERSION
    assert "mastered" not in marked.text

    again = client.post(f"/api/tutor/items/{item['id']}/known")
    assert again.status_code == 200
    assert again.json()["updated_at"] == body["updated_at"]

    detail = client.get(f"/api/tutor/items/{item['id']}")
    assert detail.status_code == 200
    assert detail.json()["item"]["status"] == "active"

    hidden = client.get(
        "/api/tutor/today",
        params={"question_count": 5, "max_new_count": 2},
    )
    assert hidden.status_code == 200, hidden.text
    assert _new_ids(hidden.json()) == {other["id"]}

    cleared = client.post(f"/api/tutor/items/{item['id']}/known/undo")
    assert cleared.status_code == 200
    assert cleared.json()["explicit_known"] is False

    restored = client.get(
        "/api/tutor/today", params={"question_count": 5, "max_new_count": 2}
    )
    assert _new_ids(restored.json()) == {item["id"], other["id"]}

    missing_item = client.post("/api/tutor/items/missing/known")
    assert missing_item.status_code == 404


def test_known_due_item_stays_in_review_queue(client: TestClient) -> None:
    item = _create_item(client, canonical_form="pain", meaning_ja="パン")
    other = _create_item(client, canonical_form="vin", meaning_ja="ワイン")
    reviewed = client.post(
        f"/api/tutor/items/{item['id']}/reviews",
        json={
            "exercise_type": "meaning_recognition",
            "result": "incorrect",
            "occurred_at": PAST.isoformat(),
        },
    )
    assert reviewed.status_code == 201, reviewed.text
    marked = client.post(f"/api/tutor/items/{item['id']}/known")
    assert marked.status_code == 200, marked.text

    queue = client.get("/api/tutor/reviews/queue")
    assert queue.status_code == 200, queue.text
    assert item["id"] in {entry["item"]["id"] for entry in queue.json()["entries"]}

    plan = client.get(
        "/api/tutor/today",
        params={"question_count": 5, "max_new_count": 2},
    )
    assert plan.status_code == 200, plan.text
    body = plan.json()
    assert any(
        entry["learning_item_id"] == item["id"] and entry["activity_kind"] == "review"
        for entry in body["entries"]
    )
    assert item["id"] not in _new_ids(body)
    assert other["id"] in _new_ids(body)
    assert "mastered" not in plan.text


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


def _new_ids(plan: dict) -> set[str]:
    return {
        entry["learning_item_id"]
        for entry in plan["entries"]
        if entry["activity_kind"] == "new_practice"
    }
