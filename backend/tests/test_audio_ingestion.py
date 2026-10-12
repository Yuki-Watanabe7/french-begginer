"""音声を文字起こし、時刻 provenance 付き SourceDocument にする（Issue #193）。

通常のテストは fake provider で完結し、ネットワークも API key も使わない。
raw audio は保存しない。
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import socket
import struct
from collections.abc import Iterator
from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import APITimeoutError, AuthenticationError, RateLimitError

from app.api.deps import (
    get_audio_ingestion_service,
    get_learning_item_extractor,
    get_transcription_provider,
    get_tutor_store,
)
from app.domain.source_ingestion import (
    INGESTION_VERSION,
    IngestAction,
    content_digest,
    segment_for_span,
)
from app.domain.tutor import SourceDocument, read_source_evidence
from app.ingestion.audio import (
    AUDIO_ADAPTER_VERSION,
    MAX_AUDIO_BYTES,
    MAX_AUDIO_SECONDS,
    AudioPayload,
    TranscriptionProvider,
    TranscriptionResult,
    TranscriptSegment,
)
from app.ingestion.audio_api import (
    MAX_TRANSCRIPTION_ATTEMPTS,
    TRANSCRIPTION_TIMEOUT_SECONDS,
    TRANSCRIPTION_VERSION,
    OpenAITranscriptionProvider,
    transcription_from_payload,
)
from app.ingestion.audio_errors import (
    MSG_AUTH_FAILED,
    MSG_NOT_CONFIGURED,
    MSG_PROVIDER,
    MSG_TIMEOUT,
    AudioIngestErrorCode,
    AudioIngestionError,
)
from app.main import app
from app.repositories.sqlite import TutorSqliteStore
from app.services.audio_ingestion import AudioIngestionService
from app.services.extraction_schema import ExtractedCandidate, ExtractedEvidenceSpan
from app.services.extraction_service import ExtractionService
from app.services.extractors import ExtractorResult

FIXED = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
LATER = datetime(2026, 4, 2, 12, 0, tzinfo=UTC)
AFTER = datetime(2026, 4, 3, 12, 0, tzinfo=UTC)
MARKER = b"RAW-AUDIO-MARKER"
LESSON = (
    "Aujourd'hui, l'élève apprend.",
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


def test_audio_limits_are_explicit() -> None:
    assert MAX_AUDIO_BYTES == 25_000_000
    assert MAX_AUDIO_SECONDS == 600.0
    assert MAX_TRANSCRIPTION_ATTEMPTS == 2
    assert TRANSCRIPTION_TIMEOUT_SECONDS == 120.0


def test_fake_transcription_saves_timed_french_transcript(
    store: TutorSqliteStore,
) -> None:
    provider = _lesson_provider()
    audio = _lesson_wav()
    committed = _service(store, provider).ingest_audio(
        source=_reader(audio),
        filename="../../leçon.wav",
        declared_media_type="audio/wav; charset=binary",
        title="Mon cours",
        note="depuis audio",
    )
    document = committed.document
    assert committed.created is True
    assert committed.action is IngestAction.create
    assert provider.calls == [("leçon.wav", "fr", len(audio))]
    assert MARKER in provider.payloads[0]
    assert document.source_type == "audio_transcript"
    assert document.title == "Mon cours"
    assert document.language == "fr"
    assert document.content == LESSON_CONTENT
    assert "l'élève" in document.content
    assert document.content_hash == content_digest(document.content)
    assert document.ingestion_version == INGESTION_VERSION
    assert document.segments[0].start_seconds == 1.0
    assert document.segments[0].end_seconds == 4.0
    assert document.segments[1].start_seconds == 4.5
    assert document.segments[1].end_seconds == 7.0
    provenance = document.provenance
    assert provenance is not None
    assert provenance.filename == "leçon.wav"
    assert "/" not in provenance.filename
    assert provenance.canonical_locator == _digest(audio)
    assert provenance.provider == "fake"
    assert provenance.provider_model == "fake-1"
    assert provenance.mime_type == "audio/wav"
    assert provenance.adapter_version == AUDIO_ADAPTER_VERSION
    assert provenance.fetched_at == FIXED
    assert document.metadata["original_filename"] == "leçon.wav"
    assert document.metadata["audio_mime"] == "audio/wav"
    assert document.metadata["audio_sha256"] == provenance.canonical_locator
    assert document.metadata["language_hint"] == "fr"
    assert document.metadata["language_status"] == "matches_hint"
    assert document.metadata["detected_language"] == "french"
    assert document.metadata["detected_language_code"] == "fr"
    assert document.metadata["is_translation"] is False
    assert document.metadata["timestamps"] == "segments"
    assert document.metadata["transcription_version"] == "fake-transcript-v1"
    assert document.metadata["transcribed_at"] == FIXED.isoformat()
    assert document.metadata["duration_seconds"] == 1.0
    assert document.metadata["note"] == "depuis audio"
    assert "api_key" not in document.metadata
    assert MARKER.decode() not in document.model_dump_json()
    assert _span(document, "élève").start_seconds == 1.0
    assert _span(document, "café").end_seconds == 7.0


def test_timestamps_are_not_invented_when_provider_omits_them(
    store: TutorSqliteStore,
) -> None:
    provider = FakeTranscriptionProvider(
        TranscriptionResult(
            text="Bonjour, l'élève.",
            segments=None,
            detected_language=None,
        )
    )
    document = _ingest(store, provider).document
    assert document.content == "Bonjour, l'élève."
    assert document.segments[0].start_seconds is None
    assert document.segments[0].end_seconds is None
    assert document.metadata["timestamps"] == "unavailable"
    assert document.language == "fr"
    assert document.metadata["language_status"] == "not_reported"
    assert "detected_language" not in document.metadata

    words_only = transcription_from_payload(
        SimpleNamespace(
            text="Bonjour",
            language="french",
            segments=None,
            words=[SimpleNamespace(word="Bonjour", start=0.0, end=1.0)],
        )
    )
    assert words_only.segments is None
    saved = _ingest(
        store,
        FakeTranscriptionProvider(words_only),
        audio=_mp3(),
        filename="note.mp3",
        media_type="audio/mpeg",
    ).document
    assert saved.segments[0].start_seconds is None
    assert "duration_seconds" not in saved.metadata


def test_combining_accent_and_apostrophe_are_preserved(
    store: TutorSqliteStore,
) -> None:
    document = _ingest(
        store,
        FakeTranscriptionProvider(
            TranscriptionResult(
                text="l'e\u0301le\u0300ve et l’école",
                segments=None,
                detected_language="fr",
            )
        ),
    ).document
    assert document.content == "l'élève et l’école"
    assert "l’école" in document.content


def test_language_difference_keeps_the_original_transcript(
    store: TutorSqliteStore,
) -> None:
    document = _ingest(
        store,
        FakeTranscriptionProvider(
            TranscriptionResult(
                text="Hello, the student learns.",
                segments=(TranscriptSegment("Hello, the student learns.", 0.0, 2.0),),
                detected_language="english",
            )
        ),
        language="fr",
    ).document
    assert document.language == "en"
    assert document.content == "Hello, the student learns."
    assert document.metadata["language_hint"] == "fr"
    assert document.metadata["language_status"] == "differs_from_hint"
    assert document.metadata["detected_language"] == "english"
    assert document.metadata["is_translation"] is False


def test_invalid_media_size_and_duration_never_reach_the_provider(
    store: TutorSqliteStore,
) -> None:
    provider = _lesson_provider()
    service = _service(store, provider)
    rejected = (
        (
            b"",
            "lecon.wav",
            "audio/wav",
            AudioIngestErrorCode.invalid_audio,
        ),
        (
            b"not-a-wav",
            "lecon.wav",
            "audio/wav",
            AudioIngestErrorCode.malformed_audio,
        ),
        (
            _lesson_wav(),
            "lecon.txt",
            "audio/wav",
            AudioIngestErrorCode.unsupported_media,
        ),
        (
            _lesson_wav(),
            "lecon.wav",
            "text/plain",
            AudioIngestErrorCode.unsupported_media,
        ),
        (
            _wav(duration_seconds=601, sample_rate=1),
            "long.wav",
            "audio/wav",
            AudioIngestErrorCode.audio_too_long,
        ),
        (
            _mp4(duration_seconds=601),
            "long.m4a",
            "audio/mp4",
            AudioIngestErrorCode.audio_too_long,
        ),
    )
    for data, name, media, code in rejected:
        with pytest.raises(AudioIngestionError) as caught:
            service.ingest_audio(
                source=_reader(data),
                filename=name,
                declared_media_type=media,
            )
        assert caught.value.code is code
        assert caught.value.retryable is False
    assert provider.calls == []
    assert store.source_documents.list() == []

    limited = AudioIngestionService(
        store.source_documents, provider, clock=lambda: FIXED, max_bytes=8
    )
    with pytest.raises(AudioIngestionError) as oversized:
        limited.ingest_audio(
            source=_reader(b"0123456789"),
            filename="lecon.wav",
            declared_media_type="audio/wav",
        )
    assert oversized.value.code is AudioIngestErrorCode.file_too_large
    assert provider.calls == []

    allowed = _service(store, provider).ingest_audio(
        source=_reader(_wav(duration_seconds=600, sample_rate=1)),
        filename="max.wav",
        declared_media_type="audio/wav",
    )
    assert allowed.document.metadata["duration_seconds"] == 600.0
    assert provider.calls


def test_missing_provider_config_is_transcription_specific(
    client: TestClient, store: TutorSqliteStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    missing = OpenAITranscriptionProvider(api_key="")
    with pytest.raises(AudioIngestionError) as direct:
        missing.transcribe(_payload(), "fr")
    assert direct.value.code is AudioIngestErrorCode.transcription_not_configured
    assert direct.value.retryable is False
    assert str(direct.value) == MSG_NOT_CONFIGURED

    app.dependency_overrides[get_transcription_provider] = lambda: (
        OpenAITranscriptionProvider()
    )
    response = client.post(
        "/api/tutor/sources/ingest/audio",
        files={"file": ("lecon.wav", _lesson_wav(), "audio/wav")},
    )
    assert response.status_code == 503
    body = response.json()["detail"]
    assert body["code"] == "transcription_not_configured"
    assert body["message"] == MSG_NOT_CONFIGURED
    assert "is not set" not in body["message"]
    assert store.source_documents.list() == []


def test_transient_errors_are_bounded_and_do_not_save(
    store: TutorSqliteStore,
) -> None:
    client = MagicMock()
    client.audio.transcriptions.create.side_effect = APITimeoutError(_request())
    provider = OpenAITranscriptionProvider(client_factory=lambda: client)
    with pytest.raises(AudioIngestionError) as timed_out:
        _service(store, provider).ingest_audio(
            source=_reader(_lesson_wav()),
            filename="lecon.wav",
            declared_media_type="audio/wav",
        )
    assert timed_out.value.code is AudioIngestErrorCode.transcription_timeout
    assert timed_out.value.retryable is True
    assert str(timed_out.value) == MSG_TIMEOUT
    assert "secret" not in str(timed_out.value)
    assert client.audio.transcriptions.create.call_count == MAX_TRANSCRIPTION_ATTEMPTS
    assert store.source_documents.list() == []

    client.audio.transcriptions.create.reset_mock(side_effect=True)
    client.audio.transcriptions.create.side_effect = [
        RateLimitError("secret-upstream", response=_response(429), body=None),
        _openai_lesson(),
    ]
    saved = _service(store, provider).ingest_audio(
        source=_reader(_lesson_wav()),
        filename="lecon.wav",
        declared_media_type="audio/wav",
    )
    assert saved.document.content == LESSON_CONTENT
    assert client.audio.transcriptions.create.call_count == 2
    assert len(store.source_documents.list()) == 1
    kwargs = client.audio.transcriptions.create.call_args.kwargs
    assert kwargs["model"] == "whisper-1"
    assert kwargs["language"] == "fr"
    assert kwargs["response_format"] == "verbose_json"
    assert kwargs["timestamp_granularities"] == ["segment"]
    assert client.audio.translations.create.call_count == 0

    client.audio.transcriptions.create.reset_mock(side_effect=True)
    client.audio.transcriptions.create.side_effect = RateLimitError(
        "secret-upstream", response=_response(429), body=None
    )
    with pytest.raises(AudioIngestionError) as limited:
        provider.transcribe(_payload(), "fr")
    assert limited.value.code is AudioIngestErrorCode.transcription_provider_error
    assert str(limited.value) == MSG_PROVIDER
    assert "secret-upstream" not in str(limited.value)
    assert client.audio.transcriptions.create.call_count == MAX_TRANSCRIPTION_ATTEMPTS


def test_empty_invalid_and_translated_transcripts_are_not_saved(
    store: TutorSqliteStore,
) -> None:
    cases = (
        TranscriptionResult(text="  \n", segments=None),
        TranscriptionResult(
            text="Bonjour",
            segments=(TranscriptSegment("Bonjour", 1.0, 0.5),),
        ),
        TranscriptionResult(
            text="Bonjour",
            segments=(TranscriptSegment("Bonjour", None, 1.0),),
        ),
        TranscriptionResult(
            text="Bonjour",
            segments=(
                TranscriptSegment("Bonjour", 0.0, 1.0),
                TranscriptSegment("suite", None, None),
            ),
        ),
        TranscriptionResult(
            text="Bonjour",
            segments=(TranscriptSegment("Bonjour", 0.0, 1.0),),
            is_translation=True,
        ),
    )
    for result in cases:
        provider = FakeTranscriptionProvider(result)
        with pytest.raises(AudioIngestionError) as caught:
            _ingest(store, provider)
        assert caught.value.retryable is False
        assert caught.value.code in {
            AudioIngestErrorCode.transcript_empty,
            AudioIngestErrorCode.invalid_transcript,
            AudioIngestErrorCode.translated_transcript,
        }
    assert store.source_documents.list() == []

    translated = transcription_from_payload(
        SimpleNamespace(text="Bonjour", language="french", task="translate")
    )
    assert translated.is_translation is True
    client = MagicMock()
    client.audio.transcriptions.create.return_value = SimpleNamespace(
        text="Bonjour",
        language="french",
        task="translate",
        segments=[SimpleNamespace(text="Bonjour", start=0.0, end=1.0)],
    )
    provider = OpenAITranscriptionProvider(client_factory=lambda: client)
    with pytest.raises(AudioIngestionError) as rejected:
        _service(store, provider).ingest_audio(
            source=_reader(_lesson_wav()),
            filename="lecon.wav",
            declared_media_type="audio/wav",
        )
    assert rejected.value.code is AudioIngestErrorCode.translated_transcript
    assert client.audio.transcriptions.create.call_count == 1
    assert store.source_documents.list() == []

    client.audio.transcriptions.create.reset_mock()
    client.audio.transcriptions.create.side_effect = AuthenticationError(
        "sk-test-secret",
        response=_response(401),
        body=None,
    )
    with pytest.raises(AudioIngestionError) as unauthorized:
        provider.transcribe(_payload(), "fr")
    assert unauthorized.value.code is AudioIngestErrorCode.transcription_not_configured
    assert str(unauthorized.value) == MSG_AUTH_FAILED
    assert "sk-test-secret" not in str(unauthorized.value)
    assert client.audio.transcriptions.create.call_count == 1

    client.audio.transcriptions.create.reset_mock()
    client.audio.transcriptions.create.side_effect = None
    client.audio.transcriptions.create.return_value = object()
    with pytest.raises(AudioIngestionError) as invalid:
        provider.transcribe(_payload(), "haw")
    assert invalid.value.code is AudioIngestErrorCode.invalid_transcript
    assert client.audio.transcriptions.create.call_count == 1
    assert "language" not in client.audio.transcriptions.create.call_args.kwargs


def test_same_audio_reuses_source_and_changed_transcript_appends(
    store: TutorSqliteStore,
) -> None:
    moments = iter((FIXED, LATER, AFTER))
    provider = _lesson_provider()
    service = _service(store, provider, clock=lambda: next(moments))
    audio = _lesson_wav()
    created = service.ingest_audio(
        source=_reader(audio),
        filename="lecon.wav",
        declared_media_type="audio/wav",
        title="Leçon",
    )
    reused = service.ingest_audio(
        source=_reader(audio),
        filename="autre.wav",
        declared_media_type="audio/wav",
        title="Ignoré",
    )
    assert reused.action is IngestAction.reuse
    assert reused.document.id == created.document.id
    assert reused.document.title == "Leçon"
    provider.result = TranscriptionResult(
        text="Une nouvelle phrase pour le café.",
        segments=None,
        detected_language="french",
    )
    appended = service.ingest_audio(
        source=_reader(audio),
        filename="lecon.wav",
        declared_media_type="audio/wav",
    )
    assert appended.action is IngestAction.append_version
    assert appended.document.id != created.document.id
    assert appended.document.metadata["prior_source_id"] == created.document.id
    preserved = store.source_documents.get(created.document.id)
    assert preserved is not None
    assert preserved.content == LESSON_CONTENT
    assert len(store.source_documents.list()) == 2


def test_candidate_evidence_maps_to_audio_timestamp(store: TutorSqliteStore) -> None:
    document = _ingest(store, _lesson_provider()).document
    extractor = _CafeExtractor()
    extracted = ExtractionService(extractor).extract(document)
    assert extractor.sources[0].source_type == "audio_transcript"
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


def test_ingest_audio_api_returns_source_and_keeps_manual_create(
    client: TestClient, store: TutorSqliteStore
) -> None:
    manual = client.post(
        "/api/tutor/sources",
        json={"title": "手入力", "content": "ligne\r\n\r\n\r\nsuite"},
    )
    assert manual.status_code == 201
    assert manual.json()["content"] == "ligne\r\n\r\n\r\nsuite"

    provider = _lesson_provider()
    app.dependency_overrides[get_transcription_provider] = lambda: provider
    created = client.post(
        "/api/tutor/sources/ingest/audio",
        files={"file": ("lecon.wav", _lesson_wav(), "audio/wav")},
        data={"title": "Mon cours", "note": "vu", "language": "fr"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    source = body["source"]
    assert body["action"] == "create"
    assert source["source_type"] == "audio_transcript"
    assert source["title"] == "Mon cours"
    assert source["content"] == LESSON_CONTENT
    assert source["segments"][1]["start_seconds"] == 4.5
    assert source["provenance"]["provider"] == "fake"
    assert provider.calls

    again = client.post(
        "/api/tutor/sources/ingest/audio",
        files={"file": ("lecon.wav", _lesson_wav(), "audio/wav")},
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

    plain = client.post(
        "/api/tutor/sources/ingest/audio",
        files={"file": ("lecon.wav", _lesson_wav(), "text/plain")},
    )
    assert plain.status_code == 415
    assert plain.json()["detail"]["code"] == "unsupported_media"

    app.dependency_overrides[get_audio_ingestion_service] = lambda: (
        AudioIngestionService(
            store.source_documents,
            FakeTranscriptionProvider(_lesson_result()),
            max_bytes=8,
        )
    )
    oversized = client.post(
        "/api/tutor/sources/ingest/audio",
        files={"file": ("lecon.wav", b"0123456789", "audio/wav")},
    )
    assert oversized.status_code == 413
    assert oversized.json()["detail"]["code"] == "file_too_large"


def test_raw_audio_and_secrets_are_not_retained(
    tmp_path, store: TutorSqliteStore
) -> None:
    path = tmp_path / "tutor.db"
    file_store = TutorSqliteStore(f"sqlite:///{path}")
    provider = _lesson_provider()
    audio = _lesson_wav()
    try:
        saved = _service(file_store, provider).ingest_audio(
            source=_reader(audio),
            filename="lecon.wav",
            declared_media_type="audio/wav",
        )
        file_store.engine.dispose()
        for item in tmp_path.rglob("*"):
            if item.is_file():
                assert MARKER not in item.read_bytes()
                assert b"sk-" not in item.read_bytes()
        reopened = TutorSqliteStore(f"sqlite:///{path}")
        try:
            loaded = reopened.source_documents.get(saved.document.id)
            assert loaded == saved.document
            assert loaded is not None
            assert _span(loaded, "café").start_seconds == 4.5
        finally:
            reopened.engine.dispose()
    finally:
        file_store.engine.dispose()
    assert store.source_documents.list() == []


def test_audio_ingestion_does_not_require_api_key_or_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(AssertionError, match="network call"):
        socket.getaddrinfo("api.openai.com", 443)
    provider = OpenAITranscriptionProvider(api_key="")
    with pytest.raises(AudioIngestionError) as missing:
        provider.transcribe(_payload(), "fr")
    assert missing.value.code is AudioIngestErrorCode.transcription_not_configured


def test_openapi_exposes_audio_ingest_without_changing_manual_create() -> None:
    with TestClient(app) as http:
        spec = http.get("/openapi.json").json()
    operation = spec["paths"]["/api/tutor/sources/ingest/audio"]["post"]
    assert "multipart/form-data" in operation["requestBody"]["content"]
    create_props = spec["components"]["schemas"]["CreateSourceRequest"]["properties"]
    assert "source_type" not in create_props


def test_audio_modules_keep_the_sdk_behind_the_provider() -> None:
    import app.ingestion.audio as adapter
    import app.ingestion.audio_api as api
    import app.services.audio_ingestion as service

    assert "openai" not in _imported_roots(adapter)
    assert "openai" not in _imported_roots(service)
    assert "openai" in _imported_roots(api)
    forbidden = {"whisper", "faster_whisper", "yt_dlp", "tts_service"}
    for module in (adapter, service, api):
        source = inspect.getsource(module)
        assert "tts_service" not in source
        assert "audio.translations" not in source
        assert "NamedTemporaryFile" not in source
        assert _imported_roots(module).isdisjoint(forbidden), module.__name__
    assert TRANSCRIPTION_VERSION == "openai-audio-transcriptions-v1"


class FakeTranscriptionProvider:
    provider_name = "fake"
    model = "fake-1"
    transcription_version = "fake-transcript-v1"

    def __init__(self, result: TranscriptionResult) -> None:
        self.result = result
        self.calls: list[tuple[str, str, int]] = []
        self.payloads: list[bytes] = []

    def transcribe(
        self, audio: AudioPayload, language_hint: str
    ) -> TranscriptionResult:
        self.calls.append((audio.filename, language_hint, len(audio.data)))
        self.payloads.append(audio.data)
        return self.result


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


def _lesson_result() -> TranscriptionResult:
    return TranscriptionResult(
        text="ignored",
        segments=(
            TranscriptSegment(LESSON[0], 1.0, 4.0),
            TranscriptSegment(LESSON[1], 4.5, 7.0),
        ),
        detected_language="french",
    )


def _lesson_provider() -> FakeTranscriptionProvider:
    return FakeTranscriptionProvider(_lesson_result())


def _service(
    store: TutorSqliteStore,
    provider: TranscriptionProvider,
    *,
    clock=lambda: FIXED,
) -> AudioIngestionService:
    return AudioIngestionService(store.source_documents, provider, clock=clock)


def _ingest(
    store: TutorSqliteStore,
    provider: FakeTranscriptionProvider,
    *,
    audio: bytes | None = None,
    filename: str = "lecon.wav",
    media_type: str = "audio/wav",
    language: str = "fr",
):
    data = _lesson_wav() if audio is None else audio
    return _service(store, provider).ingest_audio(
        source=_reader(data),
        filename=filename,
        declared_media_type=media_type,
        language=language,
    )


def _span(document: SourceDocument, word: str):
    start = document.content.index(word)
    return segment_for_span(document.segments, start=start, end=start + len(word))


def _reader(data: bytes) -> BytesIO:
    return BytesIO(data)


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _lesson_wav() -> bytes:
    return _wav(duration_seconds=1.0, sample_rate=8, payload=MARKER)


def _wav(
    *,
    duration_seconds: float,
    sample_rate: int,
    payload: bytes = b"",
) -> bytes:
    channels = 1
    bits = 16
    block_align = channels * bits // 8
    byte_rate = sample_rate * block_align
    data_size = int(round(duration_seconds * byte_rate))
    if len(payload) > data_size:
        data = payload
    else:
        data = payload + bytes(data_size - len(payload))
    fmt = struct.pack("<HHIIHH", 1, channels, sample_rate, byte_rate, block_align, bits)
    fmt_chunk = b"fmt " + len(fmt).to_bytes(4, "little") + fmt
    data_chunk = b"data" + len(data).to_bytes(4, "little") + data
    body = b"WAVE" + fmt_chunk + data_chunk
    return b"RIFF" + len(body).to_bytes(4, "little") + body


def _mp3() -> bytes:
    return b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x00"


def _mp4(*, duration_seconds: int, timescale: int = 1000) -> bytes:
    ftyp_body = b"isom" + b"\x00\x00\x00\x00" + b"isom"
    ftyp = (8 + len(ftyp_body)).to_bytes(4, "big") + b"ftyp" + ftyp_body
    mvhd_body = (
        b"\x00\x00\x00\x00"
        + b"\x00\x00\x00\x00"
        + b"\x00\x00\x00\x00"
        + timescale.to_bytes(4, "big")
        + (duration_seconds * timescale).to_bytes(4, "big")
    )
    mvhd = (8 + len(mvhd_body)).to_bytes(4, "big") + b"mvhd" + mvhd_body
    return ftyp + mvhd


def _payload() -> AudioPayload:
    return AudioPayload(_lesson_wav(), "lecon.wav", "audio/wav")


def _openai_lesson() -> SimpleNamespace:
    return SimpleNamespace(
        text=LESSON_CONTENT,
        language="french",
        task="transcribe",
        segments=[
            SimpleNamespace(text=LESSON[0], start=1.0, end=4.0),
            SimpleNamespace(text=LESSON[1], start=4.5, end=7.0),
        ],
    )


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://api.openai.com/v1/audio/transcriptions")


def _response(status_code: int) -> httpx.Response:
    return httpx.Response(status_code, request=_request())


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
