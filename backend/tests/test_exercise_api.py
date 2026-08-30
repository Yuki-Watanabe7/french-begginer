"""Tutor Exercise 取得・回答 API（Issue #149）の HTTP 契約テスト。"""

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_tutor_store
from app.domain.exercise_generation import generate_exercise
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


def test_get_exercise_omits_correct_answer(client: TestClient):
    items = _create_vocab_pool(client)
    res = client.get(f"/api/tutor/items/{items[0]['id']}/exercises/meaning_recognition")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["exercise_type"] == "meaning_recognition"
    assert body["response_kind"] == "choice"
    assert "本" in body["options"]
    assert _LEAKED_ANSWER_KEYS.isdisjoint(body)
    assert "metadata" not in body


def test_meaning_recognition_correct_and_incorrect(client: TestClient):
    items = _create_vocab_pool(client)
    item_id = items[0]["id"]
    path = f"/api/tutor/items/{item_id}/exercises/meaning_recognition/answer"

    correct = client.post(path, json={"answer": "本"})
    assert correct.status_code == 201, correct.text
    correct_body = correct.json()
    assert correct_body["correct"] is True
    assert correct_body["correct_answer"] == "本"
    assert correct_body["learner_state"]["correct_count"] == 1
    assert correct_body["event"]["exercise_type"] == "meaning_recognition"
    assert correct_body["event"]["metadata"]["skill_direction"] == "recognition"

    wrong = client.post(path, json={"answer": "家"})
    assert wrong.status_code == 201, wrong.text
    assert wrong.json()["correct"] is False
    assert wrong.json()["correct_answer"] == "本"
    assert wrong.json()["learner_state"]["attempt_count"] == 2
    assert wrong.json()["learner_state"]["incorrect_count"] == 1
    assert wrong.json()["review_schedule"]["lapse_count"] == 1


def test_ja_to_fr_normalizes_and_rejects_missing_accent(client: TestClient):
    item = _create_item(
        client,
        canonical_form="été",
        meaning_ja="夏",
    )
    path = f"/api/tutor/items/{item['id']}/exercises/ja_to_fr/answer"
    matching = client.post(path, json={"answer": "  ÉTÉ "})
    assert matching.status_code == 201, matching.text
    assert matching.json()["correct"] is True

    missing_accent = client.post(path, json={"answer": "ete"})
    assert missing_accent.status_code == 201, missing_accent.text
    assert missing_accent.json()["correct"] is False
    assert missing_accent.json()["correct_answer"] == "été"


def test_apostrophe_variants_are_accepted(client: TestClient):
    item = _create_item(
        client,
        item_type="expression",
        canonical_form="j'ai faim",
        meaning_ja="お腹が空いている",
    )
    res = client.post(
        f"/api/tutor/items/{item['id']}/exercises/ja_to_fr/answer",
        json={"answer": "J\u2019ai faim"},
    )
    assert res.status_code == 201, res.text
    assert res.json()["correct"] is True


def test_cloze_and_reconstruction(client: TestClient):
    content = "Je me suis rendu compte qu'il fallait changer de stratégie."
    fragment = "rendu compte"
    start = content.index(fragment)
    source = client.post(
        "/api/tutor/sources",
        json={"title": "fixture", "content": content},
    )
    assert source.status_code == 201, source.text
    item = _create_item(
        client,
        item_type="expression",
        canonical_form="se rendre compte de",
        meaning_ja="〜に気づく",
        explanation_ja="気づく",
        source_refs=[
            {
                "source_document_id": source.json()["id"],
                "evidence_span": {"start": start, "end": start + len(fragment)},
            }
        ],
    )

    cloze_get = client.get(f"/api/tutor/items/{item['id']}/exercises/cloze")
    assert cloze_get.status_code == 200, cloze_get.text
    assert _LEAKED_ANSWER_KEYS.isdisjoint(cloze_get.json())
    assert "____" in cloze_get.json()["prompt"]

    cloze = client.post(
        f"/api/tutor/items/{item['id']}/exercises/cloze/answer",
        json={"answer": fragment},
    )
    assert cloze.status_code == 201, cloze.text
    assert cloze.json()["correct"] is True
    assert cloze.json()["correct_answer"] == fragment
    assert cloze.json()["explanation_ja"] == "気づく"
    assert cloze.json()["source_context"] is not None

    recon = client.post(
        f"/api/tutor/items/{item['id']}/exercises/expression_reconstruction/answer",
        json={"answer": ["se", "rendre", "compte", "de"]},
    )
    assert recon.status_code == 201, recon.text
    assert recon.json()["correct"] is True
    assert recon.json()["given"] == ["se", "rendre", "compte", "de"]


def test_verb_conjugation_adapter_answer(client: TestClient, store: TutorSqliteStore):
    item = _create_item(
        client,
        item_type="conjugation",
        canonical_form="parler",
        meaning_ja="話す",
        metadata={"lemma": "parler", "tense": "présent"},
    )
    domain_item = store.learning_items.get(item["id"])
    assert domain_item is not None
    generated = generate_exercise(
        domain_item, "verb_conjugation", seed="tutor-exercise"
    )
    assert generated.exercise is not None
    expected = generated.exercise.answer_key.expected_answers[0]

    shown = client.get(f"/api/tutor/items/{item['id']}/exercises/verb_conjugation")
    assert shown.status_code == 200, shown.text
    assert _LEAKED_ANSWER_KEYS.isdisjoint(shown.json())
    assert "correct_answer" not in shown.json()

    res = client.post(
        f"/api/tutor/items/{item['id']}/exercises/verb_conjugation/answer",
        json={"answer": expected},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["correct"] is True
    assert body["correct_answer"] == expected
    assert body["event"]["metadata"]["generation_method"] == "conjugation_adapter"


def test_duplicate_answer_returns_409_without_double_apply(
    client: TestClient, store: TutorSqliteStore
):
    item = _create_item(client, canonical_form="livre", meaning_ja="本")
    payload = {"id": "evt-dup", "answer": "livre", "occurred_at": PAST.isoformat()}
    path = f"/api/tutor/items/{item['id']}/exercises/ja_to_fr/answer"
    first = client.post(path, json=payload)
    assert first.status_code == 201, first.text
    second = client.post(path, json=payload)
    assert second.status_code == 409
    assert "LearningEvent" in second.json()["detail"]
    assert store.learner_states.get(item["id"]).attempt_count == 1
    assert len(store.learning_events.list_by_item(item["id"])) == 1


def test_missing_item_returns_404(client: TestClient):
    res = client.get("/api/tutor/items/missing/exercises/ja_to_fr")
    assert res.status_code == 404
    answer = client.post(
        "/api/tutor/items/missing/exercises/ja_to_fr/answer",
        json={"answer": "livre"},
    )
    assert answer.status_code == 404


def test_unsupported_and_inactive_return_422(client: TestClient):
    item = _create_item(client)
    unsupported = client.get(
        f"/api/tutor/items/{item['id']}/exercises/verb_conjugation"
    )
    assert unsupported.status_code == 422
    assert unsupported.json()["detail"]["skip_reason"] == "unsupported_combination"

    suspended = _create_item(
        client,
        canonical_form="maison",
        meaning_ja="家",
        status="suspended",
    )
    inactive = client.get(f"/api/tutor/items/{suspended['id']}/exercises/ja_to_fr")
    assert inactive.status_code == 422
    assert inactive.json()["detail"]["skip_reason"] == "inactive_item"


def test_malformed_answer_returns_422_without_event(
    client: TestClient, store: TutorSqliteStore
):
    item = _create_item(client)
    res = client.post(
        f"/api/tutor/items/{item['id']}/exercises/ja_to_fr/answer",
        json={"answer": "   "},
    )
    assert res.status_code == 422
    assert store.learning_events.list_by_item(item["id"]) == []


def test_exercise_endpoints_are_in_openapi():
    with TestClient(app) as http:
        paths = http.get("/openapi.json").json()["paths"]
    assert "/api/tutor/items/{item_id}/exercises/{exercise_type}" in paths
    assert "/api/tutor/items/{item_id}/exercises/{exercise_type}/answer" in paths
    assert "get" in paths["/api/tutor/items/{item_id}/exercises/{exercise_type}"]
    assert (
        "post" in paths["/api/tutor/items/{item_id}/exercises/{exercise_type}/answer"]
    )
