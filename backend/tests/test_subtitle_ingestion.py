"""SRT / VTT を時刻 provenance 付き SourceDocument にする（Issue #192）。

ネットワークも音声認識も使わない。
"""

from __future__ import annotations

import ast
import inspect
import socket
from collections.abc import Iterator
from datetime import UTC, datetime
from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_learning_item_extractor, get_tutor_store
from app.domain.source_ingestion import (
    INGESTION_VERSION,
    IngestAction,
    SourceIngestionError,
    content_digest,
    segment_for_span,
)
from app.domain.tutor import SourceDocument, read_source_evidence
from app.ingestion.subtitle import SUBTITLE_ADAPTER_VERSION
from app.ingestion.subtitle_errors import SubtitleIngestErrorCode
from app.ingestion.subtitle_text import MAX_SUBTITLE_BYTES
from app.ingestion.timed_text import strip_cue_markup
from app.main import app
from app.repositories.sqlite import TutorSqliteStore
from app.services.extraction_schema import ExtractedCandidate, ExtractedEvidenceSpan
from app.services.extraction_service import ExtractionService
from app.services.extractors import ExtractorResult
from app.services.subtitle_ingestion import SubtitleIngestionService

FIXED = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
LATER = datetime(2026, 4, 2, 12, 0, tzinfo=UTC)
AFTER = datetime(2026, 4, 3, 12, 0, tzinfo=UTC)

SRT_LESSON = """\
1
00:00:01,000 --> 00:00:04,000
Aujourd'hui, l'élève apprend.

2
00:00:04,500 --> 00:00:07,000
Il prend un café.
"""
SRT_CONTENT = "Aujourd'hui, l'élève apprend.\n\nIl prend un café."

VTT_LESSON = """\
WEBVTT
X-TIMESTAMP-MAP=MPEGTS:900000,LOCAL:00:00:00.000

NOTE ne-pas-importer

STYLE
::cue { color: white }

00:00:01.000 --> 00:00:03.000
<v Marie>Bonjour, ça va ?</v>

00:01.000 --> 00:04.000 align:start position:0%
<i>café</i> aujourd’hui
"""
VTT_CONTENT = "Bonjour, ça va ?\n\ncafé aujourd’hui"


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


def test_subtitle_ingestion_does_not_use_network() -> None:
    with pytest.raises(AssertionError, match="network call"):
        socket.getaddrinfo("example.com", 443)


def test_cue_markup_keeps_one_speaker_and_french_text() -> None:
    plain, speaker = strip_cue_markup("<v Marie>Bonjour, ça va ?</v>")
    assert plain == "Bonjour, ça va ?"
    assert speaker == "Marie"
    plain, speaker = strip_cue_markup("<v.Luc>Salut</v>")
    assert plain == "Salut"
    assert speaker == "Luc"
    plain, speaker = strip_cue_markup("<v Marie>A</v> <v Luc>B</v>")
    assert speaker is None
    assert plain == "A B"
    plain, speaker = strip_cue_markup("<i>café</i> l&#39;élève {\\an8}")
    assert "café" in plain
    assert "l'élève" in plain
    assert "<" not in plain
    assert speaker is None


def test_srt_and_vtt_keep_accents_apostrophes_speakers_and_order(
    store: TutorSqliteStore,
) -> None:
    assert MAX_SUBTITLE_BYTES == 2_000_000
    srt = _service(store).ingest_subtitle(
        source=BytesIO(SRT_LESSON.encode()),
        filename=r"..\..\leçon.srt",
        declared_media_type="application/x-subrip; charset=utf-8",
        note="depuis le srt",
    )
    document = srt.document
    assert srt.created is True
    assert srt.action is IngestAction.create
    assert document.source_type == "subtitle"
    assert document.title == "leçon"
    assert document.language == "fr"
    assert document.content == SRT_CONTENT
    assert "l'élève" in document.content
    assert "café" in document.content
    assert document.content_hash == content_digest(document.content)
    assert document.ingestion_version == INGESTION_VERSION
    assert [segment.speaker for segment in document.segments] == [None, None]
    assert document.segments[0].start_seconds == 1.0
    assert document.segments[0].end_seconds == 4.0
    assert document.segments[1].start_seconds == 4.5
    assert document.segments[1].end_seconds == 7.0
    _assert_slices(document, SRT_CONTENT.split("\n\n"))
    provenance = document.provenance
    assert provenance is not None
    assert provenance.filename == "leçon.srt"
    assert provenance.mime_type == "application/x-subrip"
    assert provenance.adapter_version == SUBTITLE_ADAPTER_VERSION
    assert provenance.canonical_locator == document.metadata["file_sha256"]
    assert str(provenance.canonical_locator).startswith("sha256:")
    assert provenance.canonical_locator != document.content_hash
    assert document.metadata["format"] == "srt"
    assert document.metadata["cue_count"] == 2
    assert document.metadata["empty_cue_count"] == 0
    assert document.metadata["note"] == "depuis le srt"
    assert "../" not in document.model_dump_json()

    vtt = _service(store).ingest_subtitle(
        source=BytesIO(VTT_LESSON.encode()),
        filename="leçon.vtt",
        declared_media_type="text/vtt",
    )
    spoken = vtt.document
    assert spoken.content == VTT_CONTENT
    assert "ne-pas-importer" not in spoken.content
    assert "color" not in spoken.content
    assert "X-TIMESTAMP-MAP" not in spoken.content
    assert spoken.segments[0].speaker == "Marie"
    assert spoken.segments[0].start_seconds == 1.0
    assert spoken.segments[0].end_seconds == 3.0
    assert spoken.segments[1].speaker is None
    assert spoken.segments[1].start_seconds == 1.0
    assert spoken.segments[1].end_seconds == 4.0
    assert "aujourd’hui" in spoken.content
    assert spoken.metadata["format"] == "vtt"
    assert spoken.provenance is not None
    assert spoken.provenance.mime_type == "text/vtt"

    again = _service(store).ingest_subtitle(
        source=BytesIO(SRT_LESSON.encode()),
        filename="leçon.srt",
        declared_media_type="text/plain",
    )
    assert again.document.content == srt.document.content
    assert again.document.segments == srt.document.segments


def test_combining_accent_is_normalized_without_replacing_apostrophes(
    store: TutorSqliteStore,
) -> None:
    raw = "1\n00:00:01,000 --> 00:00:02,000\ncafe\u0301 aujourd'hui\n"
    document = (
        _service(store)
        .ingest_subtitle(
            source=BytesIO(raw.encode()),
            filename="accents.srt",
            declared_media_type=None,
        )
        .document
    )
    assert document.content == "café aujourd'hui"
    assert _span(document, "café").start_seconds == 1.0


def test_malformed_timestamps_are_rejected_without_saving(
    store: TutorSqliteStore,
) -> None:
    service = _service(store)
    cases = [
        "1\n00:00:05,000 --> 00:00:01,000\nSUPERSECRET\n",
        "1\n00:99:00,000 --> 00:99:05,000\nBonjour\n",
        "1\nnot a timestamp\nBonjour\n",
        "1\n00:00:01,000 --> 00:00:02,000\n\n2\nbad\n",
        "WEBVTT\n\n00:00:01.000 --> 00:00:00.500\nSECRET\n",
    ]
    for raw in cases:
        suffix = "vtt" if raw.startswith("WEBVTT") else "srt"
        with pytest.raises(Exception) as rejected:
            service.ingest_subtitle(
                source=BytesIO(raw.encode()),
                filename=f"bad.{suffix}",
                declared_media_type=None,
            )
        assert getattr(rejected.value, "code", None) is (
            SubtitleIngestErrorCode.malformed_subtitle
        )
        assert "SUPERSECRET" not in str(rejected.value)
        assert "SECRET" not in str(rejected.value)
    assert store.source_documents.list() == []

    with pytest.raises(Exception) as swapped:
        service.ingest_subtitle(
            source=BytesIO(b"WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nBonjour\n"),
            filename="lesson.srt",
            declared_media_type="text/plain",
        )
    assert swapped.value.code is SubtitleIngestErrorCode.malformed_subtitle
    with pytest.raises(Exception) as binary:
        service.ingest_subtitle(
            source=BytesIO(b"\xff\xfeSECRET"),
            filename="lesson.srt",
            declared_media_type=None,
        )
    assert binary.value.code is SubtitleIngestErrorCode.malformed_subtitle
    assert "SECRET" not in str(binary.value)


def test_overlapping_cues_keep_file_order_and_timecodes(
    store: TutorSqliteStore,
) -> None:
    raw = """\
1
00:00:05,000 --> 00:00:08,000
deuxième

2
00:00:01,000 --> 00:00:04,000
premier
"""
    document = (
        _service(store)
        .ingest_subtitle(
            source=BytesIO(raw.encode()),
            filename="overlap.srt",
            declared_media_type="application/octet-stream",
        )
        .document
    )
    assert document.content == "deuxième\n\npremier"
    assert document.segments[0].start_seconds == 5.0
    assert document.segments[0].end_seconds == 8.0
    assert document.segments[1].start_seconds == 1.0
    assert document.segments[1].end_seconds == 4.0
    again = (
        _service(store)
        .ingest_subtitle(
            source=BytesIO(raw.encode()),
            filename="overlap.srt",
            declared_media_type=None,
        )
        .document
    )
    assert again.content == document.content
    assert [(item.start_seconds, item.end_seconds) for item in again.segments] == [
        (item.start_seconds, item.end_seconds) for item in document.segments
    ]


def test_character_offset_maps_to_timestamp(store: TutorSqliteStore) -> None:
    document = _ingest_srt(store)
    eleve = _span(document, "élève")
    cafe = _span(document, "café")
    assert eleve.start_seconds == 1.0
    assert eleve.end_seconds == 4.0
    assert cafe.start_seconds == 4.5
    assert cafe.end_seconds == 7.0
    assert document.content[eleve.normalized_start : eleve.normalized_end].startswith(
        "Aujourd'hui"
    )
    gap = document.segments[0].normalized_end
    with pytest.raises(SourceIngestionError):
        segment_for_span(document.segments, start=gap, end=gap + 2)


def test_candidate_evidence_maps_to_timecode(store: TutorSqliteStore) -> None:
    document = _ingest_srt(store)
    extractor = _CafeExtractor()
    extracted = ExtractionService(extractor).extract(document)
    assert extractor.sources[0].source_type == "subtitle"
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


def test_same_subtitle_reuses_and_other_bytes_create_a_new_source(
    store: TutorSqliteStore,
) -> None:
    moments = iter((FIXED, LATER, AFTER))
    service = _service(store, clock=lambda: next(moments))
    created = service.ingest_subtitle(
        source=BytesIO(SRT_LESSON.encode()),
        filename="leçon.srt",
        declared_media_type="application/x-subrip",
        title="Cours",
    )
    reused = service.ingest_subtitle(
        source=BytesIO(SRT_LESSON.encode()),
        filename="autre.srt",
        declared_media_type="text/plain",
        title="Ignoré",
    )
    assert reused.action is IngestAction.reuse
    assert reused.created is False
    assert reused.document.id == created.document.id
    assert reused.document.title == "Cours"
    other = "1\n00:00:01,000 --> 00:00:02,000\nAutre phrase assez longue.\n"
    created_other = service.ingest_subtitle(
        source=BytesIO(other.encode()),
        filename="autre.srt",
        declared_media_type=None,
    )
    assert created_other.action is IngestAction.create
    assert created_other.document.id != created.document.id
    assert len(store.source_documents.list()) == 2


def test_subtitle_source_survives_database_reopen(tmp_path) -> None:
    path = tmp_path / "tutor.db"
    store = TutorSqliteStore(f"sqlite:///{path}")
    try:
        saved = _service(store).ingest_subtitle(
            source=BytesIO(SRT_LESSON.encode()),
            filename="leçon.srt",
            declared_media_type="application/x-subrip",
        )
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


def test_ingest_subtitle_api_returns_source_and_keeps_manual_create(
    client: TestClient, store: TutorSqliteStore
) -> None:
    manual = client.post(
        "/api/tutor/sources",
        json={"title": "手入力", "content": "ligne\r\n\r\n\r\nsuite"},
    )
    assert manual.status_code == 201
    assert manual.json()["content"] == "ligne\r\n\r\n\r\nsuite"

    created = client.post(
        "/api/tutor/sources/ingest/subtitle",
        files={"file": ("../../leçon.srt", SRT_LESSON.encode(), "text/plain")},
        data={"title": "Mon cours", "note": "depuis le srt", "language": "fr"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["action"] == "create"
    assert body["created"] is True
    source = body["source"]
    assert source["source_type"] == "subtitle"
    assert source["title"] == "Mon cours"
    assert source["content"] == SRT_CONTENT
    assert source["provenance"]["filename"] == "leçon.srt"
    assert source["metadata"]["format"] == "srt"
    assert source["segments"][1]["start_seconds"] == 4.5
    assert "../" not in created.text

    detail = client.get(f"/api/tutor/sources/{source['id']}")
    assert detail.status_code == 200
    assert detail.json()["content"] == SRT_CONTENT

    again = client.post(
        "/api/tutor/sources/ingest/subtitle",
        files={"file": ("leçon.srt", SRT_LESSON.encode(), "application/x-subrip")},
    )
    assert again.status_code == 200
    assert again.json()["action"] == "reuse"
    assert again.json()["source"]["id"] == source["id"]

    app.dependency_overrides[get_learning_item_extractor] = lambda: _CafeExtractor()
    extracted = client.post(f"/api/tutor/sources/{source['id']}/candidates/extract")
    assert extracted.status_code == 200, extracted.text
    candidate = extracted.json()["created"][0]
    assert candidate["evidence_text"] == "café"
    span = candidate["evidence_span"]
    loaded = store.source_documents.get(source["id"])
    assert loaded is not None
    mapped = segment_for_span(loaded.segments, start=span["start"], end=span["end"])
    assert mapped.start_seconds == 4.5
    assert mapped.end_seconds == 7.0


def test_ingest_subtitle_api_distinguishes_errors(
    client: TestClient, store: TutorSqliteStore
) -> None:
    malformed = client.post(
        "/api/tutor/sources/ingest/subtitle",
        files={
            "file": (
                "notes.srt",
                b"1\n00:00:05,000 --> 00:00:01,000\nSUPERSECRET\n",
                "application/x-subrip",
            )
        },
    )
    assert malformed.status_code == 400
    assert malformed.json()["detail"]["code"] == "malformed_subtitle"
    assert "SUPERSECRET" not in malformed.text

    empty = client.post(
        "/api/tutor/sources/ingest/subtitle",
        files={"file": ("empty.vtt", b"WEBVTT\n", "text/vtt")},
    )
    assert empty.status_code == 422
    assert empty.json()["detail"]["code"] == "subtitle_empty"

    html = client.post(
        "/api/tutor/sources/ingest/subtitle",
        files={"file": ("leçon.srt", SRT_LESSON.encode(), "text/html")},
    )
    assert html.status_code == 415
    assert html.json()["detail"]["code"] == "unsupported_media"

    wrong_extension = client.post(
        "/api/tutor/sources/ingest/subtitle",
        files={"file": ("notes.txt", SRT_LESSON.encode(), "text/plain")},
    )
    assert wrong_extension.status_code == 415

    from app.api.deps import get_subtitle_ingestion_service

    app.dependency_overrides[get_subtitle_ingestion_service] = lambda: (
        SubtitleIngestionService(store.source_documents, max_bytes=8)
    )
    too_big = client.post(
        "/api/tutor/sources/ingest/subtitle",
        files={"file": ("leçon.srt", SRT_LESSON.encode(), "text/plain")},
    )
    assert too_big.status_code == 413
    assert too_big.json()["detail"]["code"] == "file_too_large"
    assert store.source_documents.list() == []


def test_openapi_exposes_subtitle_ingest_without_changing_manual_create() -> None:
    with TestClient(app) as http:
        spec = http.get("/openapi.json").json()
    operation = spec["paths"]["/api/tutor/sources/ingest/subtitle"]["post"]
    assert "multipart/form-data" in operation["requestBody"]["content"]
    create_props = spec["components"]["schemas"]["CreateSourceRequest"]["properties"]
    assert "source_type" not in create_props
    assert "file" not in create_props
    assert "/api/tutor/sources/subtitle" not in spec["paths"]


def test_subtitle_modules_do_not_fetch_or_transcribe() -> None:
    import app.domain.source_ingestion as domain
    import app.ingestion.subtitle as adapter
    import app.ingestion.subtitle_text as rules
    import app.ingestion.timed_text as timed
    import app.services.subtitle_ingestion as service

    forbidden = {
        "requests",
        "httpx",
        "youtube_transcript_api",
        "yt_dlp",
        "pytube",
        "youtube_dl",
        "whisper",
        "faster_whisper",
        "openai",
    }
    for module in (domain, rules, timed, adapter, service):
        assert _imported_roots(module).isdisjoint(forbidden), module.__name__


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


def _service(
    store: TutorSqliteStore, *, clock=lambda: FIXED
) -> SubtitleIngestionService:
    return SubtitleIngestionService(store.source_documents, clock=clock)


def _ingest_srt(store: TutorSqliteStore) -> SourceDocument:
    return (
        _service(store)
        .ingest_subtitle(
            source=BytesIO(SRT_LESSON.encode()),
            filename="leçon.srt",
            declared_media_type="application/x-subrip",
        )
        .document
    )


def _span(document: SourceDocument, word: str):
    start = document.content.index(word)
    return segment_for_span(document.segments, start=start, end=start + len(word))


def _assert_slices(document: SourceDocument, pieces: list[str]) -> None:
    for segment, piece in zip(document.segments, pieces, strict=True):
        extracted = document.content[segment.normalized_start : segment.normalized_end]
        assert extracted == piece


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
