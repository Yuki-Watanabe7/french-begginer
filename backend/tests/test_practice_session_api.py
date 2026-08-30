"""Tutor Practice Session API（Issue #150）の HTTP 契約テスト。"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_tutor_store
from app.main import app
from app.repositories.sqlite import TutorSqliteStore

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


def test_create_practice_session_from_all_items(client: TestClient):
    _create_vocab_pool(client)
    res = client.post(
        "/api/tutor/practice/sessions",
        json={"question_count": 5, "seed": "fixed"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["session_id"]
    assert body["requested_count"] == 5
    assert body["generated_count"] == 5
    assert len(body["exercises"]) == 5
    keys = [
        (row["learning_item_id"], row["exercise_type"]) for row in body["exercises"]
    ]
    assert len(keys) == len(set(keys))
    directions = {row["skill_direction"] for row in body["exercises"]}
    assert "recognition" in directions
    assert "production" in directions
    for row in body["exercises"]:
        assert _LEAKED_ANSWER_KEYS.isdisjoint(row)


def test_practice_session_item_ids_filter(client: TestClient):
    items = _create_vocab_pool(client)
    chosen = [items[0]["id"], items[2]["id"]]
    res = client.post(
        "/api/tutor/practice/sessions",
        json={"item_ids": chosen, "question_count": 10, "seed": "fixed"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    item_ids = {row["learning_item_id"] for row in body["exercises"]}
    assert item_ids <= set(chosen)
    assert item_ids == set(chosen)


def test_practice_session_source_id_filter(client: TestClient):
    source = client.post(
        "/api/tutor/sources",
        json={"title": "A", "content": "Le livre est sur la table."},
    )
    assert source.status_code == 201, source.text
    source_id = source.json()["id"]
    start = "Le livre est sur la table.".index("livre")
    item = _create_item(
        client,
        canonical_form="livre",
        meaning_ja="本",
        source_refs=[
            {
                "source_document_id": source_id,
                "evidence_span": {"start": start, "end": start + 5},
            }
        ],
    )
    _create_item(client, canonical_form="maison", meaning_ja="家")
    res = client.post(
        "/api/tutor/practice/sessions",
        json={"source_id": source_id, "question_count": 10, "seed": "fixed"},
    )
    assert res.status_code == 200, res.text
    item_ids = {row["learning_item_id"] for row in res.json()["exercises"]}
    assert item_ids == {item["id"]}


def test_practice_session_skips_unsupported_item(client: TestClient):
    pool = _create_vocab_pool(client)
    grammar = _create_item(
        client,
        item_type="grammar",
        canonical_form="il faut",
        meaning_ja="〜しなければならない",
    )
    res = client.post(
        "/api/tutor/practice/sessions",
        json={
            "item_ids": [grammar["id"], pool[0]["id"]],
            "question_count": 5,
            "seed": "fixed",
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    skipped = {row["learning_item_id"]: row for row in body["skipped_items"]}
    assert skipped[grammar["id"]]["skip_reason"] == "missing_source_evidence"
    assert all(row["learning_item_id"] != grammar["id"] for row in body["exercises"])
    assert body["generated_count"] >= 1


def test_practice_session_skips_inactive_item(client: TestClient):
    pool = _create_vocab_pool(client)
    inactive = _create_item(
        client,
        canonical_form="eau",
        meaning_ja="水",
        status="suspended",
    )
    res = client.post(
        "/api/tutor/practice/sessions",
        json={
            "item_ids": [inactive["id"], pool[0]["id"]],
            "question_count": 5,
            "seed": "fixed",
        },
    )
    assert res.status_code == 200, res.text
    skipped = {row["learning_item_id"]: row for row in res.json()["skipped_items"]}
    assert skipped[inactive["id"]]["skip_reason"] == "inactive_item"


def test_practice_session_seed_is_deterministic(client: TestClient):
    _create_vocab_pool(client)
    first = client.post(
        "/api/tutor/practice/sessions",
        json={"question_count": 5, "seed": "alpha"},
    )
    second = client.post(
        "/api/tutor/practice/sessions",
        json={"question_count": 5, "seed": "alpha"},
    )
    assert first.status_code == 200
    assert second.status_code == 200

    def keys(body: dict) -> list[tuple[str, str]]:
        return [
            (row["learning_item_id"], row["exercise_type"]) for row in body["exercises"]
        ]

    assert keys(first.json()) == keys(second.json())


def test_practice_session_zero_items(client: TestClient):
    res = client.post("/api/tutor/practice/sessions", json={"question_count": 5})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["exercises"] == []
    assert body["skipped_items"] == []
    assert body["generated_count"] == 0
    assert body["requested_count"] == 5


def test_practice_session_rejects_both_filters(client: TestClient):
    res = client.post(
        "/api/tutor/practice/sessions",
        json={"source_id": "src-1", "item_ids": ["item-1"]},
    )
    assert res.status_code == 422


def test_practice_session_question_count_out_of_range(client: TestClient):
    assert (
        client.post(
            "/api/tutor/practice/sessions", json={"question_count": 0}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/tutor/practice/sessions", json={"question_count": 21}
        ).status_code
        == 422
    )


def test_practice_session_missing_source(client: TestClient):
    res = client.post(
        "/api/tutor/practice/sessions", json={"source_id": "missing-source"}
    )
    assert res.status_code == 404
    assert "SourceDocument" in res.json()["detail"]


def test_practice_session_missing_item(client: TestClient):
    res = client.post(
        "/api/tutor/practice/sessions", json={"item_ids": ["missing-item"]}
    )
    assert res.status_code == 404
    assert "LearningItem" in res.json()["detail"]


def test_practice_session_does_not_persist(client: TestClient, store: TutorSqliteStore):
    _create_vocab_pool(client)
    res = client.post("/api/tutor/practice/sessions", json={"question_count": 3})
    assert res.status_code == 200, res.text
    session_id = res.json()["session_id"]
    # Session 用のテーブルは無く、再 GET できない。LearningEvent も増えない。
    assert client.get(f"/api/tutor/practice/sessions/{session_id}").status_code == 404
    for item in store.learning_items.list():
        assert store.learning_events.list_by_item(item.id) == []


def test_list_active_learning_items(client: TestClient):
    active = _create_item(client, canonical_form="livre", meaning_ja="本")
    _create_item(client, canonical_form="eau", meaning_ja="水", status="suspended")
    res = client.get("/api/tutor/items")
    assert res.status_code == 200, res.text
    body = res.json()
    assert [row["id"] for row in body] == [active["id"]]
    assert body[0]["canonical_form"] == "livre"


def test_list_learning_items_empty(client: TestClient):
    res = client.get("/api/tutor/items")
    assert res.status_code == 200
    assert res.json() == []


def test_generic_practice_collection_is_not_exposed():
    with TestClient(app) as http:
        spec = http.get("/openapi.json").json()
    paths = spec["paths"]
    assert "/api/tutor/practice/sessions" in paths
    assert "/api/tutor/practice" not in paths
    assert "/api/tutor/recommendations" not in paths
