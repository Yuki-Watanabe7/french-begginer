"""テキスト PDF をページ provenance 付き SourceDocument にする（Issue #191）。

OCR も外部 API も使わない。パーサは adapter の背後に閉じる。
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
from pypdf import PdfWriter

from app.api.deps import (
    get_learning_item_extractor,
    get_pdf_ingestion_service,
    get_pdf_text_parser,
    get_tutor_store,
)
from app.domain.source_ingestion import (
    INGESTION_VERSION,
    IngestAction,
    SourceIngestionError,
    SourceIngestionRequest,
    content_digest,
    segment_for_span,
)
from app.domain.tutor import SourceDocument, read_source_evidence
from app.ingestion.pdf import PDF_ADAPTER_VERSION, PdfIngestionAdapter
from app.ingestion.pdf_errors import (
    MSG_OCR_REQUIRED,
    MSG_PARSER_TIMEOUT,
    PdfIngestErrorCode,
    PdfIngestionError,
)
from app.ingestion.pdf_parser import PARSER_NAME, PypdfTextParser
from app.ingestion.pdf_text import (
    MAX_PDF_BYTES,
    MAX_PDF_PAGES,
    MIN_PDF_LETTER_CHARS,
    PDF_PARSE_TIMEOUT_SECONDS,
    PdfExtractedDocument,
    PdfPageText,
    PdfTextParser,
    normalize_pdf_page_text,
)
from app.main import app
from app.repositories.sqlite import TutorSqliteStore
from app.services.extraction_schema import ExtractedCandidate, ExtractedEvidenceSpan
from app.services.extraction_service import ExtractionService
from app.services.extractors import ExtractorResult
from app.services.pdf_ingestion import PdfIngestionService
from tests.pdf_samples import build_pdf, lesson_pdf, text_page

FIXED = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
LATER = datetime(2026, 4, 2, 12, 0, tzinfo=UTC)
AFTER = datetime(2026, 4, 3, 12, 0, tzinfo=UTC)

PAGE_1 = (
    "Leçon 1\n"
    "Aujourd'hui, l'élève prend un café.\n"
    "\n"
    "Il n'est pas trop tard pour apprendre le français."
)
PAGE_2 = "Leçon 1\nC'est l'heure du petit déjeuner.\nL'école ouvre à huit heures."
PAGE_3 = "Leçon 1\nBon courage, et à demain."
LESSON_TEXT = "\n\n".join((PAGE_1, PAGE_2, PAGE_3))


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


def test_page_text_keeps_ligatures_apostrophes_and_line_breaks() -> None:
    assert MAX_PDF_BYTES == 8_000_000
    assert MAX_PDF_PAGES == 50
    assert PDF_PARSE_TIMEOUT_SECONDS == 10.0
    assert MIN_PDF_LETTER_CHARS == 20
    raw = "aujourd\u2019hui ﬁ cafe\u0301  \n\nappren-\ndre\f"
    assert normalize_pdf_page_text(raw) == (
        "aujourd\u2019hui ﬁ cafe\u0301\n\nappren-\ndre"
    )
    assert "\ufb01" in normalize_pdf_page_text("ﬁnalement")
    with pytest.raises(PdfIngestionError) as nul:
        normalize_pdf_page_text("bon\x00jour")
    assert nul.value.code is PdfIngestErrorCode.malformed_pdf


def test_lesson_pdf_saves_pages_in_order_with_provenance(
    store: TutorSqliteStore,
) -> None:
    data = lesson_pdf()
    committed = _service(store).ingest_pdf(
        source=BytesIO(data),
        filename=r"..\..\leçon.pdf",
        declared_media_type="Application/PDF; charset=binary",
        note="depuis le pdf",
    )
    document = committed.document
    assert committed.created is True
    assert committed.action is IngestAction.create
    assert document.source_type == "pdf"
    assert document.title == "leçon"
    assert document.language == "fr"
    assert document.content == LESSON_TEXT
    assert document.content.count("Leçon 1") == 3
    assert "l'élève" in document.content
    assert "français" in document.content
    assert "à huit" in document.content
    assert "%PDF" not in document.content
    assert "\x00" not in document.content
    assert [segment.page_number for segment in document.segments] == [1, 2, 3]
    for segment, page in zip(document.segments, (PAGE_1, PAGE_2, PAGE_3), strict=True):
        extracted = document.content[segment.normalized_start : segment.normalized_end]
        assert extracted == page
    assert (
        document.content[
            document.segments[0].normalized_end : document.segments[1].normalized_start
        ]
        == "\n\n"
    )
    assert (
        "\n\n"
        in document.content[
            document.segments[0].normalized_start : document.segments[0].normalized_end
        ]
    )
    assert document.content_hash == content_digest(document.content)
    assert document.ingestion_version == INGESTION_VERSION
    provenance = document.provenance
    assert provenance is not None
    assert provenance.filename == "leçon.pdf"
    assert provenance.mime_type == "application/pdf"
    assert provenance.adapter_version == PDF_ADAPTER_VERSION
    assert provenance.ingestion_version == INGESTION_VERSION
    assert provenance.canonical_locator == document.metadata["file_sha256"]
    assert str(provenance.canonical_locator).startswith("sha256:")
    assert provenance.canonical_locator != document.content_hash
    assert document.metadata["page_count"] == 3
    assert document.metadata["text_page_count"] == 3
    assert document.metadata["empty_page_numbers"] == []
    assert document.metadata["parser_name"] == PARSER_NAME
    assert document.metadata["parser_version"]
    assert document.metadata["text_extraction"] == "plain"
    assert document.metadata["pdf_access"] == "open"
    assert document.metadata["note"] == "depuis le pdf"
    assert "raw_pdf" not in document.metadata
    assert "../" not in document.model_dump_json()
    cafe = _span(document, "café")
    assert cafe.page_number == 1
    demain = _span(document, "demain")
    assert demain.page_number == 3


def test_empty_page_keeps_later_page_numbers(store: TutorSqliteStore) -> None:
    data = build_pdf(
        [
            text_page(
                r"Le\347on 1",
                r"Aujourd'hui, l'\351l\350ve prend un caf\351.",
            ),
            b"",
            text_page(r"Bon courage, et \340 demain avec les \351l\350ves."),
        ]
    )
    document = (
        _service(store)
        .ingest_pdf(
            source=BytesIO(data),
            filename="leçon.pdf",
            declared_media_type=None,
        )
        .document
    )
    assert [segment.page_number for segment in document.segments] == [1, 3]
    assert document.metadata["page_count"] == 3
    assert document.metadata["text_page_count"] == 2
    assert document.metadata["empty_page_numbers"] == [2]
    assert _span(document, "café").page_number == 1
    assert _span(document, "élèves").page_number == 3
    with pytest.raises(SourceIngestionError):
        segment_for_span(
            document.segments,
            start=document.segments[0].normalized_end - 1,
            end=document.segments[1].normalized_start + 1,
        )


def test_evidence_span_maps_to_page_for_candidate_extraction(
    store: TutorSqliteStore,
) -> None:
    document = (
        _service(store)
        .ingest_pdf(
            source=BytesIO(lesson_pdf()),
            filename="leçon.pdf",
            declared_media_type="application/octet-stream",
        )
        .document
    )
    extractor = _CafeExtractor()
    extracted = ExtractionService(extractor).extract(document)
    assert extractor.sources[0].source_type == "pdf"
    assert "%PDF" not in extractor.sources[0].content
    assert len(extracted.candidates) == 1
    evidence = read_source_evidence(
        document.content, extracted.candidates[0].evidence_span
    )
    assert evidence == "café"
    assert (
        segment_for_span(
            document.segments,
            start=extracted.candidates[0].evidence_span.start,
            end=extracted.candidates[0].evidence_span.end,
        ).page_number
        == 1
    )


def test_same_bytes_reuse_and_other_bytes_create_a_new_source(
    store: TutorSqliteStore,
) -> None:
    moments = iter((FIXED, LATER, AFTER))
    service = _service(store, clock=lambda: next(moments))
    data = lesson_pdf()
    created = service.ingest_pdf(
        source=BytesIO(data),
        filename="leçon.pdf",
        declared_media_type="application/pdf",
        title="Mon cours",
    )
    reused = service.ingest_pdf(
        source=BytesIO(data),
        filename="autre.pdf",
        declared_media_type="application/pdf",
        title="Ignoré",
    )
    assert reused.created is False
    assert reused.action is IngestAction.reuse
    assert reused.document.id == created.document.id
    assert reused.document.title == "Mon cours"
    assert reused.document.content == LESSON_TEXT

    changed = lesson_pdf(comment="autre-fichier")
    assert changed != data
    second = service.ingest_pdf(
        source=BytesIO(changed),
        filename="leçon.pdf",
        declared_media_type="application/pdf",
    )
    assert second.created is True
    assert second.action is IngestAction.create
    assert second.document.id != created.document.id
    assert second.document.content == created.document.content
    assert "prior_source_id" not in created.document.metadata
    preserved = store.source_documents.get(created.document.id)
    assert preserved is not None
    assert preserved.content == LESSON_TEXT


def test_rejects_bad_files_without_saving_or_leaking_bytes(
    store: TutorSqliteStore,
) -> None:
    secret = "SUPERSECRET-BODY"
    cases = [
        (
            b"",
            "notes.pdf",
            "application/pdf",
            PdfIngestErrorCode.invalid_pdf,
            _service(store),
        ),
        (
            b"not a pdf",
            "notes.pdf",
            "application/pdf",
            PdfIngestErrorCode.malformed_pdf,
            _service(store),
        ),
        (
            f"%PDF-1.4\n{secret}".encode(),
            "notes.pdf",
            "application/pdf",
            PdfIngestErrorCode.malformed_pdf,
            _service(store),
        ),
        (
            b"A" * 1024 + lesson_pdf(),
            "notes.pdf",
            "application/pdf",
            PdfIngestErrorCode.malformed_pdf,
            _service(store),
        ),
        (
            lesson_pdf(),
            "notes.pdf",
            "text/html",
            PdfIngestErrorCode.unsupported_media,
            _service(store),
        ),
        (
            lesson_pdf(),
            "../",
            "application/pdf",
            PdfIngestErrorCode.invalid_pdf,
            _service(store),
        ),
        (
            lesson_pdf(),
            "notes.pdf",
            "application/pdf",
            PdfIngestErrorCode.file_too_large,
            _service(store, max_bytes=32),
        ),
        (
            lesson_pdf(),
            "notes.pdf",
            "application/pdf",
            PdfIngestErrorCode.too_many_pages,
            _service(store, parser=PypdfTextParser(max_pages=2)),
        ),
        (
            build_pdf([b""]),
            "scan.pdf",
            "application/pdf",
            PdfIngestErrorCode.ocr_required,
            _service(store),
        ),
        (
            build_pdf([text_page("12")]),
            "scan.pdf",
            "application/pdf",
            PdfIngestErrorCode.ocr_required,
            _service(store),
        ),
        (
            _encrypt(lesson_pdf(), "super-secret-password"),
            "secret.pdf",
            "application/pdf",
            PdfIngestErrorCode.encrypted_pdf,
            _service(store),
        ),
    ]
    for data, filename, media, code, service in cases:
        with pytest.raises(PdfIngestionError) as caught:
            service.ingest_pdf(
                source=BytesIO(data),
                filename=filename,
                declared_media_type=media,
            )
        assert caught.value.code is code
        assert caught.value.retryable is False
        assert secret not in str(caught.value)
        assert "super-secret-password" not in str(caught.value)
        if code is PdfIngestErrorCode.ocr_required:
            assert "OCR" in str(caught.value)
            assert str(caught.value) == MSG_OCR_REQUIRED
    assert store.source_documents.list() == []


def test_owner_restriction_opens_without_a_user_password(
    store: TutorSqliteStore,
) -> None:
    data = _encrypt(lesson_pdf(), "", owner_password="owner-only-secret")
    document = (
        _service(store)
        .ingest_pdf(
            source=BytesIO(data),
            filename="leçon.pdf",
            declared_media_type="application/pdf",
        )
        .document
    )
    assert document.content == LESSON_TEXT
    assert document.metadata["pdf_access"] == "owner_restrictions"
    dumped = document.model_dump_json()
    assert "owner-only-secret" not in dumped
    assert "%PDF" not in document.content


def test_short_text_needs_ocr_and_unicode_is_preserved(
    store: TutorSqliteStore,
) -> None:
    short = _scripted("a" * (MIN_PDF_LETTER_CHARS - 1))
    with pytest.raises(PdfIngestionError) as sparse:
        _service(store, parser=short).ingest_pdf(
            source=BytesIO(b"%PDF-1.4\n"),
            filename="court.pdf",
            declared_media_type="application/pdf",
        )
    assert sparse.value.code is PdfIngestErrorCode.ocr_required
    assert short.calls == 1
    assert store.source_documents.list() == []

    enough = _scripted("a" * MIN_PDF_LETTER_CHARS)
    saved = _service(store, parser=enough).ingest_pdf(
        source=BytesIO(b"%PDF-1.4\n% enough\n"),
        filename="assez.pdf",
        declared_media_type="application/pdf",
    )
    assert saved.document.content == "a" * MIN_PDF_LETTER_CHARS

    ligature = _scripted("L'élève lit ﬁnalement aujourd\u2019hui un cafe\u0301.")
    document = (
        _service(store, parser=ligature)
        .ingest_pdf(
            source=BytesIO(b"%PDF-1.4\n% ligature\n"),
            filename="unicode.pdf",
            declared_media_type="application/pdf",
        )
        .document
    )
    assert "ﬁ" in document.content
    assert "aujourd\u2019hui" in document.content
    assert "café" in document.content
    assert "cafe\u0301" not in document.content

    raw = _scripted("%PDF-1.7\n" + ("Bonjour le français. " * 3))
    with pytest.raises(PdfIngestionError) as payload:
        _service(store, parser=raw).ingest_pdf(
            source=BytesIO(b"%PDF-1.4\n% raw\n"),
            filename="raw.pdf",
            declared_media_type="application/pdf",
        )
    assert payload.value.code is PdfIngestErrorCode.invalid_pdf
    assert "%PDF" not in str(payload.value)
    assert store.source_documents.get(saved.document.id) is not None
    assert len(store.source_documents.list()) == 2


def test_txt_extension_is_accepted_when_magic_is_pdf(
    store: TutorSqliteStore,
) -> None:
    document = (
        _service(store)
        .ingest_pdf(
            source=BytesIO(b"\n" + lesson_pdf()),
            filename="notes.txt",
            declared_media_type="application/octet-stream",
            title="  Cours  ",
            language="en",
        )
        .document
    )
    assert document.title == "Cours"
    assert document.language == "en"
    assert document.content == LESSON_TEXT
    assert document.provenance is not None
    assert document.provenance.filename == "notes.txt"


def test_parser_timeout_is_retryable_and_stops_before_commit(
    store: TutorSqliteStore,
) -> None:
    clock = _ExpireClock()
    parser = PypdfTextParser(clock=clock, timeout_seconds=10)
    with pytest.raises(PdfIngestionError) as caught:
        _service(store, parser=parser).ingest_pdf(
            source=BytesIO(lesson_pdf()),
            filename="leçon.pdf",
            declared_media_type="application/pdf",
        )
    assert caught.value.code is PdfIngestErrorCode.parser_timeout
    assert caught.value.retryable is True
    assert str(caught.value) == MSG_PARSER_TIMEOUT
    assert clock.calls == 2
    assert store.source_documents.list() == []


def test_pdf_source_survives_database_reopen(tmp_path) -> None:
    path = tmp_path / "pdf.db"
    store = TutorSqliteStore(f"sqlite:///{path}")
    try:
        saved = _service(store, clock=lambda: FIXED).ingest_pdf(
            source=BytesIO(lesson_pdf()),
            filename="leçon.pdf",
            declared_media_type="application/pdf",
        )
        store.engine.dispose()
        reopened = TutorSqliteStore(f"sqlite:///{path}")
        try:
            loaded = reopened.source_documents.get(saved.document.id)
            assert loaded == saved.document
            assert loaded is not None
            assert _span(loaded, "café").page_number == 1
            assert _span(loaded, "demain").page_number == 3
        finally:
            reopened.engine.dispose()
    finally:
        store.engine.dispose()


def test_adapter_boundary_does_not_import_parser_or_ocr() -> None:
    import app.domain.source_ingestion as domain
    import app.ingestion.pdf as adapter
    import app.ingestion.pdf_parser as parser
    import app.ingestion.pdf_text as rules
    import app.services.pdf_ingestion as service
    import app.services.source_ingestion_service as commit_service

    forbidden = {
        "pypdf",
        "pdfminer",
        "fitz",
        "pytesseract",
        "ocrmypdf",
        "easyocr",
        "pdf2image",
        "httpx",
        "requests",
        "openai",
    }
    for module in (domain, rules, adapter, service, commit_service):
        assert _imported_roots(module).isdisjoint(forbidden), module.__name__
    parser_imports = _imported_roots(parser)
    assert "pypdf" in parser_imports
    assert parser_imports.isdisjoint(
        {"pytesseract", "ocrmypdf", "easyocr", "pdf2image", "fitz", "pdfminer"}
    )
    assert "app.ingestion" not in _imported_roots(domain)


def test_ingest_pdf_api_returns_source_and_keeps_manual_create(
    client: TestClient, store: TutorSqliteStore
) -> None:
    manual = client.post(
        "/api/tutor/sources",
        json={"title": "手入力", "content": "ligne\r\n\r\n\r\nsuite"},
    )
    assert manual.status_code == 201
    assert manual.json()["content"] == "ligne\r\n\r\n\r\nsuite"

    created = client.post(
        "/api/tutor/sources/ingest/pdf",
        files={"file": ("../../leçon.pdf", lesson_pdf(), "application/pdf")},
        data={"title": "Mon cours", "note": "depuis le pdf", "language": "fr"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["action"] == "create"
    assert body["created"] is True
    source = body["source"]
    assert source["source_type"] == "pdf"
    assert source["title"] == "Mon cours"
    assert source["content"] == LESSON_TEXT
    assert source["provenance"]["filename"] == "leçon.pdf"
    assert source["provenance"]["mime_type"] == "application/pdf"
    assert source["metadata"]["page_count"] == 3
    assert [segment["page_number"] for segment in source["segments"]] == [1, 2, 3]
    assert "../" not in created.text
    assert "%PDF" not in source["content"]

    detail = client.get(f"/api/tutor/sources/{source['id']}")
    assert detail.status_code == 200
    assert detail.json()["content"] == LESSON_TEXT

    again = client.post(
        "/api/tutor/sources/ingest/pdf",
        files={"file": ("leçon.pdf", lesson_pdf(), "application/pdf")},
    )
    assert again.status_code == 200
    assert again.json()["action"] == "reuse"
    assert again.json()["source"]["id"] == source["id"]
    assert again.json()["source"]["title"] == "Mon cours"

    app.dependency_overrides[get_learning_item_extractor] = lambda: _CafeExtractor()
    extracted = client.post(f"/api/tutor/sources/{source['id']}/candidates/extract")
    assert extracted.status_code == 200, extracted.text
    candidate = extracted.json()["created"][0]
    assert candidate["evidence_text"] == "café"
    span = candidate["evidence_span"]
    loaded = store.source_documents.get(source["id"])
    assert loaded is not None
    mapped = segment_for_span(loaded.segments, start=span["start"], end=span["end"])
    assert mapped.page_number == 1


def test_ingest_pdf_api_distinguishes_errors(
    client: TestClient, store: TutorSqliteStore
) -> None:
    malformed = client.post(
        "/api/tutor/sources/ingest/pdf",
        files={
            "file": (
                "notes.pdf",
                b"%PDF-1.4\nSUPERSECRET-BODY",
                "application/pdf",
            )
        },
    )
    assert malformed.status_code == 400
    assert malformed.json()["detail"]["code"] == "malformed_pdf"
    assert "SUPERSECRET" not in malformed.text

    encrypted = client.post(
        "/api/tutor/sources/ingest/pdf",
        files={
            "file": (
                "secret.pdf",
                _encrypt(lesson_pdf(), "super-secret-password"),
                "application/pdf",
            )
        },
    )
    assert encrypted.status_code == 422
    assert encrypted.json()["detail"]["code"] == "encrypted_pdf"
    assert "super-secret-password" not in encrypted.text

    scanned = client.post(
        "/api/tutor/sources/ingest/pdf",
        files={"file": ("scan.pdf", build_pdf([b""]), "application/pdf")},
    )
    assert scanned.status_code == 422
    assert scanned.json()["detail"]["code"] == "ocr_required"
    assert "OCR" in scanned.json()["detail"]["message"]

    html = client.post(
        "/api/tutor/sources/ingest/pdf",
        files={"file": ("leçon.pdf", lesson_pdf(), "text/html")},
    )
    assert html.status_code == 415
    assert html.json()["detail"]["code"] == "unsupported_media"

    app.dependency_overrides[get_pdf_ingestion_service] = lambda: PdfIngestionService(
        store.source_documents, PypdfTextParser(), max_bytes=32
    )
    oversized = client.post(
        "/api/tutor/sources/ingest/pdf",
        files={"file": ("leçon.pdf", lesson_pdf(), "application/pdf")},
    )
    assert oversized.status_code == 413
    assert oversized.json()["detail"]["code"] == "file_too_large"
    del app.dependency_overrides[get_pdf_ingestion_service]

    app.dependency_overrides[get_pdf_text_parser] = lambda: PypdfTextParser(max_pages=2)
    too_many = client.post(
        "/api/tutor/sources/ingest/pdf",
        files={"file": ("leçon.pdf", lesson_pdf(), "application/pdf")},
    )
    assert too_many.status_code == 413
    assert too_many.json()["detail"]["code"] == "too_many_pages"

    app.dependency_overrides[get_pdf_text_parser] = lambda: _TimeoutParser()
    timed_out = client.post(
        "/api/tutor/sources/ingest/pdf",
        files={"file": ("leçon.pdf", lesson_pdf(), "application/pdf")},
    )
    assert timed_out.status_code == 504
    assert timed_out.json()["detail"]["code"] == "parser_timeout"
    assert store.source_documents.list() == []


def test_openapi_exposes_pdf_ingest_without_changing_manual_create() -> None:
    with TestClient(app) as http:
        spec = http.get("/openapi.json").json()
    operation = spec["paths"]["/api/tutor/sources/ingest/pdf"]["post"]
    assert "multipart/form-data" in operation["requestBody"]["content"]
    create_props = spec["components"]["schemas"]["CreateSourceRequest"]["properties"]
    assert "source_type" not in create_props
    assert "file" not in create_props
    assert "/api/tutor/sources/pdf" not in spec["paths"]


class _CafeExtractor:
    def __init__(self) -> None:
        self.sources: list[SourceDocument] = []

    def extract(self, source: SourceDocument) -> ExtractorResult:
        self.sources.append(source)
        content = source.content
        start = content.index("café")
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


class _ScriptedParser:
    def __init__(self, document: PdfExtractedDocument) -> None:
        self._document = document
        self.calls = 0

    def parse(self, data: bytes) -> PdfExtractedDocument:
        self.calls += 1
        assert data.startswith(b"%PDF-")
        return self._document


class _TimeoutParser:
    def parse(self, data: bytes) -> PdfExtractedDocument:
        raise PdfIngestionError(
            MSG_PARSER_TIMEOUT, code=PdfIngestErrorCode.parser_timeout
        )


class _ExpireClock:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> float:
        self.calls += 1
        return 0.0 if self.calls == 1 else 100.0


def _service(
    store: TutorSqliteStore,
    *,
    parser: PdfTextParser | None = None,
    clock=lambda: FIXED,
    max_bytes: int = MAX_PDF_BYTES,
) -> PdfIngestionService:
    return PdfIngestionService(
        store.source_documents,
        parser if parser is not None else PypdfTextParser(),
        clock=clock,
        max_bytes=max_bytes,
    )


def _scripted(text: str) -> _ScriptedParser:
    return _ScriptedParser(
        PdfExtractedDocument(
            page_count=1,
            pages=(PdfPageText(page_number=1, text=text),),
            parser_name="fake",
            parser_version="fake-1",
            pdf_access="open",
        )
    )


def _span(document: SourceDocument, word: str):
    start = document.content.index(word)
    return segment_for_span(document.segments, start=start, end=start + len(word))


def _encrypt(
    data: bytes, user_password: str, owner_password: str | None = None
) -> bytes:
    writer = PdfWriter()
    writer.append(BytesIO(data))
    if owner_password is None:
        writer.encrypt(user_password)
    else:
        writer.encrypt(user_password=user_password, owner_password=owner_password)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


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


def test_direct_adapter_rejects_wrong_source_type() -> None:
    adapter = PdfIngestionAdapter(
        b"%PDF-1.4\n",
        _scripted("a" * 20),
        original_filename="a.pdf",
        file_sha256="sha256:abc",
    )
    request = SourceIngestionRequest(
        source_type="manual_text", title="t", text="bonjour"
    )
    with pytest.raises(SourceIngestionError):
        adapter.ingest(request, ingested_at=FIXED)
