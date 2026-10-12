"""外部 Source → Candidate → 今日の学習の vertical slice（Issue #196 / Phase 6）。

Web / PDF / SRT / 音声 / 会話 / テキストを同じ SourceDocument に正規化し、
fake extractor で採用した LearningItem が既存の ranking と Today Session に
流れることを HTTP API + SQLite で一本につなぐ。実ネットワーク、外部の
文字起こし API、実 LLM は使わない。失敗した取り込みは Source を残さない。
"""

from __future__ import annotations

import ast
import inspect
import json
import socket
import struct
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api.deps import (
    get_learning_item_extractor,
    get_transcription_provider,
    get_tutor_store,
    get_web_page_fetcher,
    get_youtube_transcript_provider,
)
from app.domain.exercise import tokenize_canonical_form
from app.domain.exercise_generation import DEFAULT_GENERATION_SEED, generate_exercise
from app.domain.noun import NOUNS
from app.domain.recommendation_ranking import rank_recommendations
from app.domain.recommendation_signal import extract_recommendation_signal
from app.domain.source_ingestion import (
    INGESTION_VERSION,
    SourceSegment,
    content_digest,
    segment_for_span,
)
from app.domain.tutor import LearningItem, SourceDocument
from app.ingestion.audio import AudioPayload, TranscriptionResult, TranscriptSegment
from app.ingestion.audio_errors import (
    MSG_PROVIDER,
    AudioIngestErrorCode,
    AudioIngestionError,
)
from app.ingestion.errors import WebFetchErrorCode, WebUrlIngestionError
from app.ingestion.fetcher import FetchedWebPage, GuardedWebFetcher, HttpExchange
from app.ingestion.pdf_text import MAX_PDF_PAGES
from app.ingestion.text_file import MAX_TEXT_FILE_BYTES
from app.main import app
from app.repositories.sqlite import TutorSqliteStore
from app.services.extraction_prompt import EXTRACTION_VERSION
from app.services.extraction_schema import ExtractedCandidate, ExtractedEvidenceSpan
from app.services.extractors import ExtractorResult
from tests.pdf_samples import build_pdf, lesson_pdf, text_page

PUBLIC_URL = "https://example.com/articles/bibliotheque"
WEB_HTML = """<!DOCTYPE html>
<html lang="fr">
<head><meta charset="utf-8"><title>Page</title></head>
<body>
<nav>Accueil secret-nav</nav>
<script>var secret = "secret-script";</script>
<article>
<h1>Page</h1>
<p>La bibliothèque ouvre à neuf heures.</p>
</article>
</body>
</html>
"""
SRT_GARE = """\
1
00:00:02,000 --> 00:00:05,000
Le train est à la gare.
"""
TEXT_LANGUE = "Cette langue est vivante.\n\nLa bibliothèque ouvre."
AUDIO_TEXT = "Le livre est sur la table."
AUDIO_MARKER = b"RAW-AUDIO-MARKER"
CONVERSATION = {
    "messages": [
        {
            "speaker": "user",
            "text": "こんにちは",
            "timestamp": "2026-04-01T12:00:00+09:00",
        },
        {
            "speaker": "partner",
            "text": "Le musée est ouvert.",
            "timestamp": "2026-04-01T03:00:01Z",
        },
    ]
}

PLANS: dict[str, tuple[tuple[str, str], ...]] = {
    "web-biblio": (("bibliothèque", "図書館"),),
    "pdf-lesson": (("café", "コーヒー"), ("déjeuner", "朝食")),
    "srt-gare": (("gare", "駅"),),
    "audio-livre": (("livre", "本"),),
    "conversation-musee": (("musée", "美術館"),),
    "text-langue": (("langue", "言語"), ("bibliothèque", "図書館")),
}


class _PageFetcher:
    def __init__(self, pages: list[FetchedWebPage]) -> None:
        self.pages = pages
        self.urls: list[str] = []

    def fetch(self, url: str, *, fetched_at: datetime) -> FetchedWebPage:
        self.urls.append(url)
        return self.pages[0]


class _ExplodingResolver:
    def resolve(self, hostname: str, port: int) -> tuple[str, ...]:
        raise AssertionError(f"resolved {hostname}")


class _ExplodingTransport:
    def __init__(self) -> None:
        self.calls = 0

    def exchange(self, request: object) -> HttpExchange:
        self.calls += 1
        raise AssertionError("exchanged")


class _FailingFetcher:
    def __init__(self) -> None:
        self.calls = 0

    def fetch(self, url: str, *, fetched_at: datetime) -> FetchedWebPage:
        self.calls += 1
        raise WebUrlIngestionError(
            "ページの取得に失敗した",
            code=WebFetchErrorCode.upstream_error,
        )


class _AddressResolver:
    def resolve(self, hostname: str, port: int) -> tuple[str, ...]:
        return ("8.8.8.8",)


class _ScriptedTransport:
    def __init__(self, exchanges: list[HttpExchange]) -> None:
        self.exchanges = list(exchanges)
        self.calls: list[object] = []

    def exchange(self, request: object) -> HttpExchange:
        self.calls.append(request)
        return self.exchanges.pop(0)


class _EmptyYoutube:
    provider_name = "fake"
    provider_version = "0"

    def list_tracks(self, video_id: str) -> tuple[object, ...]:
        return ()

    def fetch_track(self, video_id: str, track: object) -> tuple[object, ...]:
        raise AssertionError("transcript fetch")


class _TranscriptionProvider:
    provider_name = "fake"
    model = "fake-1"
    transcription_version = "fake-transcript-v1"

    def __init__(
        self,
        result: TranscriptionResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls = 0

    def transcribe(
        self, audio: AudioPayload, language_hint: str
    ) -> TranscriptionResult:
        self.calls += 1
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


class PlanExtractor:
    def __init__(self) -> None:
        self.seen: list[SourceDocument] = []

    def extract(self, source: SourceDocument) -> ExtractorResult:
        self.seen.append(source)
        rows: list[ExtractedCandidate] = []
        for fragment, meaning in PLANS[source.title]:
            start = source.content.index(fragment)
            rows.append(
                ExtractedCandidate(
                    item_type="vocabulary",
                    canonical_form=fragment,
                    meaning_ja=meaning,
                    evidence_span=ExtractedEvidenceSpan(
                        start=start, end=start + len(fragment)
                    ),
                    confidence=0.9,
                )
            )
        return ExtractorResult(
            candidates=tuple(rows),
            provider="fake",
            model="fake",
            extraction_version=EXTRACTION_VERSION,
        )


def _html_page() -> FetchedWebPage:
    return FetchedWebPage(
        requested_url=PUBLIC_URL,
        final_url=PUBLIC_URL,
        status_code=200,
        media_type="text/html",
        content_type_header="text/html; charset=utf-8",
        body=WEB_HTML.encode(),
        fetched_at=datetime(2026, 10, 12, tzinfo=UTC),
    )


def _wav() -> bytes:
    sample_rate = 8
    channels = 1
    bits = 16
    block_align = channels * bits // 8
    byte_rate = sample_rate * block_align
    data = AUDIO_MARKER + bytes(byte_rate - len(AUDIO_MARKER))
    fmt = struct.pack("<HHIIHH", 1, channels, sample_rate, byte_rate, block_align, bits)
    fmt_chunk = b"fmt " + len(fmt).to_bytes(4, "little") + fmt
    data_chunk = b"data" + len(data).to_bytes(4, "little") + data
    body = b"WAVE" + fmt_chunk + data_chunk
    return b"RIFF" + len(body).to_bytes(4, "little") + body


def _audio_result() -> TranscriptionResult:
    return TranscriptionResult(
        text="ignored-provider-text",
        segments=(TranscriptSegment(AUDIO_TEXT, 1.0, 3.5),),
        detected_language="french",
    )


def _bind(
    store: TutorSqliteStore,
    extractor: PlanExtractor,
    fetcher: object,
    audio: _TranscriptionProvider,
) -> None:
    app.dependency_overrides[get_tutor_store] = lambda: store
    app.dependency_overrides[get_learning_item_extractor] = lambda: extractor
    app.dependency_overrides[get_web_page_fetcher] = lambda: fetcher
    app.dependency_overrides[get_transcription_provider] = lambda: audio


def _segments(document: dict) -> list[SourceSegment]:
    return [SourceSegment.model_validate(row) for row in document["segments"]]


def _assert_segment_ranges(document: dict) -> None:
    content = document["content"]
    last = 0
    for segment in _segments(document):
        assert last <= segment.normalized_start < segment.normalized_end
        assert segment.normalized_end <= len(content)
        assert content[segment.normalized_start : segment.normalized_end]
        last = segment.normalized_end


def _mapped(document: dict, fragment: str) -> SourceSegment:
    content = document["content"]
    start = content.index(fragment)
    end = start + len(fragment)
    assert content[start:end] == fragment
    return segment_for_span(_segments(document), start=start, end=end)


def _post_file(
    client: TestClient,
    path: str,
    filename: str,
    payload: bytes,
    media_type: str,
    *,
    title: str | None = None,
) -> dict:
    data = {"title": title} if title is not None else None
    response = client.post(
        path,
        files={"file": (filename, payload, media_type)},
        data=data,
    )
    return {
        "status": response.status_code,
        "body": response.json(),
        "text": response.text,
    }


def _source_body(posted: dict) -> dict:
    assert posted["status"] == 201, posted["text"]
    assert posted["body"]["action"] == "create"
    return posted["body"]["source"]


def _detail_code(response_body: dict) -> str:
    detail = response_body["detail"]
    assert isinstance(detail, dict)
    return str(detail["code"])


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
def client(store: TutorSqliteStore) -> Iterator[TestClient]:
    _bind(
        store,
        PlanExtractor(),
        GuardedWebFetcher(_ExplodingResolver(), _ExplodingTransport()),
        _TranscriptionProvider(),
    )
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


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


def _answer(
    client: TestClient,
    store: TutorSqliteStore,
    item_id: str,
    exercise_type: str,
    *,
    event_id: str,
) -> dict:
    generated = _generated(store, item_id, exercise_type)
    expected = generated.answer_key.expected_answers[0]
    if generated.spec.response_kind == "reconstruction":
        payload_answer: str | list[str] = list(tokenize_canonical_form(expected))
    else:
        payload_answer = expected
    response = client.post(
        f"/api/tutor/items/{item_id}/exercises/{exercise_type}/answer",
        json={"answer": payload_answer, "id": event_id},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_phase6_external_source_to_today_learning_vertical_slice(tmp_path) -> None:
    """必須 fixture A〜E とテキストが、同じ LearningItem 経路で今日の学習に入る。"""

    db_path = tmp_path / "tutor-phase6.db"
    file_store = TutorSqliteStore(f"sqlite:///{db_path}")
    extractor = PlanExtractor()
    fetcher = _PageFetcher([_html_page()])
    audio = _TranscriptionProvider(result=_audio_result())
    _bind(file_store, extractor, fetcher, audio)
    try:
        with TestClient(app) as http:
            sources = _ingest_fixtures(http, fetcher, audio)
            _assert_provenance(sources)
            created = _extract_all(http, extractor, sources)
            item_ids = _accept_all(http, created, sources)
            _assert_ranking_uses_the_same_items(file_store, item_ids)
            _assert_today_flow(http, file_store, item_ids)
            manual = http.post(
                "/api/tutor/sources",
                json={"title": "手入力", "content": "ligne\r\n\r\n\r\nsuite"},
            )
            assert manual.status_code == 201
            assert manual.json()["content"] == "ligne\r\n\r\n\r\nsuite"
            assert manual.json()["source_type"] == "manual_text"
    finally:
        app.dependency_overrides.clear()
        file_store.engine.dispose()

    reopened = TutorSqliteStore(f"sqlite:///{db_path}")
    _bind(
        reopened,
        PlanExtractor(),
        GuardedWebFetcher(_ExplodingResolver(), _ExplodingTransport()),
        _TranscriptionProvider(),
    )
    try:
        with TestClient(app) as http:
            _assert_reopened(http, reopened, sources, item_ids)
    finally:
        app.dependency_overrides.clear()
        reopened.engine.dispose()


def _ingest_fixtures(
    http: TestClient, fetcher: _PageFetcher, audio: _TranscriptionProvider
) -> dict[str, dict]:
    web = http.post(
        "/api/tutor/sources/ingest/url",
        json={"url": PUBLIC_URL, "title": "web-biblio"},
    )
    assert web.status_code == 201, web.text
    web_source = web.json()["source"]
    again = http.post(
        "/api/tutor/sources/ingest/url",
        json={"url": PUBLIC_URL, "title": "web-biblio"},
    )
    assert again.status_code == 200
    assert again.json()["action"] == "reuse"
    assert again.json()["source"]["id"] == web_source["id"]
    assert again.json()["source"]["content_hash"] == web_source["content_hash"]
    assert fetcher.urls == [PUBLIC_URL, PUBLIC_URL]

    pdf = _source_body(
        _post_file(
            http,
            "/api/tutor/sources/ingest/pdf",
            "leçon.pdf",
            lesson_pdf(),
            "application/pdf",
            title="pdf-lesson",
        )
    )
    srt = _source_body(
        _post_file(
            http,
            "/api/tutor/sources/ingest/subtitle",
            "gare.srt",
            SRT_GARE.encode(),
            "application/x-subrip",
            title="srt-gare",
        )
    )
    srt_again = _post_file(
        http,
        "/api/tutor/sources/ingest/subtitle",
        "gare.srt",
        SRT_GARE.encode(),
        "application/x-subrip",
        title="srt-gare",
    )
    assert srt_again["status"] == 200
    assert srt_again["body"]["source"]["id"] == srt["id"]
    assert srt_again["body"]["source"]["content_hash"] == srt["content_hash"]

    audio_source = _source_body(
        _post_file(
            http,
            "/api/tutor/sources/ingest/audio",
            "livre.wav",
            _wav(),
            "audio/wav",
            title="audio-livre",
        )
    )
    assert audio.calls == 1
    conversation = _source_body(
        _post_file(
            http,
            "/api/tutor/sources/ingest/conversation",
            "dialogue.json",
            json.dumps(CONVERSATION, ensure_ascii=False).encode(),
            "application/json",
            title="conversation-musee",
        )
    )
    text = _source_body(
        _post_file(
            http,
            "/api/tutor/sources/ingest/text-file",
            "langue.txt",
            TEXT_LANGUE.encode(),
            "text/plain",
            title="text-langue",
        )
    )
    return {
        "web": web_source,
        "pdf": pdf,
        "srt": srt,
        "audio": audio_source,
        "conversation": conversation,
        "text": text,
    }


def _assert_provenance(sources: dict[str, dict]) -> None:
    expected_types = {
        "web": "web_url",
        "pdf": "pdf",
        "srt": "subtitle",
        "audio": "audio_transcript",
        "conversation": "conversation_log",
        "text": "conversation_log",
    }
    for key, source_type in expected_types.items():
        document = sources[key]
        assert document["source_type"] == source_type
        assert document["title"] in PLANS
        assert document["content_hash"] == content_digest(document["content"])
        assert document["ingestion_version"] == INGESTION_VERSION
        assert document["provenance"]["ingestion_version"] == INGESTION_VERSION
        _assert_segment_ranges(document)
        dumped = json.dumps(document, ensure_ascii=False)
        assert "secret-nav" not in document["content"]
        assert "secret-script" not in document["content"]
        assert "%PDF" not in document["content"]
        assert "RAW-AUDIO-MARKER" not in dumped
        assert "ignored-provider-text" not in document["content"]
        assert "raw_html" not in document["metadata"]
        assert "raw_pdf" not in document["metadata"]
        assert "raw_audio" not in document["metadata"]
        assert "email" not in document["metadata"]

    web = sources["web"]
    assert "bibliothèque" in web["content"]
    assert "<" not in web["content"]
    assert web["provenance"]["canonical_locator"] == PUBLIC_URL
    web_span = _mapped(web, "bibliothèque")
    assert web_span.page_number is None
    assert web_span.start_seconds is None
    assert web_span.speaker is None

    pdf = sources["pdf"]
    assert [segment.page_number for segment in _segments(pdf)] == [1, 2, 3]
    assert _mapped(pdf, "café").page_number == 1
    assert _mapped(pdf, "déjeuner").page_number == 2
    assert pdf["provenance"]["filename"] == "leçon.pdf"

    srt = sources["srt"]
    gare = _mapped(srt, "gare")
    assert gare.start_seconds == 2.0
    assert gare.end_seconds == 5.0
    assert gare.page_number is None

    audio = sources["audio"]
    livre = _mapped(audio, "livre")
    assert livre.start_seconds == 1.0
    assert livre.end_seconds == 3.5
    assert audio["content"] == AUDIO_TEXT
    assert audio["provenance"]["filename"] == "livre.wav"

    conversation = sources["conversation"]
    assert conversation["content"] == "こんにちは\n\nLe musée est ouvert."
    museum = _mapped(conversation, "musée")
    assert museum.speaker == "partner"
    assert museum.timestamp == "2026-04-01T03:00:01Z"
    assert museum.start_seconds is None
    assert "こんにちは" in conversation["content"]

    text = sources["text"]
    assert text["content"] == TEXT_LANGUE
    assert _mapped(text, "langue").speaker is None
    assert _mapped(text, "bibliothèque").page_number is None


def _extract_all(
    http: TestClient, extractor: PlanExtractor, sources: dict[str, dict]
) -> list[dict]:
    created: list[dict] = []
    for document in sources.values():
        response = http.post(f"/api/tutor/sources/{document['id']}/candidates/extract")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["extraction_version"] == EXTRACTION_VERSION
        created.extend(body["created"])
        for row in body["created"]:
            assert row["evidence_text"] == row["canonical_form"]
            assert "provider" not in row
            assert "source_type" not in row
    seen = {source.id: source.content for source in extractor.seen}
    assert set(seen) == {document["id"] for document in sources.values()}
    for document in sources.values():
        assert seen[document["id"]] == document["content"]
    keys = {frozenset(row) for row in created}
    assert len(keys) == 1
    return created


def _accept_all(
    http: TestClient, created: list[dict], sources: dict[str, dict]
) -> dict[str, str]:
    item_ids: dict[str, str] = {}
    for row in created:
        response = http.post(f"/api/tutor/candidates/{row['id']}/accept")
        assert response.status_code == 200, response.text
        body = response.json()
        form = body["item"]["canonical_form"]
        assert "source_type" not in body["item"]
        assert body["item"]["item_type"] == "vocabulary"
        if form in item_ids:
            assert body["merged"] is True
            assert body["item"]["id"] == item_ids[form]
        else:
            assert body["merged"] is False
            item_ids[form] = body["item"]["id"]
    assert set(item_ids) == {
        "bibliothèque",
        "café",
        "déjeuner",
        "gare",
        "livre",
        "musée",
        "langue",
    }
    detail = http.get(f"/api/tutor/items/{item_ids['bibliothèque']}")
    assert detail.status_code == 200, detail.text
    refs = detail.json()["item"]["source_refs"]
    assert {ref["source_document_id"] for ref in refs} == {
        sources["web"]["id"],
        sources["text"]["id"],
    }
    return item_ids


def _assert_ranking_uses_the_same_items(
    store: TutorSqliteStore, item_ids: dict[str, str]
) -> None:
    now = datetime.now(UTC)
    sources = {document.id: document for document in store.source_documents.list()}
    snapshots = [
        extract_recommendation_signal(item, sources_by_id=sources, now=now)
        for item in store.learning_items.list()
    ]
    ranked = rank_recommendations(snapshots)
    new_ids = {
        row.learning_item_id
        for row in ranked
        if row.activity_kind == "new_practice" and row.skill_direction == "recognition"
    }
    assert new_ids == set(item_ids.values())
    for snapshot in snapshots:
        assert snapshot.source_recency_days is not None
        assert not hasattr(snapshot, "source_type")


def _assert_today_flow(
    http: TestClient, store: TutorSqliteStore, item_ids: dict[str, str]
) -> None:
    params = {"question_count": 10, "max_new_count": 7}
    plan = http.get("/api/tutor/today", params=params)
    assert plan.status_code == 200, plan.text
    body = plan.json()
    assert body["review_count"] == 0
    assert body["new_count"] == 7
    assert {row["canonical_form"] for row in body["entries"]} == set(item_ids)
    assert all(row["activity_kind"] == "new_practice" for row in body["entries"])
    assert all("source_type" not in row for row in body["entries"])
    assert all("total_score" not in row for row in body["entries"])
    assert "RECENT_SOURCE" in body["entries"][0]["reason_codes"]

    session = http.post("/api/tutor/today/sessions", json=params)
    assert session.status_code == 200, session.text
    session_body = session.json()
    assert session_body["new_count"] == 7
    assert session_body["review_count"] == 0
    exercises = session_body["exercises"]
    assert len(exercises) == 7
    for exercise in exercises:
        assert "correct_answer" not in exercise
        assert "expected" not in exercise
    livre = next(
        row for row in exercises if row["learning_item_id"] == item_ids["livre"]
    )
    assert livre["skill_direction"] == "recognition"
    answered = _answer(
        http,
        store,
        item_ids["livre"],
        livre["exercise_type"],
        event_id="evt-phase6-livre",
    )
    assert answered["correct"] is True
    assert answered["event"]["metadata"]["skill_direction"] == "recognition"
    assert (
        answered["learner_state"]["by_direction"]["recognition"]["attempt_count"] == 1
    )
    assert answered["review_schedule"]["skill_direction"] == "recognition"
    assert answered["review_schedule"]["due_at"] > body["generated_at"]

    next_plan = http.get("/api/tutor/today", params=params)
    assert next_plan.status_code == 200, next_plan.text
    assert not any(
        row["learning_item_id"] == item_ids["livre"]
        and row["skill_direction"] == "recognition"
        and row["activity_kind"] == "new_practice"
        for row in next_plan.json()["entries"]
    )


def _assert_reopened(
    http: TestClient,
    store: TutorSqliteStore,
    sources: dict[str, dict],
    item_ids: dict[str, str],
) -> None:
    for key in ("pdf", "srt", "audio", "conversation", "web", "text"):
        loaded = http.get(f"/api/tutor/sources/{sources[key]['id']}")
        assert loaded.status_code == 200, loaded.text
        document = loaded.json()
        assert document["content"] == sources[key]["content"]
        assert document["content_hash"] == sources[key]["content_hash"]
        assert document["segments"] == sources[key]["segments"]
        assert document["provenance"] == sources[key]["provenance"]
    item = http.get(f"/api/tutor/items/{item_ids['livre']}")
    assert item.status_code == 200, item.text
    detail = item.json()
    assert detail["learner_state"]["by_direction"]["recognition"]["attempt_count"] == 1
    directions = {row["skill_direction"] for row in detail["review_schedules"]}
    assert directions == {"recognition"}
    events = store.learning_events.list_by_item(item_ids["livre"])
    assert [event.id for event in events] == ["evt-phase6-livre"]
    persisted = {item.canonical_form for item in store.learning_items.list()}
    assert set(item_ids) <= persisted


def test_phase6_failed_ingestion_does_not_persist_or_damage_history(
    client: TestClient, store: TutorSqliteStore
) -> None:
    """失敗した取り込みは不完全な Source を残さず、既存の学習履歴も壊さない。"""

    manual = client.post(
        "/api/tutor/sources",
        json={"title": "手入力", "content": "Bonjour le livre."},
    )
    assert manual.status_code == 201
    created = client.post(
        "/api/tutor/items",
        json={
            "item_type": "vocabulary",
            "canonical_form": "livre",
            "meaning_ja": "本",
        },
    )
    assert created.status_code == 201, created.text
    item_id = created.json()["item"]["id"]
    review = client.post(
        f"/api/tutor/items/{item_id}/reviews",
        json={
            "exercise_type": "meaning_recognition",
            "result": "correct",
            "occurred_at": datetime.now(UTC).isoformat(),
        },
    )
    assert review.status_code == 201, review.text

    fetcher = _FailingFetcher()
    app.dependency_overrides[get_web_page_fetcher] = lambda: fetcher
    failed_url = client.post(
        "/api/tutor/sources/ingest/url",
        json={"url": PUBLIC_URL},
    )
    assert failed_url.status_code == 502
    assert _detail_code(failed_url.json()) == "upstream_error"
    assert fetcher.calls == 1

    failed_pdf = _post_file(
        client,
        "/api/tutor/sources/ingest/pdf",
        "broken.pdf",
        b"%PDF-not-a-real-document",
        "application/pdf",
    )
    assert failed_pdf["status"] == 400
    assert _detail_code(failed_pdf["body"]) == "malformed_pdf"

    app.dependency_overrides[get_youtube_transcript_provider] = lambda: _EmptyYoutube()
    failed_youtube = client.post(
        "/api/tutor/sources/ingest/youtube",
        json={"video": "abcdefghijk"},
    )
    assert failed_youtube.status_code == 422
    assert _detail_code(failed_youtube.json()) == "transcript_unavailable"

    app.dependency_overrides[get_transcription_provider] = lambda: (
        _TranscriptionProvider(
            error=AudioIngestionError(
                MSG_PROVIDER,
                code=AudioIngestErrorCode.transcription_provider_error,
            )
        )
    )
    failed_audio = _post_file(
        client,
        "/api/tutor/sources/ingest/audio",
        "livre.wav",
        _wav(),
        "audio/wav",
    )
    assert failed_audio["status"] == 502
    assert _detail_code(failed_audio["body"]) == "transcription_provider_error"
    assert "RAW-AUDIO-MARKER" not in failed_audio["text"]

    listed = client.get("/api/tutor/sources")
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [manual.json()["id"]]
    assert store.learning_events.list_by_item(item_id)
    detail = client.get(f"/api/tutor/items/{item_id}")
    assert detail.status_code == 200
    state = detail.json()["learner_state"]["by_direction"]["recognition"]
    assert state["attempt_count"] == 1


def test_phase6_blocks_unsafe_urls_and_malformed_files(
    client: TestClient, store: TutorSqliteStore
) -> None:
    """危険な URL、拡張子だけの MIME、壊れた入力、上限超過を保存しない。"""

    transport = _ExplodingTransport()
    app.dependency_overrides[get_web_page_fetcher] = lambda: GuardedWebFetcher(
        _ExplodingResolver(), transport
    )
    blocked = (
        "http://localhost/admin",
        "http://127.0.0.1/",
        "http://10.0.0.1/",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/",
    )
    for url in blocked:
        response = client.post("/api/tutor/sources/ingest/url", json={"url": url})
        assert response.status_code == 400, response.text
        assert _detail_code(response.json()) in {"blocked_url", "invalid_url"}
        assert "127.0.0.1" not in response.text
        assert "169.254.169.254" not in response.text
    assert transport.calls == 0

    transport = _ScriptedTransport(
        [
            HttpExchange(
                status=302,
                headers={"location": "http://169.254.169.254/latest"},
                body=b"secret-redirect-body",
            )
        ]
    )
    app.dependency_overrides[get_web_page_fetcher] = lambda: GuardedWebFetcher(
        _AddressResolver(), transport
    )
    redirected = client.post(
        "/api/tutor/sources/ingest/url",
        json={"url": "https://example.com/start"},
    )
    assert redirected.status_code == 400, redirected.text
    assert _detail_code(redirected.json()) == "blocked_url"
    assert "169.254.169.254" not in redirected.text
    assert "secret-redirect-body" not in redirected.text
    assert len(transport.calls) == 1

    declared_html = _post_file(
        client,
        "/api/tutor/sources/ingest/pdf",
        "lecon.pdf",
        lesson_pdf(),
        "text/html",
    )
    assert declared_html["status"] == 415
    assert _detail_code(declared_html["body"]) == "unsupported_media"

    malformed_pdf = _post_file(
        client,
        "/api/tutor/sources/ingest/pdf",
        "lecon.pdf",
        b"<html><body>secret-html-pdf</body></html>",
        "application/pdf",
    )
    assert malformed_pdf["status"] == 400
    assert _detail_code(malformed_pdf["body"]) == "malformed_pdf"
    assert "secret-html-pdf" not in malformed_pdf["text"]

    too_many_pages = _post_file(
        client,
        "/api/tutor/sources/ingest/pdf",
        "long.pdf",
        build_pdf(
            [
                text_page("Bonjour, cette page parle francais aujourd'hui.")
                for _ in range(MAX_PDF_PAGES + 1)
            ]
        ),
        "application/pdf",
    )
    assert too_many_pages["status"] == 413
    assert _detail_code(too_many_pages["body"]) == "too_many_pages"

    oversized = _post_file(
        client,
        "/api/tutor/sources/ingest/text-file",
        "big.txt",
        b"a" * (MAX_TEXT_FILE_BYTES + 1),
        "text/plain",
    )
    assert oversized["status"] == 413
    assert _detail_code(oversized["body"]) == "file_too_large"

    html_text = _post_file(
        client,
        "/api/tutor/sources/ingest/text-file",
        "notes.txt",
        b"<!DOCTYPE html><html><body>SUPERSECRET</body></html>",
        "text/plain",
    )
    assert html_text["status"] == 400
    assert _detail_code(html_text["body"]) == "malformed_text"
    assert "SUPERSECRET" not in html_text["text"]

    leaked = _post_file(
        client,
        "/api/tutor/sources/ingest/conversation",
        "dialogue.json",
        json.dumps(
            {"messages": [{"text": "Bonjour", "email": "secret@example.com"}]}
        ).encode(),
        "application/json",
    )
    assert leaked["status"] == 400
    assert _detail_code(leaked["body"]) == "malformed_conversation"
    assert "secret@example.com" not in leaked["text"]

    broken_srt = _post_file(
        client,
        "/api/tutor/sources/ingest/subtitle",
        "notes.srt",
        b"this is not a timed subtitle",
        "text/plain",
    )
    assert broken_srt["status"] == 400
    assert store.source_documents.list() == []


def test_phase6_downstream_pipeline_does_not_branch_on_source_type() -> None:
    """Candidate / LearningItem / ranking / Today は SourceType を必須にしない。"""

    import app.domain.daily_learning_plan as daily_learning_plan
    import app.domain.exercise as exercise
    import app.domain.exercise_generation as exercise_generation
    import app.domain.recommendation_ranking as recommendation_ranking
    import app.domain.recommendation_signal as recommendation_signal
    import app.domain.today_session as today_session
    import app.services.candidate_service as candidate_service
    import app.services.extraction_service as extraction_service
    import app.services.today_learning_service as today_learning_service

    modules = (
        recommendation_signal,
        recommendation_ranking,
        daily_learning_plan,
        today_session,
        exercise,
        exercise_generation,
        extraction_service,
        candidate_service,
        today_learning_service,
    )
    for module in modules:
        tree = ast.parse(inspect.getsource(module))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                assert node.id != "source_type"
            if isinstance(node, ast.Attribute):
                assert node.attr != "source_type"
    assert "source_type" not in inspect.signature(rank_recommendations).parameters
    assert "source_type" not in LearningItem.model_fields
    with TestClient(app) as http:
        spec = http.get("/openapi.json").json()
    paths = spec["paths"]
    for path in (
        "/api/tutor/sources/ingest/url",
        "/api/tutor/sources/ingest/pdf",
        "/api/tutor/sources/ingest/subtitle",
        "/api/tutor/sources/ingest/audio",
        "/api/tutor/sources/ingest/text-file",
        "/api/tutor/sources/ingest/conversation",
        "/api/tutor/today",
        "/api/tutor/today/sessions",
    ):
        assert path in paths
    for path in ("/api/tutor/ranking", "/api/tutor/recommendations"):
        assert path not in paths


def test_phase6_manual_practice_review_quiz_and_tts_remain(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    manual = client.post(
        "/api/tutor/sources",
        json={"title": "手入力", "content": "ligne\r\n\r\n\r\nsuite"},
    )
    assert manual.status_code == 201
    assert manual.json()["source_type"] == "manual_text"
    assert manual.json()["content"] == "ligne\r\n\r\n\r\nsuite"
    assert manual.json()["segments"] == []

    created = client.post(
        "/api/tutor/items",
        json={
            "item_type": "vocabulary",
            "canonical_form": "livre",
            "meaning_ja": "本",
        },
    )
    assert created.status_code == 201, created.text
    for form, meaning in (("gare", "駅"), ("café", "コーヒー"), ("école", "学校")):
        extra = client.post(
            "/api/tutor/items",
            json={
                "item_type": "vocabulary",
                "canonical_form": form,
                "meaning_ja": meaning,
            },
        )
        assert extra.status_code == 201, extra.text
    item_id = created.json()["item"]["id"]
    occurred_at = datetime.now(UTC) - timedelta(days=30)
    review = client.post(
        f"/api/tutor/items/{item_id}/reviews",
        json={
            "exercise_type": "meaning_recognition",
            "result": "correct",
            "occurred_at": occurred_at.isoformat(),
        },
    )
    assert review.status_code == 201, review.text

    question = client.get("/api/questions/next")
    assert question.status_code == 200
    assert {"verb", "tense", "pronoun"} <= set(question.json())
    noun = client.get("/api/nouns/next")
    assert noun.status_code == 200
    assert noun.json()["noun"] in NOUNS
    article = client.get("/api/nouns/article/next")
    assert article.status_code == 200
    tts = client.get("/api/tts/speak?text=bonjour")
    assert tts.status_code == 503
    practice = client.post("/api/tutor/practice/sessions", json={"question_count": 5})
    assert practice.status_code == 200, practice.text
    assert practice.json()["generated_count"] >= 1
    review_session = client.post(
        "/api/tutor/review/sessions", json={"question_count": 5}
    )
    assert review_session.status_code == 200, review_session.text
    assert review_session.json()["generated_count"] >= 1
    today = client.get("/api/tutor/today")
    assert today.status_code == 200
