"""Candidate 抽出・一覧・採否 API（Issue #134）の HTTP 契約テスト。"""

from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_learning_item_extractor, get_tutor_store
from app.domain.tutor import SourceDocument
from app.main import app
from app.repositories.sqlite import TutorSqliteStore
from app.services.exceptions import (
    ExtractionConfigError,
    ExtractionInvalidResponseError,
    ExtractionTransientError,
)
from app.services.extraction_prompt import EXTRACTION_VERSION
from app.services.extraction_schema import ExtractedCandidate, ExtractedEvidenceSpan
from app.services.extractors import ExtractorResult

CONTENT = "Je me suis rendu compte qu'il fallait changer de stratégie."


@dataclass
class FakeLearningItemExtractor:
    result: ExtractorResult | None = None
    error: Exception | None = None
    seen_sources: list[SourceDocument] = field(default_factory=list)

    def extract(self, source: SourceDocument) -> ExtractorResult:
        self.seen_sources.append(source)
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


def _span_for(fragment: str) -> ExtractedEvidenceSpan:
    start = CONTENT.index(fragment)
    return ExtractedEvidenceSpan(start=start, end=start + len(fragment))


def _extracted(**overrides) -> ExtractedCandidate:
    values = {
        "item_type": "expression",
        "canonical_form": "se rendre compte",
        "meaning_ja": "〜に気づく",
        "evidence_span": _span_for("rendu compte"),
        "confidence": 0.9,
        "explanation_ja": "よく出る表現",
        "level": "A2",
    }
    values.update(overrides)
    return ExtractedCandidate(**values)


def _result(
    candidates: tuple[ExtractedCandidate, ...] | list[ExtractedCandidate] | None = None,
) -> ExtractorResult:
    return ExtractorResult(
        candidates=tuple(candidates if candidates is not None else (_extracted(),)),
        provider="openai",
        model="gpt-4o-mini",
        extraction_version=EXTRACTION_VERSION,
    )


@pytest.fixture
def store() -> TutorSqliteStore:
    return TutorSqliteStore.in_memory()


@pytest.fixture
def fake() -> FakeLearningItemExtractor:
    return FakeLearningItemExtractor(result=_result())


@pytest.fixture
def client(
    store: TutorSqliteStore, fake: FakeLearningItemExtractor
) -> Iterator[TestClient]:
    app.dependency_overrides[get_tutor_store] = lambda: store
    app.dependency_overrides[get_learning_item_extractor] = lambda: fake
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _create_source(client: TestClient, **overrides) -> dict:
    payload = {"title": "記事", "content": CONTENT}
    payload.update(overrides)
    res = client.post("/api/tutor/sources", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def _extract(client: TestClient, source_id: str) -> dict:
    res = client.post(f"/api/tutor/sources/{source_id}/candidates/extract")
    assert res.status_code == 200, res.text
    return res.json()


def test_extract_saves_candidates_and_hides_provider_payload(client: TestClient):
    source = _create_source(client)
    body = _extract(client, source["id"])

    assert body["source_document_id"] == source["id"]
    assert body["extraction_version"] == EXTRACTION_VERSION
    assert len(body["created"]) == 1
    assert body["skipped"] == []
    candidate = body["created"][0]
    assert candidate["status"] == "candidate"
    assert candidate["canonical_form"] == "se rendre compte"
    assert candidate["evidence_text"] == "rendu compte"
    assert candidate["confidence"] == 0.9
    assert "metadata" not in candidate
    assert "provider" not in candidate
    assert "raw" not in candidate


def test_extract_missing_source_returns_404(client: TestClient):
    res = client.post("/api/tutor/sources/missing-source/candidates/extract")
    assert res.status_code == 404
    assert "SourceDocument" in res.json()["detail"]


def test_list_candidates_for_source(client: TestClient):
    source = _create_source(client)
    created = _extract(client, source["id"])["created"][0]

    res = client.get(f"/api/tutor/sources/{source['id']}/candidates")
    assert res.status_code == 200
    body = res.json()
    assert [row["id"] for row in body] == [created["id"]]
    assert body[0]["status"] == "candidate"
    assert body[0]["evidence_text"] == "rendu compte"
    assert "metadata" not in body[0]


def test_list_candidates_missing_source_returns_404(client: TestClient):
    res = client.get("/api/tutor/sources/missing-source/candidates")
    assert res.status_code == 404
    assert "SourceDocument" in res.json()["detail"]


def test_reextract_does_not_duplicate(client: TestClient):
    source = _create_source(client)
    first = _extract(client, source["id"])
    second = _extract(client, source["id"])

    assert len(first["created"]) == 1
    assert second["created"] == []
    assert second["skipped"][0]["id"] == first["created"][0]["id"]

    listed = client.get(f"/api/tutor/sources/{source['id']}/candidates")
    assert len(listed.json()) == 1


def test_accept_creates_learning_item(client: TestClient):
    source = _create_source(client)
    candidate = _extract(client, source["id"])["created"][0]
    res = client.post(f"/api/tutor/candidates/{candidate['id']}/accept")
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["merged"] is False
    assert body["candidate"]["status"] == "accepted"
    item = body["item"]
    assert item["canonical_form"] == "se rendre compte"
    assert item["meaning_ja"] == "〜に気づく"
    assert item["explanation_ja"] == "よく出る表現"
    assert item["level"] == "A2"
    assert len(item["source_refs"]) == 1
    ref = item["source_refs"][0]
    assert ref["source_document_id"] == source["id"]
    assert ref["confidence"] == 0.9
    assert ref["evidence_span"]["start"] == CONTENT.index("rendu compte")

    detail = client.get(f"/api/tutor/items/{item['id']}")
    assert detail.status_code == 200
    assert detail.json()["item"]["id"] == item["id"]


def test_accept_merges_existing_learning_item(client: TestClient):
    source = _create_source(client)
    created_item = client.post(
        "/api/tutor/items",
        json={
            "item_type": "expression",
            "canonical_form": "se rendre compte",
            "meaning_ja": "手入力の意味",
        },
    )
    assert created_item.status_code == 201
    item_id = created_item.json()["item"]["id"]

    candidate = _extract(client, source["id"])["created"][0]
    res = client.post(f"/api/tutor/candidates/{candidate['id']}/accept")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["merged"] is True
    assert body["item"]["id"] == item_id
    assert body["item"]["meaning_ja"] == "手入力の意味"
    assert body["item"]["source_refs"][0]["source_document_id"] == source["id"]


def test_reject_does_not_create_learning_item(
    client: TestClient, store: TutorSqliteStore
):
    source = _create_source(client)
    candidate = _extract(client, source["id"])["created"][0]
    res = client.post(f"/api/tutor/candidates/{candidate['id']}/reject")
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "rejected"

    listed = client.get(f"/api/tutor/sources/{source['id']}/candidates")
    assert listed.json()[0]["status"] == "rejected"
    assert store.learning_items.list() == []


def test_reextract_after_reject_does_not_revive(client: TestClient):
    source = _create_source(client)
    candidate = _extract(client, source["id"])["created"][0]
    rejected = client.post(f"/api/tutor/candidates/{candidate['id']}/reject")
    assert rejected.status_code == 200

    again = _extract(client, source["id"])
    assert again["created"] == []
    assert again["skipped"][0]["status"] == "rejected"


def test_accept_rejected_returns_409(client: TestClient):
    source = _create_source(client)
    candidate = _extract(client, source["id"])["created"][0]
    assert (
        client.post(f"/api/tutor/candidates/{candidate['id']}/reject").status_code
        == 200
    )
    res = client.post(f"/api/tutor/candidates/{candidate['id']}/accept")
    assert res.status_code == 409
    assert "rejected" in res.json()["detail"]


def test_reject_accepted_returns_409(client: TestClient):
    source = _create_source(client)
    candidate = _extract(client, source["id"])["created"][0]
    assert (
        client.post(f"/api/tutor/candidates/{candidate['id']}/accept").status_code
        == 200
    )
    res = client.post(f"/api/tutor/candidates/{candidate['id']}/reject")
    assert res.status_code == 409
    assert "accepted" in res.json()["detail"]


def test_reaccept_is_idempotent(client: TestClient):
    source = _create_source(client)
    candidate = _extract(client, source["id"])["created"][0]
    first = client.post(f"/api/tutor/candidates/{candidate['id']}/accept")
    second = client.post(f"/api/tutor/candidates/{candidate['id']}/accept")
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["item"]["id"] == first.json()["item"]["id"]
    assert second.json()["merged"] is True


def test_accept_missing_candidate_returns_404(client: TestClient):
    res = client.post("/api/tutor/candidates/missing/accept")
    assert res.status_code == 404
    assert "LearningItemCandidate" in res.json()["detail"]


def test_extract_config_error_returns_503(
    client: TestClient, fake: FakeLearningItemExtractor
):
    source = _create_source(client)
    fake.error = ExtractionConfigError(
        "OPENAI_API_KEY が設定されていない", kind="missing_api_key"
    )
    res = client.post(f"/api/tutor/sources/{source['id']}/candidates/extract")
    assert res.status_code == 503
    assert "OPENAI_API_KEY" in res.json()["detail"]
    listed = client.get(f"/api/tutor/sources/{source['id']}/candidates")
    assert listed.json() == []


def test_extract_transient_error_returns_503(
    client: TestClient, fake: FakeLearningItemExtractor, store: TutorSqliteStore
):
    source = _create_source(client)
    first = _extract(client, source["id"])
    fake.error = ExtractionTransientError("rate limited", kind="rate_limit")
    res = client.post(f"/api/tutor/sources/{source['id']}/candidates/extract")
    assert res.status_code == 503
    remaining = store.learning_item_candidates.list_by_source(source["id"])
    assert [row.id for row in remaining] == [first["created"][0]["id"]]


def test_extract_invalid_response_returns_502(
    client: TestClient, fake: FakeLearningItemExtractor
):
    source = _create_source(client)
    fake.error = ExtractionInvalidResponseError(
        "structured output が空", kind="empty_response"
    )
    res = client.post(f"/api/tutor/sources/{source['id']}/candidates/extract")
    assert res.status_code == 502


def test_existing_question_api_is_unchanged(client: TestClient):
    res = client.get("/api/questions/next")
    assert res.status_code == 200
    assert {"verb", "tense", "pronoun"} <= set(res.json())
