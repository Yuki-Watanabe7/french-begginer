"""Source ingestion 共通契約（Issue #189）。"""

from __future__ import annotations

import ast
import hashlib
import inspect
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.domain.source_ingestion import (
    INGESTION_VERSION,
    MAX_SOURCE_TEXT_CHARS,
    SOURCE_TYPES,
    IngestAction,
    IngestionFailureKind,
    SourceIngestionError,
    SourceIngestionRequest,
    SourceSegment,
    SourceSegmentDraft,
    StoredSourceIdentity,
    assemble_ingestion_result,
    content_digest,
    ingest_manual_text,
    ingest_source,
    normalize_source_text,
    plan_source_ingestion,
    provider_failure,
    provider_timeout,
    segment_for_span,
)
from app.domain.tutor import (
    EvidenceSpan,
    SourceDocument,
    read_source_evidence,
    source_document_from_ingestion,
)
from app.persistence.schema import CURRENT_SCHEMA_VERSION, get_schema_version
from app.repositories.sqlite import TutorSqliteStore
from app.services.source_ingestion_service import SourceIngestionService

FIXED = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
LATER = datetime(2026, 4, 2, 12, 0, tzinfo=UTC)

_BONJOUR_SHA256 = (
    "sha256:2cb4b1431b84ec15d35ed83bb927e27e8967d75f4bcd9cc4b25c8d879ae23e18"
)


def test_source_types_cover_phase6_contract():
    assert SOURCE_TYPES == (
        "manual_text",
        "web_url",
        "pdf",
        "youtube_transcript",
        "subtitle",
        "audio_transcript",
        "conversation_log",
    )


def test_content_digest_is_stable_sha256():
    assert content_digest("bonjour") == _BONJOUR_SHA256
    assert content_digest("bonjour") == (
        "sha256:" + hashlib.sha256(b"bonjour").hexdigest()
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("café", "café"),
        ("cafe\u0301", "café"),
        ("\ufeffBonjour", "Bonjour"),
        ("a\r\nb", "a\nb"),
        ("a\rb", "a\nb"),
        ("a\u2028b", "a\nb"),
        ("a\n\n\n\nb", "a\n\nb"),
        ("a  \n\t b \t", "a\n\t b"),
        ("  a  ", "a"),
    ],
)
def test_normalize_source_text_is_idempotent(raw: str, expected: str):
    once = normalize_source_text(raw)
    assert once == expected
    assert normalize_source_text(once) == once


def test_manual_text_ingestion_is_deterministic():
    request = _manual_request(text="Bonjour\r\n\r\n\r\nle monde")
    first = ingest_manual_text(request, ingested_at=FIXED)
    second = ingest_manual_text(request, ingested_at=FIXED)
    assert first == second
    assert first.normalized_content == "Bonjour\n\nle monde"
    assert first.content_hash == content_digest(first.normalized_content)
    assert first.ingestion_version == INGESTION_VERSION
    assert first.provenance.ingestion_version == INGESTION_VERSION
    assert first.provenance.adapter_version == "manual-text-v1"
    assert first.provenance.ingested_at == FIXED
    assert first.metadata["note"] == "se rendre compte"
    assert normalize_source_text(first.normalized_content) == first.normalized_content


def test_original_hash_tracks_pre_normalization_text():
    raw = "cafe\u0301\r\n"
    result = ingest_manual_text(_manual_request(text=raw), ingested_at=FIXED)
    assert result.normalized_content == "café"
    assert result.provenance.original_content_hash == content_digest(raw)
    assert result.provenance.original_content_hash != result.content_hash


def test_normalized_span_maps_back_to_page_time_and_speaker():
    result = assemble_ingestion_result(
        source_type="pdf",
        title="Leçon",
        language="fr",
        drafts=[
            SourceSegmentDraft(text="Page un.", page_number=1),
            SourceSegmentDraft(
                text="Le cafe\u0301 est prêt.",
                page_number=2,
                external_locator="page-2",
            ),
        ],
        adapter_version="pdf-test-v1",
        ingested_at=FIXED,
        canonical_locator="file://lesson.pdf",
        filename="lesson.pdf",
        mime_type="application/pdf",
    )
    assert result.normalized_content == "Page un.\n\nLe café est prêt."
    fragment = "café"
    start = result.normalized_content.index(fragment)
    end = start + len(fragment)
    segment = segment_for_span(result.segments, start=start, end=end)
    assert segment.page_number == 2
    assert segment.external_locator == "page-2"

    document = source_document_from_ingestion(result)
    assert document.content == result.normalized_content
    assert document.content_hash == result.content_hash
    evidence = EvidenceSpan(start=start, end=end)
    assert read_source_evidence(document.content, evidence) == fragment
    assert normalize_source_text(document.content) == document.content
    assert document.content[evidence.start : evidence.end] == fragment

    spoken = assemble_ingestion_result(
        source_type="conversation_log",
        title="Dialogue",
        language="fr",
        drafts=[
            SourceSegmentDraft(text="Bonjour", speaker="Marie"),
            SourceSegmentDraft(text="Salut", speaker="Luc"),
        ],
        adapter_version="conversation-log-test-v1",
        ingested_at=FIXED,
    )
    salut = spoken.normalized_content.index("Salut")
    speaker = segment_for_span(spoken.segments, start=salut, end=salut + len("Salut"))
    assert speaker.speaker == "Luc"

    timed = assemble_ingestion_result(
        source_type="subtitle",
        title="Sous-titres",
        language="fr",
        drafts=[
            SourceSegmentDraft(text="Bonjour", start_seconds=1.25, end_seconds=2.5)
        ],
        adapter_version="subtitle-test-v1",
        ingested_at=FIXED,
    )
    cue = segment_for_span(timed.segments, start=0, end=len("Bonjour"))
    assert cue.start_seconds == 1.25
    assert cue.end_seconds == 2.5


def test_invalid_segment_ranges_are_rejected():
    with pytest.raises(ValidationError):
        SourceSegment(normalized_start=4, normalized_end=4)
    with pytest.raises(ValidationError):
        SourceSegment(normalized_start=0, normalized_end=2, start_seconds=1.0)
    with pytest.raises(ValidationError):
        SourceSegment(
            normalized_start=0,
            normalized_end=2,
            start_seconds=2.0,
            end_seconds=1.0,
        )
    with pytest.raises(ValidationError):
        SourceDocument(
            title="t",
            content="abcd",
            segments=[
                SourceSegment(normalized_start=0, normalized_end=2),
                SourceSegment(normalized_start=1, normalized_end=3),
            ],
        )
    content = "Page un.\n\nPage deux."
    result = assemble_ingestion_result(
        source_type="pdf",
        title="Pages",
        language="fr",
        drafts=[
            SourceSegmentDraft(text="Page un.", page_number=1),
            SourceSegmentDraft(text="Page deux.", page_number=2),
        ],
        adapter_version="pdf-test-v1",
        ingested_at=FIXED,
    )
    assert result.normalized_content == content
    gap = content.index("\n\n")
    with pytest.raises(SourceIngestionError) as exc:
        segment_for_span(result.segments, start=gap, end=gap + 2)
    assert exc.value.kind is IngestionFailureKind.validation
    with pytest.raises(SourceIngestionError):
        segment_for_span(result.segments, start=0, end=len(content))


def test_evidence_span_keeps_stored_offsets_without_renormalizing():
    raw = "cafe\u0301"
    document = SourceDocument(title="t", content=raw)
    span = EvidenceSpan(start=0, end=len(raw))
    assert read_source_evidence(document.content, span) == raw
    assert normalize_source_text(raw) == "café"
    assert read_source_evidence(document.content, span) != "café"
    assert document.content_hash is None
    assert document.ingestion_version is None


def test_same_input_and_version_reuse_changed_content_appends_history():
    request = _manual_request(locator="manual://article")
    result = ingest_manual_text(request, ingested_at=FIXED)
    identity = StoredSourceIdentity(
        id="src-1",
        source_type=result.source_type,
        canonical_locator="manual://article",
        content_hash=result.content_hash,
        ingestion_version=result.ingestion_version,
        created_at=FIXED,
    )
    reused = plan_source_ingestion([identity], result)
    assert reused.action is IngestAction.reuse
    assert reused.existing_id == "src-1"

    changed = ingest_manual_text(
        _manual_request(text="Bonjour!", locator="manual://article"),
        ingested_at=LATER,
    )
    appended = plan_source_ingestion([identity], changed)
    assert appended.action is IngestAction.append_version
    assert appended.prior_source_id == "src-1"

    older_version = StoredSourceIdentity(
        id="src-0",
        source_type=result.source_type,
        canonical_locator="manual://article",
        content_hash=result.content_hash,
        ingestion_version="source-ingest-v0",
        created_at=FIXED - timedelta(days=1),
    )
    versioned = plan_source_ingestion([older_version], result)
    assert versioned.action is IngestAction.append_version
    assert versioned.prior_source_id == "src-0"

    unlocated = ingest_manual_text(_manual_request(), ingested_at=FIXED)
    assert plan_source_ingestion([identity], unlocated).action is IngestAction.create


def test_limits_media_secrets_and_raw_payload_are_rejected():
    oversized = _manual_request(text="a" * (MAX_SOURCE_TEXT_CHARS + 1))
    with pytest.raises(SourceIngestionError) as too_big:
        ingest_manual_text(oversized, ingested_at=FIXED)
    assert too_big.value.kind is IngestionFailureKind.input_too_large
    assert too_big.value.retryable is False

    exact = ingest_manual_text(
        _manual_request(text="a" * MAX_SOURCE_TEXT_CHARS), ingested_at=FIXED
    )
    assert len(exact.normalized_content) == MAX_SOURCE_TEXT_CHARS

    with pytest.raises(SourceIngestionError) as secret:
        ingest_manual_text(
            _manual_request(metadata={"api_key": "sk-test"}), ingested_at=FIXED
        )
    assert secret.value.kind is IngestionFailureKind.validation
    with pytest.raises(SourceIngestionError):
        ingest_manual_text(
            _manual_request(metadata={"provider": {"access_token": "x"}}),
            ingested_at=FIXED,
        )
    allowed = ingest_manual_text(
        _manual_request(
            note="le token n'est pas une clé",
            metadata={"tokenizer": "whitespace"},
        ),
        ingested_at=FIXED,
    )
    assert allowed.metadata["note"] == "le token n'est pas une clé"
    assert allowed.metadata["tokenizer"] == "whitespace"

    with pytest.raises(SourceIngestionError) as html:
        ingest_manual_text(
            _manual_request(text="<!DOCTYPE html><html><body>Bonjour</body></html>"),
            ingested_at=FIXED,
        )
    assert html.value.kind is IngestionFailureKind.validation
    with pytest.raises(SourceIngestionError):
        assemble_ingestion_result(
            source_type="pdf",
            title="PDF",
            language="fr",
            drafts=[SourceSegmentDraft(text="%PDF-1.7\n1 0 obj")],
            adapter_version="pdf-test-v1",
            ingested_at=FIXED,
        )
    prose = ingest_manual_text(
        _manual_request(text="3 < 4, donc c'est faux."), ingested_at=FIXED
    )
    assert prose.normalized_content == "3 < 4, donc c'est faux."

    with pytest.raises(SourceIngestionError) as media:
        ingest_source(
            SourceIngestionRequest(
                source_type="pdf",
                title="Notes",
                filename="notes.pdf",
                mime_type="text/html",
            ),
            ingested_at=FIXED,
        )
    assert media.value.kind is IngestionFailureKind.unsupported_media
    with pytest.raises(SourceIngestionError) as extension:
        ingest_source(
            SourceIngestionRequest(
                source_type="pdf",
                title="Notes",
                filename="notes.exe",
                mime_type="application/pdf",
            ),
            ingested_at=FIXED,
        )
    assert extension.value.kind is IngestionFailureKind.unsupported_media

    with pytest.raises(SourceIngestionError) as file_url:
        ingest_source(
            SourceIngestionRequest(
                source_type="web_url",
                title="Local",
                locator="file:///tmp/secret.txt",
            ),
            ingested_at=FIXED,
        )
    assert file_url.value.kind is IngestionFailureKind.validation
    with pytest.raises(SourceIngestionError):
        ingest_source(
            SourceIngestionRequest(
                source_type="web_url",
                title="Secret",
                locator="https://user:pass@example.com/a",
            ),
            ingested_at=FIXED,
        )


def test_unimplemented_adapters_are_classified_without_fetching():
    with pytest.raises(SourceIngestionError) as missing:
        ingest_source(
            SourceIngestionRequest(
                source_type="pdf",
                title="Notes",
                filename="notes.PDF",
                mime_type="application/pdf",
            ),
            ingested_at=FIXED,
        )
    assert missing.value.kind is IngestionFailureKind.not_implemented
    assert missing.value.retryable is False

    with pytest.raises(SourceIngestionError) as subtitle:
        ingest_source(
            SourceIngestionRequest(
                source_type="subtitle", title="Cues", filename="lecon.srt"
            ),
            ingested_at=FIXED,
        )
    assert subtitle.value.kind is IngestionFailureKind.not_implemented

    timeout = provider_timeout("timed out")
    assert timeout.kind is IngestionFailureKind.timeout
    assert timeout.retryable is True
    failure = provider_failure("unavailable")
    assert failure.kind is IngestionFailureKind.provider
    assert failure.retryable is True


def test_adapter_protocol_can_normalize_without_leaving_domain():
    class _ConversationAdapter:
        source_type = "conversation_log"
        adapter_version = "conversation-log-test-v1"

        def ingest(self, request: SourceIngestionRequest, *, ingested_at: datetime):
            assert request.text is not None
            return assemble_ingestion_result(
                source_type="conversation_log",
                title=request.title or "Dialogue",
                language=request.language,
                drafts=[
                    SourceSegmentDraft(text="Bonjour", speaker="Marie"),
                    SourceSegmentDraft(text=request.text, speaker="Luc"),
                ],
                adapter_version=self.adapter_version,
                ingested_at=ingested_at,
                canonical_locator=request.locator,
            )

    result = ingest_source(
        SourceIngestionRequest(
            source_type="conversation_log",
            title="Dialogue",
            text="Salut",
            locator="conversation://1",
        ),
        ingested_at=FIXED,
        adapter=_ConversationAdapter(),
    )
    assert result.normalized_content == "Bonjour\n\nSalut"
    assert result.segments[1].speaker == "Luc"
    assert result.provenance.adapter_version == "conversation-log-test-v1"


def test_commit_reuses_same_locator_and_appends_when_content_changes(tmp_path: Path):
    store = TutorSqliteStore(f"sqlite:///{tmp_path / 'ingest.db'}")
    times = iter(
        (
            FIXED,
            LATER,
            LATER + timedelta(minutes=1),
            LATER + timedelta(minutes=2),
        )
    )
    service = SourceIngestionService(store.source_documents, clock=lambda: next(times))
    request = _manual_request(locator="manual://article")

    first = service.ingest_manual_text(request)
    second = service.ingest_manual_text(request)
    assert first.created is True
    assert first.action is IngestAction.create
    assert second.created is False
    assert second.action is IngestAction.reuse
    assert second.document.id == first.document.id
    assert len(store.source_documents.list()) == 1

    third = service.ingest_manual_text(
        _manual_request(text="Au revoir", locator="manual://article")
    )
    assert third.created is True
    assert third.action is IngestAction.append_version
    assert third.document.id != first.document.id
    assert third.document.metadata["prior_source_id"] == first.document.id
    assert third.document.content == "Au revoir"
    preserved = store.source_documents.get(first.document.id)
    assert preserved is not None
    assert preserved.content == first.document.content
    assert preserved.metadata == first.document.metadata

    unrelated = service.ingest_manual_text(_manual_request(text="Autre"))
    assert unrelated.action is IngestAction.create
    assert unrelated.document.id != third.document.id
    assert (
        store.source_documents.list_by_locator(
            source_type="manual_text", canonical_locator="manual://article"
        )
    )[0].id == first.document.id

    store.engine.dispose()
    reopened = TutorSqliteStore(f"sqlite:///{tmp_path / 'ingest.db'}")
    assert get_schema_version(reopened.engine) == CURRENT_SCHEMA_VERSION
    loaded = reopened.source_documents.get(third.document.id)
    assert loaded == third.document
    assert loaded is not None
    assert loaded.provenance is not None
    assert loaded.provenance.canonical_locator == "manual://article"
    assert loaded.segments[0].normalized_end == len(loaded.content)
    reopened.engine.dispose()


def test_ingestion_modules_do_not_import_adapter_libraries():
    forbidden = {
        "httpx",
        "requests",
        "urllib",
        "openai",
        "pypdf",
        "pdfminer",
        "fitz",
        "bs4",
        "pytube",
        "youtube_transcript_api",
        "aiohttp",
    }
    import app.domain.source_ingestion as ingestion
    import app.services.source_ingestion_service as service

    assert _imported_roots(ingestion).isdisjoint(forbidden)
    assert _imported_roots(ingestion).isdisjoint(
        {
            "app.services",
            "app.api",
            "app.persistence",
            "app.repositories",
            "app.ingestion",
        }
    )
    assert _imported_roots(service).isdisjoint(forbidden)
    assert "app.ingestion" not in _imported_roots(service)

    import app.domain.candidate_normalization as normalization

    tree = ast.parse(inspect.getsource(normalization))
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    attrs = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert "normalize_source_text" not in names | attrs
    assert "source_ingestion" not in _imported_roots(normalization)


def _manual_request(**overrides: object) -> SourceIngestionRequest:
    payload: dict[str, object] = {
        "source_type": "manual_text",
        "title": "Article",
        "text": "Bonjour",
        "note": "se rendre compte",
    }
    payload.update(overrides)
    return SourceIngestionRequest.model_validate(payload)


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
