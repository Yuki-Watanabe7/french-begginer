"""YouTube の公開字幕を時刻 provenance 付き SourceDocument にする（Issue #192）。

通常のテストは fake provider で完結し、ネットワークも音声 download も使わない。
"""

from __future__ import annotations

import ast
import inspect
import socket
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
import requests
from fastapi.testclient import TestClient
from youtube_transcript_api._errors import (
    InvalidVideoId,
    RequestBlocked,
    TranscriptsDisabled,
    VideoUnavailable,
)

from app.api.deps import (
    get_learning_item_extractor,
    get_tutor_store,
    get_youtube_transcript_provider,
)
from app.domain.source_ingestion import (
    INGESTION_VERSION,
    IngestAction,
    SourceIngestionError,
    content_digest,
    segment_for_span,
)
from app.domain.tutor import SourceDocument, read_source_evidence
from app.ingestion.youtube import (
    YOUTUBE_ADAPTER_VERSION,
    YOUTUBE_FETCH_TIMEOUT_SECONDS,
    TranscriptSnippet,
    TranscriptTrack,
    parse_youtube_video,
    select_transcript_track,
)
from app.ingestion.youtube_api import (
    YoutubeTranscriptApiProvider,
    map_youtube_library_error,
)
from app.ingestion.youtube_errors import (
    MSG_TRANSCRIPT_DISABLED,
    MSG_TRANSCRIPT_PROVIDER,
    MSG_TRANSCRIPT_TIMEOUT,
    YoutubeIngestErrorCode,
    YoutubeIngestionError,
)
from app.main import app
from app.repositories.sqlite import TutorSqliteStore
from app.services.extraction_schema import ExtractedCandidate, ExtractedEvidenceSpan
from app.services.extraction_service import ExtractionService
from app.services.extractors import ExtractorResult
from app.services.youtube_ingestion import YoutubeIngestionService

FIXED = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
LATER = datetime(2026, 4, 2, 12, 0, tzinfo=UTC)
AFTER = datetime(2026, 4, 3, 12, 0, tzinfo=UTC)
VIDEO_ID = "abcdefghijk"
WATCH_URL = f"https://www.youtube.com/watch?v={VIDEO_ID}"
LESSON = (
    "<i>Aujourd'hui</i>, l'élève apprend.",
    "Il prend un café.",
)
LESSON_CONTENT = "Aujourd'hui, l'élève apprend.\n\nIl prend un café."


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError(f"network call: {args!r} {kwargs!r}")

    monkeypatch.setattr(socket, "getaddrinfo", boom)
    monkeypatch.setattr(socket, "create_connection", boom)


@pytest.fixture
def store() -> TutorSqliteStore:
    return TutorSqliteStore.in_memory()


@pytest.fixture
def client(store: TutorSqliteStore) -> Iterator[TestClient]:
    app.dependency_overrides[get_tutor_store] = lambda: store
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_youtube_ingestion_does_not_use_network() -> None:
    assert YOUTUBE_FETCH_TIMEOUT_SECONDS == 10.0
    with pytest.raises(AssertionError, match="network call"):
        socket.getaddrinfo("www.youtube.com", 443)


def test_video_url_and_id_validation() -> None:
    for value in (
        VIDEO_ID,
        WATCH_URL,
        f"https://youtu.be/{VIDEO_ID}?t=12",
        f"https://m.youtube.com/watch?v={VIDEO_ID}",
        f"https://music.youtube.com/watch?v={VIDEO_ID}&list=PLabcdefghij",
        f"https://www.youtube.com/shorts/{VIDEO_ID}",
        f"https://www.youtube.com/embed/{VIDEO_ID}",
        f"https://www.youtube.com/live/{VIDEO_ID}",
        f"https://www.youtube-nocookie.com/embed/{VIDEO_ID}",
        f"http://youtu.be/{VIDEO_ID}",
    ):
        parsed = parse_youtube_video(value)
        assert parsed.video_id == VIDEO_ID
        assert parsed.canonical_locator == f"youtube:{VIDEO_ID}"
    assert parse_youtube_video(VIDEO_ID).original_url == WATCH_URL
    watched = parse_youtube_video(f"{WATCH_URL}&list=PLabcdefghij#t=3")
    assert watched.video_id == VIDEO_ID
    assert watched.original_url == f"{WATCH_URL}&list=PLabcdefghij"

    secret_url = "https://user:secret-token@www.youtube.com/watch?v=" + VIDEO_ID
    secret = parse_failure(secret_url)
    assert secret.code is YoutubeIngestErrorCode.invalid_video
    assert "secret-token" not in str(secret)
    playlist = parse_failure("https://www.youtube.com/playlist?list=PLabcdefghij")
    assert playlist.code is YoutubeIngestErrorCode.invalid_video
    assert "playlist" in str(playlist)
    for rejected in (
        "short",
        "https://example.com/watch?v=" + VIDEO_ID,
        "https://www.youtube.com/@frenchpod",
        "javascript:alert(1)",
        "https://www.youtube.com/watch?list=PLabcdefghij",
    ):
        assert parse_failure(rejected).code is YoutubeIngestErrorCode.invalid_video


def test_language_selection_prefers_original_french_and_records_translation() -> None:
    french_manual = _track("fr")
    french_generated = _track("fr", generated=True)
    french_regional = _track("fr-CA")
    french_translation = _track("fr", translation=True, translated_from="en")
    english = _track("en")
    chosen = select_transcript_track(
        [english, french_generated, french_translation, french_regional, french_manual],
        "fr",
    )
    assert chosen.track.track_id == french_manual.track_id
    assert chosen.rule == "manual_caption"

    regional = select_transcript_track([french_regional, french_generated], "fr")
    assert regional.track.language_code == "fr-CA"
    assert regional.rule == "manual_caption"

    exact = select_transcript_track([_track("fr"), _track("fr-FR")], "fr-FR")
    assert exact.track.language_code == "fr-FR"

    generated = select_transcript_track([english, french_generated], "fr")
    assert generated.rule == "generated_caption"

    translated = select_transcript_track([english, french_translation], "fr")
    assert translated.rule == "manual_translation"
    assert translated.track.is_translation is True
    assert translated.track.translated_from == "en"

    english_choice = select_transcript_track([french_manual, english], "en")
    assert english_choice.track.language_code == "en"

    tied = select_transcript_track(
        [_track("fr", track_id="manual:fr:b"), _track("fr", track_id="manual:fr:a")],
        "fr",
    )
    assert tied.track.track_id == "manual:fr:a"

    with pytest.raises(YoutubeIngestionError) as missing:
        select_transcript_track([english], "fr")
    assert missing.value.code is YoutubeIngestErrorCode.transcript_unavailable
    assert missing.value.available_languages == ("en",)


def test_fake_youtube_transcript_saves_timed_segments(store: TutorSqliteStore) -> None:
    provider = _lesson_provider()
    committed = _service(store, provider).ingest_youtube(
        video=f"https://youtu.be/{VIDEO_ID}",
        note="depuis youtube",
    )
    document = committed.document
    assert committed.created is True
    assert committed.action is IngestAction.create
    assert provider.fetch_calls == [(VIDEO_ID, "manual:fr")]
    assert document.source_type == "youtube_transcript"
    assert document.title == f"YouTube {VIDEO_ID}"
    assert document.language == "fr"
    assert document.content == LESSON_CONTENT
    assert "l'élève" in document.content
    assert "<i>" not in document.content
    assert document.content_hash == content_digest(document.content)
    assert document.ingestion_version == INGESTION_VERSION
    assert document.segments[0].start_seconds == 1.0
    assert document.segments[0].end_seconds == 4.0
    assert document.segments[1].start_seconds == 4.5
    assert document.segments[1].end_seconds == 7.0
    provenance = document.provenance
    assert provenance is not None
    assert provenance.canonical_locator == f"youtube:{VIDEO_ID}"
    assert provenance.external_id == VIDEO_ID
    assert provenance.provider == "fake"
    assert provenance.fetched_at == FIXED
    assert provenance.adapter_version == YOUTUBE_ADAPTER_VERSION
    assert provenance.mime_type == "text/plain"
    assert document.metadata["video_id"] == VIDEO_ID
    assert document.metadata["original_url"] == f"https://youtu.be/{VIDEO_ID}"
    assert document.metadata["requested_language"] == "fr"
    assert document.metadata["transcript_language"] == "fr"
    assert document.metadata["caption_kind"] == "manual"
    assert document.metadata["transcript_is_translation"] is False
    assert document.metadata["selection_rule"] == "manual_caption"
    assert document.metadata["cue_count"] == 2
    assert document.metadata["note"] == "depuis youtube"
    assert "speech_language" not in document.metadata
    assert "original_language" not in document.metadata
    assert _span(document, "élève").start_seconds == 1.0
    assert _span(document, "café").end_seconds == 7.0


def test_translation_is_not_treated_as_original_speech(store: TutorSqliteStore) -> None:
    provider = FakeTranscriptProvider(
        tracks=(
            _track("en", generated=True),
            _track("fr", translation=True, translated_from="en"),
        ),
        cues=(TranscriptSnippet("Bonjour, le café est chaud.", 0.0, 2.0),),
    )
    document = (
        _service(store, provider).ingest_youtube(video=VIDEO_ID, language="fr").document
    )
    assert document.language == "fr"
    assert document.metadata["selection_rule"] == "manual_translation"
    assert document.metadata["transcript_is_translation"] is True
    assert document.metadata["translated_from"] == "en"
    assert document.metadata["asr_language"] == "en"
    assert document.metadata["speech_language"] == "en"
    assert document.metadata["transcript_matches_speech"] is False
    assert provider.fetch_calls == [(VIDEO_ID, "manual-translation:fr")]

    spoken = FakeTranscriptProvider(
        tracks=(_track("fr", generated=True),),
        cues=(TranscriptSnippet("Le café est servi.", 0.0, 2.0),),
    )
    asr = _service(store, spoken).ingest_youtube(video=VIDEO_ID).document
    assert asr.metadata["selection_rule"] == "generated_caption"
    assert asr.metadata["speech_language"] == "fr"
    assert asr.metadata["transcript_matches_speech"] is True
    assert asr.metadata["transcript_is_translation"] is False


def test_transcript_unavailable_does_not_fetch_cues(store: TutorSqliteStore) -> None:
    missing_language = FakeTranscriptProvider(tracks=(_track("en"),))
    with pytest.raises(YoutubeIngestionError) as unavailable:
        _service(store, missing_language).ingest_youtube(video=VIDEO_ID)
    assert unavailable.value.code is YoutubeIngestErrorCode.transcript_unavailable
    assert unavailable.value.available_languages == ("en",)
    assert missing_language.fetch_calls == []

    empty = FakeTranscriptProvider(tracks=())
    with pytest.raises(YoutubeIngestionError) as no_tracks:
        _service(store, empty).ingest_youtube(video=VIDEO_ID)
    assert no_tracks.value.code is YoutubeIngestErrorCode.transcript_unavailable
    assert empty.fetch_calls == []
    assert store.source_documents.list() == []


def test_transcript_disabled_is_explicit(store: TutorSqliteStore) -> None:
    provider = FakeTranscriptProvider(
        tracks=(),
        list_error=YoutubeIngestionError(
            MSG_TRANSCRIPT_DISABLED, code=YoutubeIngestErrorCode.transcript_disabled
        ),
    )
    with pytest.raises(YoutubeIngestionError) as disabled:
        _service(store, provider).ingest_youtube(video=WATCH_URL)
    assert disabled.value.code is YoutubeIngestErrorCode.transcript_disabled
    assert disabled.value.retryable is False
    assert provider.fetch_calls == []
    assert store.source_documents.list() == []


def test_youtube_cues_keep_provider_order_when_times_overlap(
    store: TutorSqliteStore,
) -> None:
    provider = FakeTranscriptProvider(
        tracks=(_track("fr"),),
        cues=(
            TranscriptSnippet("deuxième", 5.0, 1.0),
            TranscriptSnippet("premier", 1.0, 3.0),
            TranscriptSnippet("café", 2.0, 0.0),
        ),
    )
    document = _service(store, provider).ingest_youtube(video=VIDEO_ID).document
    assert document.content == "deuxième\n\npremier\n\ncafé"
    assert [(item.start_seconds, item.end_seconds) for item in document.segments] == [
        (5.0, 6.0),
        (1.0, 4.0),
        (2.0, pytest.approx(2.001)),
    ]
    assert document.segments[1].end_seconds > document.segments[2].start_seconds


def test_malformed_transcript_and_empty_cues_are_not_saved(
    store: TutorSqliteStore,
) -> None:
    malformed = FakeTranscriptProvider(
        tracks=(_track("fr"),),
        cues=(TranscriptSnippet("secret-body", -1.0, 2.0),),
    )
    with pytest.raises(YoutubeIngestionError) as bad_time:
        _service(store, malformed).ingest_youtube(video=VIDEO_ID)
    assert bad_time.value.code is YoutubeIngestErrorCode.malformed_transcript
    assert "secret-body" not in str(bad_time.value)

    empty = FakeTranscriptProvider(
        tracks=(_track("fr"),),
        cues=(TranscriptSnippet("<i></i>", 0.0, 1.0),),
    )
    with pytest.raises(YoutubeIngestionError) as blank:
        _service(store, empty).ingest_youtube(video=VIDEO_ID)
    assert blank.value.code is YoutubeIngestErrorCode.transcript_empty
    assert store.source_documents.list() == []


def test_character_offset_maps_to_youtube_timestamp(store: TutorSqliteStore) -> None:
    document = (
        _service(store, _lesson_provider()).ingest_youtube(video=VIDEO_ID).document
    )
    assert _span(document, "élève").start_seconds == 1.0
    assert _span(document, "café").start_seconds == 4.5
    gap = document.segments[0].normalized_end
    with pytest.raises(SourceIngestionError):
        segment_for_span(document.segments, start=gap, end=gap + 2)


def test_candidate_evidence_maps_to_timecode(store: TutorSqliteStore) -> None:
    document = (
        _service(store, _lesson_provider()).ingest_youtube(video=VIDEO_ID).document
    )
    extractor = _CafeExtractor()
    extracted = ExtractionService(extractor).extract(document)
    assert extractor.sources[0].source_type == "youtube_transcript"
    evidence = read_source_evidence(
        document.content, extracted.candidates[0].evidence_span
    )
    assert evidence == "café"
    mapped = segment_for_span(
        document.segments,
        start=extracted.candidates[0].evidence_span.start,
        end=extracted.candidates[0].evidence_span.end,
    )
    assert mapped.start_seconds == 4.5
    assert mapped.end_seconds == 7.0


def test_same_video_reuses_and_changed_transcript_appends(
    store: TutorSqliteStore,
) -> None:
    moments = iter((FIXED, LATER, AFTER))
    provider = _lesson_provider()
    service = _service(store, provider, clock=lambda: next(moments))
    created = service.ingest_youtube(video=WATCH_URL, title="Leçon")
    reused = service.ingest_youtube(video=VIDEO_ID, title="Ignoré")
    assert reused.action is IngestAction.reuse
    assert reused.document.id == created.document.id
    assert reused.document.title == "Leçon"
    provider.cues = (TranscriptSnippet("Une nouvelle phrase pour le café.", 0.0, 2.0),)
    appended = service.ingest_youtube(
        video=f"https://www.youtube.com/shorts/{VIDEO_ID}"
    )
    assert appended.action is IngestAction.append_version
    assert appended.document.id != created.document.id
    assert appended.document.metadata["prior_source_id"] == created.document.id
    preserved = store.source_documents.get(created.document.id)
    assert preserved is not None
    assert preserved.content == LESSON_CONTENT


def test_youtube_source_survives_database_reopen(tmp_path) -> None:
    path = tmp_path / "tutor.db"
    store = TutorSqliteStore(f"sqlite:///{path}")
    try:
        saved = _service(store, _lesson_provider()).ingest_youtube(video=VIDEO_ID)
        store.engine.dispose()
        reopened = TutorSqliteStore(f"sqlite:///{path}")
        try:
            loaded = reopened.source_documents.get(saved.document.id)
            assert loaded == saved.document
            assert loaded is not None
            assert _span(loaded, "café").start_seconds == 4.5
        finally:
            reopened.engine.dispose()
    finally:
        store.engine.dispose()


def test_ingest_youtube_api_returns_source_and_keeps_manual_create(
    client: TestClient, store: TutorSqliteStore
) -> None:
    manual = client.post(
        "/api/tutor/sources",
        json={"title": "手入力", "content": "ligne\r\n\r\n\r\nsuite"},
    )
    assert manual.status_code == 201
    assert manual.json()["content"] == "ligne\r\n\r\n\r\nsuite"

    provider = _lesson_provider()
    app.dependency_overrides[get_youtube_transcript_provider] = lambda: provider
    created = client.post(
        "/api/tutor/sources/ingest/youtube",
        json={"video": WATCH_URL, "title": "Mon cours", "note": "vu", "language": "fr"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    source = body["source"]
    assert body["action"] == "create"
    assert source["source_type"] == "youtube_transcript"
    assert source["title"] == "Mon cours"
    assert source["content"] == LESSON_CONTENT
    assert source["provenance"]["external_id"] == VIDEO_ID
    assert source["metadata"]["video_id"] == VIDEO_ID
    assert source["segments"][1]["start_seconds"] == 4.5
    assert provider.fetch_calls

    again = client.post(
        "/api/tutor/sources/ingest/youtube",
        json={"video": f"https://youtu.be/{VIDEO_ID}"},
    )
    assert again.status_code == 200
    assert again.json()["action"] == "reuse"
    assert again.json()["source"]["id"] == source["id"]

    app.dependency_overrides[get_learning_item_extractor] = lambda: _CafeExtractor()
    extracted = client.post(f"/api/tutor/sources/{source['id']}/candidates/extract")
    assert extracted.status_code == 200, extracted.text
    candidate = extracted.json()["created"][0]
    assert candidate["evidence_text"] == "café"
    loaded = store.source_documents.get(source["id"])
    assert loaded is not None
    span = candidate["evidence_span"]
    mapped = segment_for_span(loaded.segments, start=span["start"], end=span["end"])
    assert mapped.start_seconds == 4.5


def test_ingest_youtube_api_distinguishes_errors(
    client: TestClient, store: TutorSqliteStore
) -> None:
    app.dependency_overrides[get_youtube_transcript_provider] = lambda: (
        FakeTranscriptProvider(tracks=(_track("en"),))
    )
    unavailable = client.post(
        "/api/tutor/sources/ingest/youtube",
        json={"video": VIDEO_ID, "language": "fr"},
    )
    assert unavailable.status_code == 422
    assert unavailable.json()["detail"]["code"] == "transcript_unavailable"
    assert unavailable.json()["detail"]["available_languages"] == ["en"]

    app.dependency_overrides[get_youtube_transcript_provider] = lambda: (
        FakeTranscriptProvider(
            tracks=(),
            list_error=YoutubeIngestionError(
                MSG_TRANSCRIPT_DISABLED,
                code=YoutubeIngestErrorCode.transcript_disabled,
            ),
        )
    )
    disabled = client.post(
        "/api/tutor/sources/ingest/youtube",
        json={"video": WATCH_URL},
    )
    assert disabled.status_code == 422
    assert disabled.json()["detail"]["code"] == "transcript_disabled"

    app.dependency_overrides[get_youtube_transcript_provider] = lambda: (
        FakeTranscriptProvider(
            tracks=(_track("fr"),),
            fetch_error=YoutubeIngestionError(
                MSG_TRANSCRIPT_TIMEOUT,
                code=YoutubeIngestErrorCode.transcript_timeout,
            ),
        )
    )
    timed_out = client.post(
        "/api/tutor/sources/ingest/youtube",
        json={"video": VIDEO_ID},
    )
    assert timed_out.status_code == 504
    assert timed_out.json()["detail"]["code"] == "transcript_timeout"

    playlist = client.post(
        "/api/tutor/sources/ingest/youtube",
        json={"video": "https://www.youtube.com/playlist?list=PLabcdefghij"},
    )
    assert playlist.status_code == 400
    assert playlist.json()["detail"]["code"] == "invalid_video"
    assert store.source_documents.list() == []


def test_provider_reads_published_captions_without_translating() -> None:
    transcript = _LibraryTranscript()
    api = _LibraryApi(transcript)
    provider = YoutubeTranscriptApiProvider(client_factory=lambda: api)
    tracks = provider.list_tracks(VIDEO_ID)
    assert tracks[0].is_translation is False
    assert tracks[0].is_generated is False
    assert tracks[0].language_code == "fr"
    cues = provider.fetch_track(VIDEO_ID, tracks[0])
    assert cues[0].text == "Bonjour"
    assert cues[0].start_seconds == 0.0
    assert cues[0].duration_seconds == 1.5
    assert api.listed == [VIDEO_ID]
    assert transcript.fetch_calls == 1

    def refuse() -> _LibraryApi:
        raise AssertionError("provider called")

    guarded = YoutubeTranscriptApiProvider(client_factory=refuse)
    with pytest.raises(YoutubeIngestionError) as invalid:
        guarded.list_tracks("https://www.youtube.com/watch?v=" + VIDEO_ID)
    assert invalid.value.code is YoutubeIngestErrorCode.invalid_video


def test_library_errors_do_not_leak_urls() -> None:
    disabled = map_youtube_library_error(TranscriptsDisabled(VIDEO_ID))
    assert disabled.code is YoutubeIngestErrorCode.transcript_disabled
    assert disabled.retryable is False
    assert "http" not in str(disabled)
    unavailable = map_youtube_library_error(VideoUnavailable(VIDEO_ID))
    assert unavailable.code is YoutubeIngestErrorCode.video_unavailable
    invalid = map_youtube_library_error(InvalidVideoId(VIDEO_ID))
    assert invalid.code is YoutubeIngestErrorCode.invalid_video
    assert "http" not in str(invalid)
    blocked = map_youtube_library_error(RequestBlocked(VIDEO_ID))
    assert blocked.code is YoutubeIngestErrorCode.transcript_provider_error
    assert blocked.retryable is True
    assert str(blocked) == MSG_TRANSCRIPT_PROVIDER
    timed_out = map_youtube_library_error(requests.Timeout("secret-upstream"))
    assert timed_out.code is YoutubeIngestErrorCode.transcript_timeout
    assert timed_out.retryable is True
    assert str(timed_out) == MSG_TRANSCRIPT_TIMEOUT
    assert "secret-upstream" not in str(timed_out)


def test_openapi_exposes_youtube_ingest_without_changing_manual_create() -> None:
    with TestClient(app) as http:
        spec = http.get("/openapi.json").json()
    operation = spec["paths"]["/api/tutor/sources/ingest/youtube"]["post"]
    schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert (
        "video"
        in spec["components"]["schemas"][schema["$ref"].rsplit("/", 1)[-1]][
            "properties"
        ]
    )
    assert "/api/tutor/sources/youtube" not in spec["paths"]


def test_youtube_modules_do_not_download_audio() -> None:
    import app.ingestion.youtube as adapter
    import app.ingestion.youtube_api as api
    import app.services.youtube_ingestion as service

    audio_downloaders = {
        "yt_dlp",
        "pytube",
        "youtube_dl",
        "whisper",
        "faster_whisper",
        "openai",
    }
    assert "youtube_transcript_api" not in _imported_roots(adapter)
    assert "requests" not in _imported_roots(adapter)
    assert "youtube_transcript_api" not in _imported_roots(service)
    assert "youtube_transcript_api" in _imported_roots(api)
    assert "requests" in _imported_roots(api)
    for module in (adapter, service, api):
        assert _imported_roots(module).isdisjoint(audio_downloaders), module.__name__
    assert "translate(" not in inspect.getsource(api)


class FakeTranscriptProvider:
    provider_name = "fake"
    provider_version = "fake-1"

    def __init__(
        self,
        tracks: tuple[TranscriptTrack, ...],
        cues: tuple[TranscriptSnippet, ...] = (),
        *,
        list_error: YoutubeIngestionError | None = None,
        fetch_error: YoutubeIngestionError | None = None,
    ) -> None:
        self.tracks = tracks
        self.cues = cues
        self.list_error = list_error
        self.fetch_error = fetch_error
        self.list_calls: list[str] = []
        self.fetch_calls: list[tuple[str, str]] = []

    def list_tracks(self, video_id: str) -> tuple[TranscriptTrack, ...]:
        self.list_calls.append(video_id)
        if self.list_error is not None:
            raise self.list_error
        return self.tracks

    def fetch_track(
        self, video_id: str, track: TranscriptTrack
    ) -> tuple[TranscriptSnippet, ...]:
        self.fetch_calls.append((video_id, track.track_id))
        if self.fetch_error is not None:
            raise self.fetch_error
        return self.cues


class _LibraryTranscript:
    language_code = "fr"
    is_generated = False

    def __init__(self) -> None:
        self.fetch_calls = 0

    def fetch(self) -> list[_LibrarySnippet]:
        self.fetch_calls += 1
        return [_LibrarySnippet("Bonjour", 0.0, 1.5)]

    def translate(self, language_code: str) -> None:
        raise AssertionError(language_code)


class _LibrarySnippet:
    def __init__(self, text: str, start: float, duration: float) -> None:
        self.text = text
        self.start = start
        self.duration = duration


class _LibraryApi:
    def __init__(self, transcript: _LibraryTranscript) -> None:
        self.transcript = transcript
        self.listed: list[str] = []

    def list(self, video_id: str) -> list[_LibraryTranscript]:
        self.listed.append(video_id)
        return [self.transcript]


class _CafeExtractor:
    def __init__(self) -> None:
        self.sources: list[SourceDocument] = []

    def extract(self, source: SourceDocument) -> ExtractorResult:
        self.sources.append(source)
        start = source.content.index("café")
        return ExtractorResult(
            candidates=(
                ExtractedCandidate(
                    item_type="vocabulary",
                    canonical_form="café",
                    meaning_ja="コーヒー",
                    evidence_span=ExtractedEvidenceSpan(
                        start=start, end=start + len("café")
                    ),
                    confidence=0.9,
                ),
            ),
            provider="fake",
            model="fake",
            extraction_version="test-v1",
        )


def _track(
    code: str,
    *,
    generated: bool = False,
    translation: bool = False,
    translated_from: str | None = None,
    track_id: str | None = None,
) -> TranscriptTrack:
    kind = "generated" if generated else "manual"
    if translation:
        kind = f"{kind}-translation"
    return TranscriptTrack(
        track_id=track_id or f"{kind}:{code}",
        language_code=code,
        is_generated=generated,
        is_translation=translation,
        translated_from=translated_from,
    )


def _lesson_provider() -> FakeTranscriptProvider:
    return FakeTranscriptProvider(
        tracks=(_track("fr"),),
        cues=(
            TranscriptSnippet(LESSON[0], 1.0, 3.0),
            TranscriptSnippet(LESSON[1], 4.5, 2.5),
        ),
    )


def _service(
    store: TutorSqliteStore,
    provider: FakeTranscriptProvider,
    *,
    clock=lambda: FIXED,
) -> YoutubeIngestionService:
    return YoutubeIngestionService(store.source_documents, provider, clock=clock)


def _span(document: SourceDocument, word: str):
    start = document.content.index(word)
    return segment_for_span(document.segments, start=start, end=start + len(word))


def parse_failure(value: str) -> YoutubeIngestionError:
    with pytest.raises(YoutubeIngestionError) as caught:
        parse_youtube_video(value)
    return caught.value


def _imported_roots(module: object) -> set[str]:
    tree = ast.parse(inspect.getsource(module))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
            if node.module.startswith("app."):
                roots.add(".".join(node.module.split(".")[:2]))
    return roots
