"""Phase 7 の品質制御を一本の学習フローで検証する（Issue #207）。

固定 clock の synthetic learner で、Source 追加から翌日の再 plan までを
HTTP API + SQLite でつなぐ。実 LLM とネットワークは使わない。
複数日の不変条件そのものは `test_tutor_phase7_quality.py` が持つ。
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import (
    get_learning_item_extractor,
    get_pdf_ingestion_service,
    get_source_learning_summary_service,
    get_subtitle_ingestion_service,
    get_today_learning_service,
    get_tutor_service,
    get_tutor_store,
)
from app.domain.admission_policy import PER_SOURCE_ADMISSION_CAP
from app.domain.context_selection import POLICY_VERSION as CONTEXT_POLICY_VERSION
from app.domain.context_selection import context_usages_from_events
from app.domain.daily_learning_plan import DEFAULT_MAX_NEW_COUNT, DEFAULT_PLAN_SIZE
from app.domain.exercise_generation import DEFAULT_GENERATION_SEED, generate_exercise
from app.domain.known_item_policy import decide_auto_skip
from app.domain.noun import NOUNS
from app.domain.tutor import SourceDocument, skill_direction_for_event
from app.domain.weakness_pattern import aggregate_weakness_patterns
from app.ingestion.pdf_parser import PypdfTextParser
from app.main import app
from app.repositories.sqlite import TutorSqliteStore
from app.services.extraction_prompt import EXTRACTION_VERSION
from app.services.extraction_schema import ExtractedCandidate, ExtractedEvidenceSpan
from app.services.extractors import ExtractorResult
from app.services.pdf_ingestion import PdfIngestionService
from app.services.source_learning_summary_service import (
    build_source_learning_summary_service,
)
from app.services.subtitle_ingestion import SubtitleIngestionService
from app.services.today_learning_service import build_today_learning_service
from app.services.tutor_service import build_tutor_service
from tests.pdf_samples import build_pdf, text_page

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
NEXT_DAY = NOW + timedelta(days=1)
PDF_AT = NOW - timedelta(days=20)
SRT_AT = NOW - timedelta(days=19)

FLOOD_WORDS = ("chat", "chien", "maison", "pain", "eau", "vent")
GARDEN_WORDS = ("jardin", "fleur")
BACKLOG_WORDS = (
    "porte",
    "fenetre",
    "table",
    "chaise",
    "lampe",
    "route",
    "ville",
    "gare",
    "train",
    "bus",
    "parc",
    "pont",
    "musee",
)
SRT_LIVRE = """\
1
00:00:12,000 --> 00:00:15,500
Voici un petit livre pour toi.
"""

PlanRow = tuple[str, str, str, str]
"""item_type, canonical_form, meaning_ja, fragment."""


def _word_plan(
    words: tuple[str, ...],
    item_type: str = "vocabulary",
) -> tuple[PlanRow, ...]:
    return tuple((item_type, word, f"意味-{word}", word) for word in words)


PLANS: dict[str, tuple[PlanRow, ...]] = {
    "pdf-livre": (("vocabulary", "livre", "本", "livre"),),
    "srt-livre": (("vocabulary", "livre", "本", "livre"),),
    "大量のメモ": _word_plan(FLOOD_WORDS),
    "庭のメモ": _word_plan(GARDEN_WORDS),
    "あいさつのメモ": (("vocabulary", "bonjour", "こんにちは", "bonjour"),),
    "文法のメモ": (
        ("grammar", "il faut", "する必要がある", "Il faut"),
        ("grammar", "il fallait", "する必要があった", "Il fallait"),
    ),
    "復習のメモ": _word_plan(BACKLOG_WORDS),
    "礼のメモ": (("vocabulary", "merci", "ありがとう", "merci"),),
    "果物のメモ": (("vocabulary", "orange", "オレンジ", "orange"),),
    "明日のメモ": (
        ("vocabulary", "soleil", "太陽", "soleil"),
        ("vocabulary", "lune", "月", "lune"),
    ),
}


class PlanExtractor:
    def __init__(self) -> None:
        self.seen: list[SourceDocument] = []

    def extract(self, source: SourceDocument) -> ExtractorResult:
        self.seen.append(source)
        rows: list[ExtractedCandidate] = []
        for item_type, form, meaning, fragment in PLANS[source.title]:
            start = source.content.index(fragment)
            rows.append(
                ExtractedCandidate(
                    item_type=item_type,
                    canonical_form=form,
                    meaning_ja=meaning,
                    evidence_span=ExtractedEvidenceSpan(
                        start=start,
                        end=start + len(fragment),
                    ),
                    confidence=0.9,
                )
            )
        return ExtractorResult(
            candidates=tuple(rows),
            provider="fake",
            model="fake-phase7",
            extraction_version=EXTRACTION_VERSION,
        )


@dataclass
class FrozenClock:
    now: datetime

    def __call__(self) -> datetime:
        return self.now


def _bind(
    store: TutorSqliteStore,
    clock: FrozenClock,
    extractor: PlanExtractor,
) -> None:
    app.dependency_overrides[get_tutor_store] = lambda: store
    app.dependency_overrides[get_tutor_service] = lambda: build_tutor_service(
        store, clock=clock
    )
    app.dependency_overrides[get_today_learning_service] = lambda: (
        build_today_learning_service(store, clock=clock)
    )
    app.dependency_overrides[get_source_learning_summary_service] = lambda: (
        build_source_learning_summary_service(store, clock=clock)
    )
    app.dependency_overrides[get_learning_item_extractor] = lambda: extractor
    app.dependency_overrides[get_pdf_ingestion_service] = lambda: PdfIngestionService(
        store.source_documents,
        PypdfTextParser(),
        clock=clock,
    )
    app.dependency_overrides[get_subtitle_ingestion_service] = lambda: (
        SubtitleIngestionService(store.source_documents, clock=clock)
    )


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError(f"network call: {args!r} {kwargs!r}")

    monkeypatch.setattr(socket, "getaddrinfo", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


@pytest.fixture
def store() -> TutorSqliteStore:
    return TutorSqliteStore.in_memory()


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(NOW)


@pytest.fixture
def client(store: TutorSqliteStore, clock: FrozenClock) -> Iterator[TestClient]:
    _bind(store, clock, PlanExtractor())
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _post_text(client: TestClient, title: str, content: str) -> dict:
    response = client.post(
        "/api/tutor/sources",
        json={"title": title, "content": content, "language": "fr"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _post_file(
    client: TestClient,
    path: str,
    filename: str,
    payload: bytes,
    media_type: str,
    title: str,
) -> dict:
    response = client.post(
        path,
        files={"file": (filename, payload, media_type)},
        data={"title": title},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["action"] == "create"
    return body["source"]


def _extract_and_accept(client: TestClient, source_id: str) -> dict[str, dict]:
    extracted = client.post(f"/api/tutor/sources/{source_id}/candidates/extract")
    assert extracted.status_code == 200, extracted.text
    created = extracted.json()["created"]
    assert created, extracted.text
    items: dict[str, dict] = {}
    for candidate in created:
        accepted = client.post(f"/api/tutor/candidates/{candidate['id']}/accept")
        assert accepted.status_code == 200, accepted.text
        item = accepted.json()["item"]
        items[item["canonical_form"]] = item
    return items


def _review(
    client: TestClient,
    item_id: str,
    exercise_type: str,
    result: str,
    occurred_at: datetime,
    event_id: str,
) -> None:
    response = client.post(
        f"/api/tutor/items/{item_id}/reviews",
        json={
            "exercise_type": exercise_type,
            "result": result,
            "occurred_at": occurred_at.isoformat(),
            "id": event_id,
        },
    )
    assert response.status_code == 201, response.text


def _today(client: TestClient, **params: int) -> dict:
    response = client.get("/api/tutor/today", params=params or None)
    assert response.status_code == 200, response.text
    return response.json()


def _summary(client: TestClient, source_id: str) -> dict:
    response = client.get(f"/api/tutor/sources/{source_id}/learning-summary")
    assert response.status_code == 200, response.text
    return response.json()


def _detail(client: TestClient, item_id: str) -> dict:
    response = client.get(f"/api/tutor/items/{item_id}")
    assert response.status_code == 200, response.text
    return response.json()


def _answer_generated(
    client: TestClient,
    store: TutorSqliteStore,
    item_id: str,
    exercise_type: str,
    *,
    event_id: str,
) -> dict:
    item = store.learning_items.get(item_id)
    assert item is not None
    sources: dict[str, SourceDocument] = {}
    for ref in item.source_refs:
        document = store.source_documents.get(ref.source_document_id)
        if document is not None:
            sources[document.id] = document
    generated = generate_exercise(
        item,
        exercise_type,
        pool=store.learning_items.list(),
        seed=DEFAULT_GENERATION_SEED,
        sources=sources,
        context_usages=context_usages_from_events(
            store.learning_events.list_by_item(item_id)
        ),
    )
    assert generated.exercise is not None, generated.skip_reason
    expected = generated.exercise.answer_key.expected_answers[0]
    response = client.post(
        f"/api/tutor/items/{item_id}/exercises/{exercise_type}/answer",
        json={"answer": expected, "id": event_id},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _direction_events(store: TutorSqliteStore, item_id: str, direction: str) -> list:
    return [
        event
        for event in store.learning_events.list_by_item(item_id)
        if skill_direction_for_event(event) == direction
    ]


def _new_entries(plan: dict) -> list[dict]:
    return [row for row in plan["entries"] if row["activity_kind"] == "new_practice"]


def _forms_from(plan: dict, title: str) -> list[str]:
    return [
        row["canonical_form"]
        for row in _new_entries(plan)
        if title in row["source_titles"]
    ]


def test_phase7_quality_controls_vertical_slice(tmp_path: Path) -> None:
    """Source 追加から翌日の再 plan まで、Phase 7 の制御を一連で確認する。"""

    db_path = tmp_path / "tutor-phase7.db"
    file_store = TutorSqliteStore(f"sqlite:///{db_path}")
    clock = FrozenClock(PDF_AT)
    extractor = PlanExtractor()
    _bind(file_store, clock, extractor)
    try:
        with TestClient(app) as http:
            pdf = _post_file(
                http,
                "/api/tutor/sources/ingest/pdf",
                "livre.pdf",
                build_pdf([text_page("Je lis un livre rouge dans la bibliotheque.")]),
                "application/pdf",
                "pdf-livre",
            )
            assert "livre" in pdf["content"]
            assert any(segment["page_number"] == 1 for segment in pdf["segments"])
            clock.now = SRT_AT
            srt = _post_file(
                http,
                "/api/tutor/sources/ingest/subtitle",
                "livre.srt",
                SRT_LIVRE.encode(),
                "application/x-subrip",
                "srt-livre",
            )
            assert "petit livre" in srt["content"]
            assert any(segment["start_seconds"] == 12.0 for segment in srt["segments"])

            clock.now = NOW
            texts = {
                "大量のメモ": " ".join(FLOOD_WORDS),
                "庭のメモ": " ".join(GARDEN_WORDS),
                "あいさつのメモ": "bonjour",
                "文法のメモ": "Il faut partir. Il fallait changer.",
                "復習のメモ": " ".join(BACKLOG_WORDS),
                "礼のメモ": "merci beaucoup",
                "果物のメモ": "une orange",
                "明日のメモ": "soleil lune",
            }
            sources = {"pdf-livre": pdf, "srt-livre": srt}
            for title, content in texts.items():
                sources[title] = _post_text(http, title, content)

            accepted: dict[str, dict] = {}
            for source in sources.values():
                accepted.update(_extract_and_accept(http, source["id"]))
            livre = accepted["livre"]
            assert {ref["source_document_id"] for ref in livre["source_refs"]} == {
                pdf["id"],
                srt["id"],
            }
            detail = _detail(http, livre["id"])
            assert len(detail["item"]["source_refs"]) == 2

            duplicate = http.post(
                "/api/tutor/items",
                json={
                    "item_type": "vocabulary",
                    "canonical_form": "Chat",
                    "meaning_ja": "猫の別表記",
                },
            )
            assert duplicate.status_code == 201, duplicate.text
            chat_alias_id = duplicate.json()["item"]["id"]
            assert duplicate.json()["item"]["canonical_form"] == "Chat"

            known = http.post(f"/api/tutor/items/{accepted['bonjour']['id']}/known")
            assert known.status_code == 200, known.text
            assert known.json()["explicit_known"] is True
            again = http.post(f"/api/tutor/items/{accepted['bonjour']['id']}/known")
            assert again.status_code == 200
            assert again.json()["explicit_known"] is True

            for form in ("il faut", "il fallait"):
                item_id = accepted[form]["id"]
                for index, days in enumerate((13, 11)):
                    _review(
                        http,
                        item_id,
                        "ja_to_fr",
                        "incorrect",
                        NOW - timedelta(days=days),
                        f"evt-{form}-prod-inc-{index}",
                    )
                for index, days in enumerate((10, 9)):
                    _review(
                        http,
                        item_id,
                        "ja_to_fr",
                        "correct",
                        NOW - timedelta(days=days),
                        f"evt-{form}-prod-ok-{index}",
                    )
                for index, days in enumerate((13, 11, 8, 4)):
                    _review(
                        http,
                        item_id,
                        "meaning_recognition",
                        "correct",
                        NOW - timedelta(days=days),
                        f"evt-{form}-rec-{index}",
                    )
            _review(
                http,
                livre["id"],
                "ja_to_fr",
                "incorrect",
                NOW - timedelta(days=12),
                "evt-livre-inc",
            )
            _review(
                http,
                livre["id"],
                "ja_to_fr",
                "correct",
                NOW - timedelta(days=6),
                "evt-livre-ok",
            )
            for index, days in enumerate((12, 10)):
                _review(
                    http,
                    accepted["merci"]["id"],
                    "ja_to_fr",
                    "correct",
                    NOW - timedelta(days=days),
                    f"evt-merci-{index}",
                )
            for word in BACKLOG_WORDS:
                _review(
                    http,
                    accepted[word]["id"],
                    "ja_to_fr",
                    "correct",
                    NOW - timedelta(days=4),
                    f"evt-backlog-{word}",
                )
            for index, days in enumerate((12, 9, 6, 3)):
                _review(
                    http,
                    accepted["orange"]["id"],
                    "meaning_recognition",
                    "correct",
                    NOW - timedelta(days=days),
                    f"evt-orange-{index}",
                )
            for form in ("soleil", "lune"):
                _review(
                    http,
                    accepted[form]["id"],
                    "ja_to_fr",
                    "correct",
                    NOW,
                    f"evt-{form}-tomorrow",
                )

            patterns = aggregate_weakness_patterns(
                file_store.learning_items.list(),
                [
                    event
                    for item in file_store.learning_items.list()
                    for event in file_store.learning_events.list_by_item(item.id)
                ],
                now=NOW,
            )
            grammar = next(
                row
                for row in patterns.weaknesses
                if row.dimension == "item_type" and row.value == "grammar"
            )
            assert grammar.by_direction["production"].is_weakness is True
            assert grammar.by_direction["recognition"].is_weakness is False
            assert all(
                "recognition" not in row.weak_directions for row in patterns.weaknesses
            )
            orange_id = accepted["orange"]["id"]
            assert (
                decide_auto_skip(
                    skill_direction="recognition",
                    events=_direction_events(file_store, orange_id, "recognition"),
                    now=NOW,
                ).skip_new
                is True
            )
            assert (
                decide_auto_skip(
                    skill_direction="production",
                    events=_direction_events(file_store, orange_id, "production"),
                    now=NOW,
                ).skip_new
                is False
            )

            pressured = _today(http)
            assert pressured["review_count"] == DEFAULT_PLAN_SIZE
            assert pressured["new_count"] == 0
            assert pressured["deferred_due_count"] == 7
            assert pressured["requested_count"] == DEFAULT_PLAN_SIZE
            assert "復習が溜まっている" in pressured["explanation_summary"]
            assert "新しい項目を入れられる枠が狭い" in pressured["explanation_summary"]
            assert all(row["activity_kind"] == "review" for row in pressured["entries"])
            assert "bonjour" not in {
                row["canonical_form"] for row in pressured["entries"]
            }
            flood_forms = set(FLOOD_WORDS)
            assert flood_forms.isdisjoint(
                {row["canonical_form"] for row in pressured["entries"]}
            )
            grammar_entries = [
                row
                for row in pressured["entries"]
                if row["canonical_form"] in {"il faut", "il fallait"}
            ]
            assert grammar_entries
            assert all(
                "PRODUCTION_PATTERN_WEAKNESS" in row["reason_codes"]
                for row in grammar_entries
            )
            assert all("文法" in row["explanation"] for row in grammar_entries)
            assert all(
                row["skill_direction"] == "production" for row in grammar_entries
            )
            livre_entry = next(
                row
                for row in pressured["entries"]
                if row["learning_item_id"] == livre["id"]
            )
            assert livre_entry["activity_kind"] == "review"
            assert livre_entry["skill_direction"] == "production"

            session = http.post("/api/tutor/today/sessions", json={"seed": "phase7"})
            assert session.status_code == 200, session.text
            body = session.json()
            assert body["new_count"] == 0
            assert body["review_count"] == DEFAULT_PLAN_SIZE
            livre_exercise = next(
                row
                for row in body["exercises"]
                if row["learning_item_id"] == livre["id"]
            )
            assert livre_exercise["exercise_type"] == "cloze"
            assert "rouge" in livre_exercise["prompt"]
            assert "petit" not in livre_exercise["prompt"]
            assert "expected" not in livre_exercise
            first = _answer_generated(
                http,
                file_store,
                livre["id"],
                "cloze",
                event_id="evt-livre-context-1",
            )
            assert first["correct"] is True
            assert first["event"]["metadata"]["source_document_id"] == pdf["id"]
            assert first["event"]["metadata"]["page_number"] == 1
            assert "start_seconds" not in first["event"]["metadata"]
            assert first["event"]["metadata"]["context_policy_version"] == (
                CONTEXT_POLICY_VERSION
            )
            evidence_start = first["event"]["metadata"]["evidence_start"]
            evidence_end = first["event"]["metadata"]["evidence_end"]
            assert pdf["content"][evidence_start:evidence_end] == "livre"

            rotated = http.get(f"/api/tutor/items/{livre['id']}/exercises/cloze")
            assert rotated.status_code == 200, rotated.text
            rotated_body = rotated.json()
            assert "petit" in rotated_body["prompt"]
            assert "rouge" not in rotated_body["prompt"]
            second = _answer_generated(
                http,
                file_store,
                livre["id"],
                "cloze",
                event_id="evt-livre-context-2",
            )
            assert second["correct"] is True
            assert second["event"]["metadata"]["source_document_id"] == srt["id"]
            assert second["event"]["metadata"]["start_seconds"] == 12.0
            assert "page_number" not in second["event"]["metadata"]
            srt_start = second["event"]["metadata"]["evidence_start"]
            srt_end = second["event"]["metadata"]["evidence_end"]
            assert srt["content"][srt_start:srt_end] == "livre"

            answered = {livre["id"]}
            for entry in body["entries"]:
                item_id = entry["learning_item_id"]
                if item_id in answered:
                    continue
                _answer_generated(
                    http,
                    file_store,
                    item_id,
                    entry["selected_exercise_type"],
                    event_id=f"evt-study-{item_id}",
                )
                answered.add(item_id)
            assert len(answered) == DEFAULT_PLAN_SIZE
            follow = http.post(
                "/api/tutor/today/sessions",
                json={"question_count": 20, "max_new_count": 0, "seed": "phase7-rest"},
            )
            assert follow.status_code == 200, follow.text
            rest = follow.json()
            assert rest["new_count"] == 0
            assert rest["review_count"] == 7
            for entry in rest["entries"]:
                _answer_generated(
                    http,
                    file_store,
                    entry["learning_item_id"],
                    entry["selected_exercise_type"],
                    event_id=f"evt-rest-{entry['learning_item_id']}",
                )

            pdf_summary = _summary(http, pdf["id"])
            srt_summary = _summary(http, srt["id"])
            livre_state = _detail(http, livre["id"])["learner_state"]
            livre_attempts = sum(
                row["attempt_count"] for row in livre_state["by_direction"].values()
            )
            for summary in (pdf_summary, srt_summary):
                assert summary["accepted_item_count"] == 1
                assert summary["started_item_count"] == 1
                assert summary["attempts"] == livre_attempts
                assert summary["production"]["attempt_count"] > 0
                assert summary["recognition"]["attempt_count"] == 0
            assert pdf_summary["attempts"] == srt_summary["attempts"]
            flood_summary = _summary(http, sources["大量のメモ"]["id"])
            assert flood_summary["accepted_item_count"] == len(FLOOD_WORDS)
            assert flood_summary["unseen_item_count"] == len(FLOOD_WORDS)
            assert flood_summary["started_item_count"] == 0
            known_summary = _summary(http, sources["あいさつのメモ"]["id"])
            assert known_summary["accepted_item_count"] == 1
            assert known_summary["mastered_or_known_count"] == 1
            assert known_summary["unseen_item_count"] == 0

            clock.now = NEXT_DAY
            recovered = _today(http)
            assert recovered["requested_count"] == DEFAULT_PLAN_SIZE
            assert recovered["review_count"] == 2
            assert recovered["new_count"] == DEFAULT_MAX_NEW_COUNT
            assert {row["canonical_form"] for row in recovered["entries"][:2]} == {
                "soleil",
                "lune",
            }
            assert recovered["deferred_due_count"] == 0
            assert "減らしました" not in recovered["explanation_summary"]
            seen_new = False
            for row in recovered["entries"]:
                if row["activity_kind"] == "new_practice":
                    seen_new = True
                else:
                    assert row["activity_kind"] == "review"
                    assert not seen_new
            assert "bonjour" not in {
                row["canonical_form"] for row in recovered["entries"]
            }
            assert len(_forms_from(recovered, "大量のメモ")) <= PER_SOURCE_ADMISSION_CAP

            wide = _today(http, question_count=20, max_new_count=8)
            assert len(_forms_from(wide, "大量のメモ")) <= PER_SOURCE_ADMISSION_CAP
            assert "bonjour" not in {row["canonical_form"] for row in wide["entries"]}
            new_forms = [row["canonical_form"] for row in _new_entries(wide)]
            assert not ({"chat", "Chat"} <= set(new_forms))
            seen_new = False
            for row in wide["entries"]:
                if row["activity_kind"] == "new_practice":
                    seen_new = True
                else:
                    assert not seen_new

            leave_unseen = set(FLOOD_WORDS) | set(GARDEN_WORDS) | {"bonjour"}
            for form, item in accepted.items():
                if form in leave_unseen:
                    continue
                marked = http.post(f"/api/tutor/items/{item['id']}/known")
                assert marked.status_code == 200, marked.text
            marked_alias = http.post(f"/api/tutor/items/{chat_alias_id}/known")
            assert marked_alias.status_code == 200, marked_alias.text
            capped = _today(http, question_count=20, max_new_count=8)
            assert len(_forms_from(capped, "大量のメモ")) == PER_SOURCE_ADMISSION_CAP
            assert len(_forms_from(capped, "庭のメモ")) == len(GARDEN_WORDS)
            assert {row["canonical_form"] for row in capped["entries"][:2]} == {
                "soleil",
                "lune",
            }

            for form in (*FLOOD_WORDS, *GARDEN_WORDS):
                parked = http.post(f"/api/tutor/items/{accepted[form]['id']}/known")
                assert parked.status_code == 200, parked.text
            undone = http.post(
                f"/api/tutor/items/{accepted['bonjour']['id']}/known/undo"
            )
            assert undone.status_code == 200, undone.text
            assert undone.json()["explicit_known"] is False
            restored = _today(http, question_count=20, max_new_count=8)
            assert [row["canonical_form"] for row in _new_entries(restored)] == [
                "bonjour"
            ]
            remarked = http.post(f"/api/tutor/items/{accepted['bonjour']['id']}/known")
            assert remarked.json()["explicit_known"] is True
            hidden = _today(http, question_count=20, max_new_count=8)
            assert _new_entries(hidden) == []
            assert {row["canonical_form"] for row in hidden["entries"]} == {
                "soleil",
                "lune",
            }

            orange_undo = http.post(
                f"/api/tutor/items/{accepted['orange']['id']}/known/undo"
            )
            assert orange_undo.status_code == 200, orange_undo.text
            orange_plan = _today(http, question_count=20, max_new_count=8)
            assert [row["canonical_form"] for row in _new_entries(orange_plan)] == [
                "orange"
            ]
            assert orange_plan["entries"][-1]["skill_direction"] == "production"
            orange_again = http.post(
                f"/api/tutor/items/{accepted['orange']['id']}/known"
            )
            assert orange_again.status_code == 200, orange_again.text

            salut = http.post(
                "/api/tutor/items",
                json={
                    "item_type": "vocabulary",
                    "canonical_form": "salut",
                    "meaning_ja": "やあ",
                },
            )
            assert salut.status_code == 201, salut.text
            salut_id = salut.json()["item"]["id"]
            _review(
                http,
                salut_id,
                "meaning_recognition",
                "correct",
                NEXT_DAY,
                "evt-salut-once",
            )
            assert (
                decide_auto_skip(
                    skill_direction="recognition",
                    events=_direction_events(file_store, salut_id, "recognition"),
                    now=NEXT_DAY,
                ).skip_new
                is False
            )
            assert (
                decide_auto_skip(
                    skill_direction="production",
                    events=_direction_events(file_store, salut_id, "production"),
                    now=NEXT_DAY,
                ).skip_new
                is False
            )
            after_one = _today(http, question_count=20, max_new_count=8)
            assert [row["canonical_form"] for row in _new_entries(after_one)] == [
                "salut"
            ]
            assert after_one["entries"][-1]["skill_direction"] == "production"
            assert after_one["review_count"] == 2
            assert (
                http.get(f"/api/tutor/items/{salut_id}/known").json()["explicit_known"]
                is False
            )

            kept_summary = _summary(http, pdf["id"])
            assert kept_summary["accepted_item_count"] == 1
            assert kept_summary["attempts"] == livre_attempts
    finally:
        app.dependency_overrides.clear()
        file_store.engine.dispose()

    reopened = TutorSqliteStore(f"sqlite:///{db_path}")
    _bind(reopened, FrozenClock(NEXT_DAY), PlanExtractor())
    try:
        with TestClient(app) as http:
            loaded = _detail(http, livre["id"])
            assert len(loaded["item"]["source_refs"]) == 2
            bonjour_id = accepted["bonjour"]["id"]
            known_state = http.get(f"/api/tutor/items/{bonjour_id}/known")
            assert known_state.status_code == 200
            assert known_state.json()["explicit_known"] is True
            events = {
                event.id: event
                for event in reopened.learning_events.list_by_item(livre["id"])
            }
            assert events["evt-livre-context-1"].metadata["page_number"] == 1
            assert events["evt-livre-context-2"].metadata["start_seconds"] == 12.0
            replan = _today(http, question_count=20, max_new_count=8)
            assert [row["canonical_form"] for row in _new_entries(replan)] == ["salut"]
            assert "bonjour" not in {row["canonical_form"] for row in replan["entries"]}
            assert replan["entries"][0]["activity_kind"] == "review"
    finally:
        app.dependency_overrides.clear()
        reopened.engine.dispose()


def test_phase7_quiz_practice_review_today_and_tts_remain(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    created = client.post(
        "/api/tutor/items",
        json={
            "item_type": "vocabulary",
            "canonical_form": "livre",
            "meaning_ja": "本",
        },
    )
    assert created.status_code == 201, created.text

    question = client.get("/api/questions/next")
    assert question.status_code == 200
    assert {"verb", "tense", "pronoun"} <= set(question.json())
    checked = client.post(
        "/api/answers/check",
        json={"verb": "être", "tense": "présent", "pronoun": "je", "answer": "suis"},
    )
    assert checked.status_code == 200
    assert checked.json()["correct"] is True

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
    article_check = client.post(
        "/api/nouns/article/check",
        json={"noun": "livre", "answer": "un livre"},
    )
    assert article_check.status_code == 200
    assert article_check.json()["correct"] is True

    tts = client.get("/api/tts/speak?text=bonjour")
    assert tts.status_code == 503
    assert "OPENAI_API_KEY" in tts.json()["detail"]

    practice = client.post("/api/tutor/practice/sessions", json={"question_count": 5})
    assert practice.status_code == 200, practice.text
    review = client.post("/api/tutor/review/sessions", json={"question_count": 5})
    assert review.status_code == 200, review.text
    queue = client.get("/api/tutor/reviews/queue")
    assert queue.status_code == 200
    today = client.get("/api/tutor/today")
    assert today.status_code == 200, today.text
    assert client.get("/api/tutor/sources").status_code == 200
