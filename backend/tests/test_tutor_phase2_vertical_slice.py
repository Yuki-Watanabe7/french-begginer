"""Source → Candidate → LearningItem の vertical slice（Issue #137 / Phase 2）。

保存済み Source から fake extractor で学習候補を抽出し、根拠確認・
accept / reject・LearningItem 化・再抽出の重複抑止・DB 再 open を
HTTP API + SQLite で一本につなぐ。実 LLM は使わない。
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_learning_item_extractor, get_tutor_store
from app.domain.noun import NOUNS
from app.domain.tutor import SourceDocument
from app.main import app
from app.repositories.sqlite import TutorSqliteStore
from app.services.exceptions import ExtractionTransientError
from app.services.extraction_prompt import EXTRACTION_VERSION
from app.services.extraction_schema import ExtractedCandidate, ExtractedEvidenceSpan
from app.services.extractors import ExtractorResult

SOURCE_TITLE = "Article test"
SOURCE_CONTENT = "Je me suis rendu compte qu'il fallait changer de stratégie."
SOURCE_NOTE = "se rendre compte が気になった"


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


def _phase2_fixture_candidates() -> tuple[ExtractedCandidate, ...]:
    """Issue #137 推奨 fixture。4種 + 重複 + 範囲外 span。"""
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
            item_type="expression",
            canonical_form="  SE RENDRE COMPTE DE  ",
            meaning_ja="気づく",
            fragment="rendu compte",
            confidence=0.4,
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
            item_type="vocabulary",
            canonical_form="stratégie",
            meaning_ja="戦略",
            fragment="stratégie",
            confidence=0.8,
        ),
        _extracted(
            item_type="conjugation",
            canonical_form="changer",
            meaning_ja="変える",
            fragment="changer",
            confidence=0.7,
        ),
        _extracted(
            item_type="vocabulary",
            canonical_form="bonjour",
            meaning_ja="こんにちは",
            fragment="stratégie",
            evidence_span=ExtractedEvidenceSpan(start=0, end=len(SOURCE_CONTENT) + 8),
            confidence=0.99,
        ),
    )


def _result(
    candidates: tuple[ExtractedCandidate, ...] | None = None,
) -> ExtractorResult:
    return ExtractorResult(
        candidates=tuple(
            candidates if candidates is not None else _phase2_fixture_candidates()
        ),
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


def _bind(store: TutorSqliteStore, fake: FakeLearningItemExtractor) -> None:
    app.dependency_overrides[get_tutor_store] = lambda: store
    app.dependency_overrides[get_learning_item_extractor] = lambda: fake


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


def _list_candidates(client: TestClient, source_id: str) -> list[dict]:
    res = client.get(f"/api/tutor/sources/{source_id}/candidates")
    assert res.status_code == 200, res.text
    return res.json()


def _by_form(rows: list[dict]) -> dict[str, dict]:
    return {row["canonical_form"]: row for row in rows}


def test_phase2_source_to_candidate_to_learning_item_vertical_slice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """必須 vertical slice: 保存済み Source → 抽出 → 採否 → LearningItem → 再open。

    fake extractor は推奨文から expression / grammar / vocabulary / conjugation
    を返し、重複と範囲外 span は deterministic layer が除外する。
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    db_path = tmp_path / "tutor-phase2.db"
    file_store = TutorSqliteStore(f"sqlite:///{db_path}")
    fake = FakeLearningItemExtractor(result=_result())
    _bind(file_store, fake)
    try:
        with TestClient(app) as http:
            created = _post_source(http)
            source_id = created["id"]
            assert created["content"] == SOURCE_CONTENT

            detail = http.get(f"/api/tutor/sources/{source_id}")
            assert detail.status_code == 200, detail.text
            assert detail.json()["content"] == SOURCE_CONTENT

            extracted = _extract(http, source_id)
            assert extracted["source_document_id"] == source_id
            assert extracted["extraction_version"] == EXTRACTION_VERSION
            created_rows = extracted["created"]
            assert extracted["skipped"] == []
            forms = {row["canonical_form"] for row in created_rows}
            assert forms == {
                "se rendre compte de",
                "il fallait",
                "stratégie",
                "changer",
            }
            assert "bonjour" not in forms
            assert "SE RENDRE COMPTE DE" not in forms
            types = {row["item_type"] for row in created_rows}
            assert types == {"expression", "grammar", "vocabulary", "conjugation"}
            assert all(row["status"] == "candidate" for row in created_rows)
            assert all("metadata" not in row for row in created_rows)
            assert all("provider" not in row for row in created_rows)
            assert file_store.learning_items.list() == []

            listed = _list_candidates(http, source_id)
            assert len(listed) == 4
            by_form = _by_form(listed)
            assert by_form["se rendre compte de"]["evidence_text"] == "rendu compte"
            assert by_form["il fallait"]["evidence_text"] == "il fallait"
            assert by_form["stratégie"]["evidence_text"] == "stratégie"
            assert by_form["changer"]["evidence_text"] == "changer"

            accepted = http.post(
                f"/api/tutor/candidates/{by_form['se rendre compte de']['id']}/accept"
            )
            assert accepted.status_code == 200, accepted.text
            accepted_body = accepted.json()
            assert accepted_body["merged"] is False
            assert accepted_body["candidate"]["status"] == "accepted"
            item = accepted_body["item"]
            item_id = item["id"]
            assert item["canonical_form"] == "se rendre compte de"
            assert item["meaning_ja"] == "〜に気づく"
            assert item["item_type"] == "expression"
            assert len(item["source_refs"]) == 1
            ref = item["source_refs"][0]
            assert ref["source_document_id"] == source_id
            assert ref["confidence"] == 0.95
            start = ref["evidence_span"]["start"]
            end = ref["evidence_span"]["end"]
            assert SOURCE_CONTENT[start:end] == "rendu compte"

            rejected = http.post(
                f"/api/tutor/candidates/{by_form['stratégie']['id']}/reject"
            )
            assert rejected.status_code == 200, rejected.text
            assert rejected.json()["status"] == "rejected"

            after_review = _by_form(_list_candidates(http, source_id))
            assert after_review["se rendre compte de"]["status"] == "accepted"
            assert after_review["stratégie"]["status"] == "rejected"
            assert after_review["il fallait"]["status"] == "candidate"
            assert after_review["changer"]["status"] == "candidate"

            items = file_store.learning_items.list()
            assert [row.id for row in items] == [item_id]
            assert items[0].canonical_form == "se rendre compte de"

            item_detail = http.get(f"/api/tutor/items/{item_id}")
            assert item_detail.status_code == 200, item_detail.text
            loaded_item = item_detail.json()["item"]
            assert loaded_item["id"] == item_id
            assert loaded_item["source_refs"][0]["source_document_id"] == source_id
            loaded_span = loaded_item["source_refs"][0]["evidence_span"]
            assert SOURCE_CONTENT[loaded_span["start"] : loaded_span["end"]] == (
                "rendu compte"
            )

            again = _extract(http, source_id)
            assert again["created"] == []
            skipped_ids = {row["id"] for row in again["skipped"]}
            assert skipped_ids == {row["id"] for row in listed}
            skipped_by_form = _by_form(again["skipped"])
            assert skipped_by_form["se rendre compte de"]["status"] == "accepted"
            assert skipped_by_form["stratégie"]["status"] == "rejected"
            assert len(_list_candidates(http, source_id)) == 4
            assert [row.id for row in file_store.learning_items.list()] == [item_id]
    finally:
        app.dependency_overrides.clear()
        file_store.engine.dispose()

    reopened = TutorSqliteStore(f"sqlite:///{db_path}")
    fake_reopen = FakeLearningItemExtractor(result=_result())
    _bind(reopened, fake_reopen)
    try:
        with TestClient(app) as http:
            listed = _by_form(_list_candidates(http, source_id))
            assert listed["se rendre compte de"]["status"] == "accepted"
            assert listed["stratégie"]["status"] == "rejected"
            assert listed["il fallait"]["status"] == "candidate"
            assert listed["changer"]["status"] == "candidate"
            assert listed["se rendre compte de"]["evidence_text"] == "rendu compte"

            item_detail = http.get(f"/api/tutor/items/{item_id}")
            assert item_detail.status_code == 200
            loaded = item_detail.json()["item"]
            assert loaded["canonical_form"] == "se rendre compte de"
            assert loaded["source_refs"][0]["source_document_id"] == source_id

            persisted = reopened.learning_items.list()
            assert [row.id for row in persisted] == [item_id]
            candidates = reopened.learning_item_candidates.list_by_source(source_id)
            assert len(candidates) == 4
    finally:
        app.dependency_overrides.clear()
        reopened.engine.dispose()


def test_phase2_accept_merges_existing_learning_item(
    client: TestClient, store: TutorSqliteStore
):
    source = _post_source(client)
    existing = client.post(
        "/api/tutor/items",
        json={
            "item_type": "expression",
            "canonical_form": "SE RENDRE COMPTE DE",
            "meaning_ja": "手入力の意味",
        },
    )
    assert existing.status_code == 201, existing.text
    item_id = existing.json()["item"]["id"]

    created = _extract(client, source["id"])["created"]
    expression = _by_form(created)["se rendre compte de"]
    accepted = client.post(f"/api/tutor/candidates/{expression['id']}/accept")
    assert accepted.status_code == 200, accepted.text
    body = accepted.json()
    assert body["merged"] is True
    assert body["item"]["id"] == item_id
    assert body["item"]["meaning_ja"] == "手入力の意味"
    assert [ref["source_document_id"] for ref in body["item"]["source_refs"]] == [
        source["id"]
    ]
    assert len(store.learning_items.list()) == 1


def test_phase2_provider_failure_leaves_existing_candidates(
    client: TestClient, fake: FakeLearningItemExtractor, store: TutorSqliteStore
):
    source = _post_source(client)
    first = _extract(client, source["id"])
    assert len(first["created"]) == 4

    fake.error = ExtractionTransientError("timeout", kind="timeout")
    failed = client.post(f"/api/tutor/sources/{source['id']}/candidates/extract")
    assert failed.status_code == 503

    remaining = store.learning_item_candidates.list_by_source(source["id"])
    assert len(remaining) == 4
    assert {row.status for row in remaining} == {"candidate"}
    listed = _list_candidates(client, source["id"])
    assert {row["id"] for row in listed} == {row["id"] for row in first["created"]}


def test_phase2_does_not_expose_exercise_generation_endpoints():
    with TestClient(app) as http:
        spec = http.get("/openapi.json").json()
    paths = spec["paths"]
    assert "/api/tutor/sources/{source_id}/candidates/extract" in paths
    assert "/api/tutor/candidates/{candidate_id}/accept" in paths
    forbidden = (
        "/api/tutor/exercises",
        "/api/tutor/items/{item_id}/exercises",
        "/api/tutor/practice",
        "/api/tutor/recommendations",
    )
    for path in forbidden:
        assert path not in paths, path


def test_phase2_existing_quiz_and_tts_contracts_are_unchanged(
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
