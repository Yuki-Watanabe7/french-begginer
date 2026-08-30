"""Source → LearningItem → Practice → LearningEvent の vertical slice。

Issue #152 / Phase 3。Phase 2 で accepted になった LearningItem を実際に解き、
結果が LearningEvent / LearnerState / ReviewSchedule へ残ることを
HTTP API + SQLite で一本につなぐ。実 LLM は使わない。
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_learning_item_extractor, get_tutor_store
from app.domain.conjugation import CONJUGATIONS, get_correct_answer
from app.domain.exercise import EXERCISE_VERSION, tokenize_canonical_form
from app.domain.exercise_generation import DEFAULT_GENERATION_SEED, generate_exercise
from app.domain.noun import NOUNS
from app.domain.tutor import SourceDocument
from app.main import app
from app.repositories.sqlite import TutorSqliteStore
from app.services.extraction_prompt import EXTRACTION_VERSION
from app.services.extraction_schema import ExtractedCandidate, ExtractedEvidenceSpan
from app.services.extractors import ExtractorResult

SOURCE_TITLE = "Article test"
SOURCE_CONTENT = "Je me suis rendu compte qu'il fallait changer de stratégie."
SOURCE_NOTE = "se rendre compte が気になった"
PARLER_CONTENT = "Je parle français tous les jours."

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
class FakeLearningItemExtractor:
    result: ExtractorResult | None = None
    results_by_content: dict[str, ExtractorResult] = field(default_factory=dict)
    seen_sources: list[SourceDocument] = field(default_factory=list)

    def extract(self, source: SourceDocument) -> ExtractorResult:
        self.seen_sources.append(source)
        if source.content in self.results_by_content:
            return self.results_by_content[source.content]
        assert self.result is not None
        return self.result


def _span_for(content: str, fragment: str) -> ExtractedEvidenceSpan:
    start = content.index(fragment)
    return ExtractedEvidenceSpan(start=start, end=start + len(fragment))


def _extracted(
    *,
    content: str,
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
        "evidence_span": _span_for(content, fragment),
        "confidence": confidence,
    }
    values.update(overrides)
    return ExtractedCandidate(**values)


def _phase3_fixture_candidates() -> tuple[ExtractedCandidate, ...]:
    """Issue #152 推奨 fixture。expression / vocab / grammar / conjugation。"""
    return (
        _extracted(
            content=SOURCE_CONTENT,
            item_type="expression",
            canonical_form="se rendre compte de",
            meaning_ja="〜に気づく",
            fragment="rendu compte",
            explanation_ja="よく出る表現",
            level="A2",
            confidence=0.95,
        ),
        _extracted(
            content=SOURCE_CONTENT,
            item_type="vocabulary",
            canonical_form="stratégie",
            meaning_ja="戦略",
            fragment="stratégie",
            confidence=0.8,
        ),
        _extracted(
            content=SOURCE_CONTENT,
            item_type="grammar",
            canonical_form="il fallait",
            meaning_ja="〜しなければならなかった",
            fragment="il fallait",
            explanation_ja="義務の過去",
            level="A2",
            confidence=0.85,
        ),
        _extracted(
            content=SOURCE_CONTENT,
            item_type="conjugation",
            canonical_form="changer",
            meaning_ja="変える",
            fragment="changer",
            confidence=0.7,
        ),
    )


def _parler_candidates() -> tuple[ExtractedCandidate, ...]:
    return (
        _extracted(
            content=PARLER_CONTENT,
            item_type="conjugation",
            canonical_form="parler",
            meaning_ja="話す",
            fragment="parle",
            tense="présent",
            mood="indicatif",
            confidence=0.9,
        ),
    )


def _result(
    candidates: tuple[ExtractedCandidate, ...] | None = None,
) -> ExtractorResult:
    return ExtractorResult(
        candidates=tuple(
            candidates if candidates is not None else _phase3_fixture_candidates()
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
    return FakeLearningItemExtractor(
        result=_result(),
        results_by_content={
            SOURCE_CONTENT: _result(),
            PARLER_CONTENT: _result(_parler_candidates()),
        },
    )


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


def _post_source(client: TestClient, **overrides) -> dict:
    payload = {
        "title": SOURCE_TITLE,
        "content": SOURCE_CONTENT,
        "language": "fr",
        "metadata": {"note": SOURCE_NOTE},
    }
    payload.update(overrides)
    res = client.post("/api/tutor/sources", json=payload)
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


def _accept(client: TestClient, candidate_id: str) -> dict:
    res = client.post(f"/api/tutor/candidates/{candidate_id}/accept")
    assert res.status_code == 200, res.text
    return res.json()


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


def _answer_payload(store: TutorSqliteStore, item_id: str, exercise_type: str):
    generated = _generated(store, item_id, exercise_type)
    expected = generated.answer_key.expected_answers[0]
    if generated.spec.response_kind == "reconstruction":
        return list(tokenize_canonical_form(expected)), expected
    return expected, expected


def test_phase3_source_to_practice_to_learning_event_vertical_slice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """必須 vertical slice: Source → accept → Exercise → Practice → Event → 再open。

    推奨文から expression / vocabulary を採用し、recognition / production を
    解いた結果が LearningEvent / LearnerState / ReviewSchedule に残る。
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    db_path = tmp_path / "tutor-phase3.db"
    file_store = TutorSqliteStore(f"sqlite:///{db_path}")
    fake = FakeLearningItemExtractor(result=_result())
    _bind(file_store, fake)
    try:
        with TestClient(app) as http:
            created = _post_source(http)
            source_id = created["id"]
            assert created["content"] == SOURCE_CONTENT

            extracted = _extract(http, source_id)
            by_form = _by_form(extracted["created"])
            assert set(by_form) == {
                "se rendre compte de",
                "stratégie",
                "il fallait",
                "changer",
            }

            expression = _accept(http, by_form["se rendre compte de"]["id"])
            vocab = _accept(http, by_form["stratégie"]["id"])
            grammar = _accept(http, by_form["il fallait"]["id"])
            changer = _accept(http, by_form["changer"]["id"])
            expression_id = expression["item"]["id"]
            vocab_id = vocab["item"]["id"]
            grammar_id = grammar["item"]["id"]
            changer_id = changer["item"]["id"]
            assert expression["item"]["item_type"] == "expression"
            assert changer["item"].get("metadata", {}).get("lemma") == "changer"
            assert "tense" not in changer["item"].get("metadata", {})

            recognition = http.get(
                f"/api/tutor/items/{expression_id}/exercises/meaning_recognition"
            )
            assert recognition.status_code == 200, recognition.text
            recognition_body = recognition.json()
            _assert_no_answer_leak(recognition_body)
            assert recognition_body["skill_direction"] == "recognition"
            assert recognition_body["response_kind"] == "choice"
            assert "〜に気づく" in recognition_body["options"]
            assert recognition_body["exercise_version"] == EXERCISE_VERSION

            production = http.get(
                f"/api/tutor/items/{expression_id}/exercises/ja_to_fr"
            )
            assert production.status_code == 200, production.text
            _assert_no_answer_leak(production.json())
            assert production.json()["skill_direction"] == "production"
            assert "se rendre compte de" not in production.json()["prompt"]

            cloze = http.get(f"/api/tutor/items/{expression_id}/exercises/cloze")
            assert cloze.status_code == 200, cloze.text
            cloze_body = cloze.json()
            _assert_no_answer_leak(cloze_body)
            assert "____" in cloze_body["prompt"]
            assert "rendu compte" not in cloze_body["prompt"]

            reconstruction = http.get(
                f"/api/tutor/items/{expression_id}/exercises/expression_reconstruction"
            )
            assert reconstruction.status_code == 200, reconstruction.text
            _assert_no_answer_leak(reconstruction.json())

            fr_to_ja = http.get(f"/api/tutor/items/{expression_id}/exercises/fr_to_ja")
            assert fr_to_ja.status_code == 422
            assert fr_to_ja.json()["detail"]["skip_reason"] == (
                "requires_semantic_grading"
            )

            grammar_choice = http.get(
                f"/api/tutor/items/{grammar_id}/exercises/meaning_recognition"
            )
            assert grammar_choice.status_code == 422
            assert grammar_choice.json()["detail"]["skip_reason"] == (
                "generation_not_implemented"
            )

            changer_verb = http.get(
                f"/api/tutor/items/{changer_id}/exercises/verb_conjugation"
            )
            assert changer_verb.status_code == 422
            assert changer_verb.json()["detail"]["skip_reason"] == (
                "unknown_conjugation_lemma"
            )

            session = http.post(
                "/api/tutor/practice/sessions",
                json={
                    "source_id": source_id,
                    "question_count": 6,
                    "seed": "phase3",
                },
            )
            assert session.status_code == 200, session.text
            session_body = session.json()
            exercises = session_body["exercises"]
            assert session_body["generated_count"] == len(exercises)
            assert exercises
            keys = [
                (row["learning_item_id"], row["exercise_type"]) for row in exercises
            ]
            assert len(keys) == len(set(keys))
            directions = {row["skill_direction"] for row in exercises}
            assert "recognition" in directions
            assert "production" in directions
            for row in exercises:
                _assert_no_answer_leak(row)
            assert all(row["exercise_type"] != "verb_conjugation" for row in exercises)

            recognition_row = next(
                row
                for row in exercises
                if row["exercise_type"] == "meaning_recognition"
            )
            production_row = next(
                row
                for row in exercises
                if row["exercise_type"] in {"ja_to_fr", "cloze"}
            )

            rec_answer, rec_expected = _answer_payload(
                file_store,
                recognition_row["learning_item_id"],
                recognition_row["exercise_type"],
            )
            rec_res = http.post(
                f"/api/tutor/items/{recognition_row['learning_item_id']}"
                f"/exercises/{recognition_row['exercise_type']}/answer",
                json={"answer": rec_answer, "id": "evt-recognition"},
            )
            assert rec_res.status_code == 201, rec_res.text
            rec_body = rec_res.json()
            assert rec_body["correct"] is True
            assert rec_body["correct_answer"] == rec_expected
            assert rec_body["event"]["metadata"]["skill_direction"] == "recognition"
            assert rec_body["event"]["metadata"]["exercise_version"] == EXERCISE_VERSION
            assert rec_body["learner_state"]["correct_count"] == 1
            assert rec_body["learner_state"]["attempt_count"] == 1
            assert rec_body["review_schedule"]["review_count"] == 1
            rec_direction = rec_body["learner_state"]["by_direction"]
            assert rec_direction["recognition"]["correct_count"] == 1
            assert rec_direction["recognition"]["attempt_count"] == 1
            assert "production" not in rec_direction

            prod_answer, prod_expected = _answer_payload(
                file_store,
                production_row["learning_item_id"],
                production_row["exercise_type"],
            )
            wrong = http.post(
                f"/api/tutor/items/{production_row['learning_item_id']}"
                f"/exercises/{production_row['exercise_type']}/answer",
                json={"answer": "wrong-answer", "id": "evt-production-wrong"},
            )
            assert wrong.status_code == 201, wrong.text
            wrong_body = wrong.json()
            assert wrong_body["correct"] is False
            assert wrong_body["correct_answer"] == prod_expected
            assert wrong_body["event"]["metadata"]["skill_direction"] == "production"
            assert wrong_body["learner_state"]["incorrect_count"] == 1
            assert wrong_body["review_schedule"]["lapse_count"] == 1
            prod_direction = wrong_body["learner_state"]["by_direction"]
            assert prod_direction["production"]["incorrect_count"] == 1
            if (
                production_row["learning_item_id"]
                == recognition_row["learning_item_id"]
            ):
                assert prod_direction["recognition"]["consecutive_correct"] == 1
            else:
                assert "recognition" not in prod_direction

            dup = http.post(
                f"/api/tutor/items/{recognition_row['learning_item_id']}"
                f"/exercises/{recognition_row['exercise_type']}/answer",
                json={"answer": rec_answer, "id": "evt-recognition"},
            )
            assert dup.status_code == 409
            rec_item_id = recognition_row["learning_item_id"]
            assert file_store.learner_states.get(rec_item_id).attempt_count == 1
            assert len(file_store.learning_events.list_by_item(rec_item_id)) == 1

            detail = http.get(f"/api/tutor/items/{expression_id}")
            assert detail.status_code == 200, detail.text
            assert detail.json()["item"]["id"] == expression_id
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
            assert listed["stratégie"]["status"] == "accepted"

            rec_detail = http.get(f"/api/tutor/items/{rec_item_id}")
            assert rec_detail.status_code == 200
            rec_loaded = rec_detail.json()
            assert rec_loaded["learner_state"]["correct_count"] == 1
            assert rec_loaded["learner_state"]["attempt_count"] == 1
            assert (
                rec_loaded["learner_state"]["by_direction"]["recognition"][
                    "correct_count"
                ]
                == 1
            )
            assert rec_loaded["review_schedule"]["review_count"] == 1
            events = reopened.learning_events.list_by_item(rec_item_id)
            assert len(events) == 1
            assert events[0].metadata["skill_direction"] == "recognition"
            assert events[0].metadata["exercise_version"] == EXERCISE_VERSION

            prod_detail = http.get(
                f"/api/tutor/items/{production_row['learning_item_id']}"
            )
            assert prod_detail.json()["learner_state"]["incorrect_count"] == 1
            assert (
                prod_detail.json()["learner_state"]["by_direction"]["production"][
                    "incorrect_count"
                ]
                == 1
            )
            assert prod_detail.json()["review_schedule"]["lapse_count"] == 1
            prod_events = reopened.learning_events.list_by_item(
                production_row["learning_item_id"]
            )
            assert len(prod_events) == 1
            assert prod_events[0].result == "incorrect"
            assert vocab_id in {row.id for row in reopened.learning_items.list()}
    finally:
        app.dependency_overrides.clear()
        reopened.engine.dispose()


def test_phase3_exercise_quality_fixture(client: TestClient, store: TutorSqliteStore):
    """deterministic 品質: 正解漏洩・distractor・正規化・cloze・grammar。"""
    lone = client.post(
        "/api/tutor/items",
        json={
            "item_type": "vocabulary",
            "canonical_form": "bonjour",
            "meaning_ja": "こんにちは",
        },
    )
    assert lone.status_code == 201, lone.text
    insufficient = client.get(
        f"/api/tutor/items/{lone.json()['item']['id']}/exercises/meaning_recognition"
    )
    assert insufficient.status_code == 422
    assert insufficient.json()["detail"]["skip_reason"] == "insufficient_distractors"

    source = _post_source(client)
    created = _extract(client, source["id"])["created"]
    by_form = _by_form(created)
    expression = _accept(client, by_form["se rendre compte de"]["id"])["item"]
    vocab = _accept(client, by_form["stratégie"]["id"])["item"]
    grammar = _accept(client, by_form["il fallait"]["id"])["item"]

    meaning = client.get(
        f"/api/tutor/items/{expression['id']}/exercises/meaning_recognition"
    )
    assert meaning.status_code == 200, meaning.text
    options = meaning.json()["options"]
    assert len(options) == len(set(options))
    assert "〜に気づく" in options
    assert "戦略" in options
    _assert_no_answer_leak(meaning.json())

    fr_to_ja = client.get(f"/api/tutor/items/{vocab['id']}/exercises/fr_to_ja")
    assert fr_to_ja.status_code == 422
    assert fr_to_ja.json()["detail"]["skip_reason"] == "requires_semantic_grading"

    accent = client.post(
        "/api/tutor/items",
        json={
            "item_type": "vocabulary",
            "canonical_form": "été",
            "meaning_ja": "夏",
        },
    )
    accent_id = accent.json()["item"]["id"]
    missing = client.post(
        f"/api/tutor/items/{accent_id}/exercises/ja_to_fr/answer",
        json={"answer": "ete"},
    )
    assert missing.status_code == 201
    assert missing.json()["correct"] is False

    apostrophe = client.post(
        "/api/tutor/items",
        json={
            "item_type": "expression",
            "canonical_form": "j'ai faim",
            "meaning_ja": "お腹が空いている",
        },
    )
    apostrophe_id = apostrophe.json()["item"]["id"]
    typographic = client.post(
        f"/api/tutor/items/{apostrophe_id}/exercises/ja_to_fr/answer",
        json={"answer": "J\u2019ai faim"},
    )
    assert typographic.status_code == 201
    assert typographic.json()["correct"] is True

    cloze = client.get(f"/api/tutor/items/{expression['id']}/exercises/cloze")
    assert cloze.status_code == 200
    generated = _generated(store, expression["id"], "cloze")
    assert generated.answer_key.expected_answers == ("rendu compte",)
    assert "rendu compte" not in cloze.json()["prompt"]

    grammar_choice = client.get(
        f"/api/tutor/items/{grammar['id']}/exercises/meaning_recognition"
    )
    assert grammar_choice.status_code == 422
    assert grammar_choice.json()["detail"]["skip_reason"] == (
        "generation_not_implemented"
    )
    grammar_cloze = client.get(f"/api/tutor/items/{grammar['id']}/exercises/cloze")
    assert grammar_cloze.status_code == 200
    _assert_no_answer_leak(grammar_cloze.json())


def test_phase3_conjugation_adapter_reuses_existing_domain(
    client: TestClient, store: TutorSqliteStore
):
    parler_source = _post_source(
        client, title="Parler", content=PARLER_CONTENT, metadata={}
    )
    parler_cand = _by_form(_extract(client, parler_source["id"])["created"])["parler"]
    parler = _accept(client, parler_cand["id"])["item"]
    assert parler["metadata"]["lemma"] == "parler"
    assert parler["metadata"]["tense"] == "présent"

    shown = client.get(f"/api/tutor/items/{parler['id']}/exercises/verb_conjugation")
    assert shown.status_code == 200, shown.text
    _assert_no_answer_leak(shown.json())
    generated = _generated(store, parler["id"], "verb_conjugation")
    expected = generated.answer_key.expected_answers[0]
    material_prompt = shown.json()["prompt"]
    assert "parler" in material_prompt
    assert "présent" in material_prompt
    domain_expected = get_correct_answer(
        generated.spec.metadata["verb"],
        generated.spec.metadata["tense"],
        generated.spec.metadata["pronoun"],
    )
    assert expected == domain_expected
    assert expected in CONJUGATIONS["parler"]["présent"].values()

    answered = client.post(
        f"/api/tutor/items/{parler['id']}/exercises/verb_conjugation/answer",
        json={"answer": expected},
    )
    assert answered.status_code == 201, answered.text
    body = answered.json()
    assert body["correct"] is True
    assert body["event"]["metadata"]["generation_method"] == "conjugation_adapter"
    assert body["event"]["metadata"]["skill_direction"] == "production"

    missing_tense_item = client.post(
        "/api/tutor/items",
        json={
            "item_type": "conjugation",
            "canonical_form": "être",
            "meaning_ja": "〜である",
            "metadata": {"lemma": "être"},
        },
    )
    assert missing_tense_item.status_code == 201, missing_tense_item.text
    missing_tense_id = missing_tense_item.json()["item"]["id"]
    missing_tense = client.get(
        f"/api/tutor/items/{missing_tense_id}/exercises/verb_conjugation"
    )
    assert missing_tense.status_code == 422
    assert missing_tense.json()["detail"]["skip_reason"] == "missing_conjugation_tense"

    main = _post_source(client)
    changer_cand = _by_form(_extract(client, main["id"])["created"])["changer"]
    changer = _accept(client, changer_cand["id"])["item"]
    unknown_lemma = client.get(
        f"/api/tutor/items/{changer['id']}/exercises/verb_conjugation"
    )
    assert unknown_lemma.status_code == 422
    assert unknown_lemma.json()["detail"]["skip_reason"] == "unknown_conjugation_lemma"
    changer_cloze = client.get(f"/api/tutor/items/{changer['id']}/exercises/cloze")
    assert changer_cloze.status_code == 200

    unknown_with_tense = client.post(
        "/api/tutor/items",
        json={
            "item_type": "conjugation",
            "canonical_form": "changer",
            "meaning_ja": "変える（時制付き）",
            "metadata": {"lemma": "changer", "tense": "présent"},
        },
    )
    assert unknown_with_tense.status_code == 201, unknown_with_tense.text
    unknown_id = unknown_with_tense.json()["item"]["id"]
    unknown_verb = client.get(
        f"/api/tutor/items/{unknown_id}/exercises/verb_conjugation"
    )
    assert unknown_verb.status_code == 422
    assert unknown_verb.json()["detail"]["skip_reason"] == "unknown_conjugation_lemma"

    session = client.post(
        "/api/tutor/practice/sessions",
        json={"item_ids": [parler["id"], changer["id"]], "question_count": 10},
    )
    assert session.status_code == 200, session.text
    types_by_item: dict[str, set[str]] = {}
    for row in session.json()["exercises"]:
        types_by_item.setdefault(row["learning_item_id"], set()).add(
            row["exercise_type"]
        )
    assert "verb_conjugation" in types_by_item[parler["id"]]
    assert "verb_conjugation" not in types_by_item.get(changer["id"], set())
    assert "cloze" in types_by_item.get(changer["id"], set())


def test_phase3_existing_quiz_and_tts_contracts_are_unchanged(
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


def test_phase3_does_not_expose_generic_exercise_collection():
    with TestClient(app) as http:
        spec = http.get("/openapi.json").json()
    paths = spec["paths"]
    assert "/api/tutor/items/{item_id}/exercises/{exercise_type}" in paths
    assert "/api/tutor/items/{item_id}/exercises/{exercise_type}/answer" in paths
    assert "/api/tutor/practice/sessions" in paths
    forbidden = (
        "/api/tutor/exercises",
        "/api/tutor/items/{item_id}/exercises",
        "/api/tutor/practice",
        "/api/tutor/recommendations",
        "/api/tutor/reviews/today",
    )
    for path in forbidden:
        assert path not in paths, path
