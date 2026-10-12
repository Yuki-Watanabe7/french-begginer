"""テキスト PDF を SourceIngestionResult にする adapter（Issue #191）。

パーサは `PdfTextParser` の背後に置く。このモジュールは pypdf を import しない。
正規化と page segment の組み立ては共有の `assemble_ingestion_result` を通す。
raw PDF は結果に載せない。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.domain.source_ingestion import (
    MAX_SHORT_FIELD_CHARS,
    IngestionFailureKind,
    SourceIngestionError,
    SourceIngestionRequest,
    SourceIngestionResult,
    SourceSegmentDraft,
    SourceType,
    assemble_ingestion_result,
    normalize_source_text,
)
from app.ingestion.pdf_errors import (
    MSG_INVALID_PDF,
    MSG_MALFORMED_PDF,
    MSG_OCR_REQUIRED,
    MSG_TEXT_TOO_LARGE,
    PdfIngestErrorCode,
    PdfIngestionError,
)
from app.ingestion.pdf_text import (
    MIN_PDF_LETTER_CHARS,
    PDF_ADAPTER_VERSION,
    PdfExtractedDocument,
    PdfTextParser,
    count_letters,
    normalize_pdf_page_text,
)

TEXT_EXTRACTION = "plain"


class PdfIngestionAdapter:
    """1 件の PDF バイト列を、ページ provenance 付きの plain text にする。"""

    source_type: SourceType = "pdf"
    adapter_version = PDF_ADAPTER_VERSION

    def __init__(
        self,
        data: bytes,
        parser: PdfTextParser,
        *,
        original_filename: str,
        file_sha256: str,
    ) -> None:
        self._data = data
        self._parser = parser
        self._filename = original_filename
        self._file_sha256 = file_sha256

    def ingest(
        self, request: SourceIngestionRequest, *, ingested_at: datetime
    ) -> SourceIngestionResult:
        if request.source_type != "pdf":
            raise SourceIngestionError(
                "PdfIngestionAdapter は pdf 専用",
                kind=IngestionFailureKind.validation,
            )
        if request.locator not in (None, self._file_sha256):
            raise PdfIngestionError(
                MSG_INVALID_PDF, code=PdfIngestErrorCode.invalid_pdf
            )
        extracted = self._parser.parse(self._data)
        drafts, empty_pages = _page_drafts(extracted)
        if not drafts:
            raise PdfIngestionError(
                MSG_OCR_REQUIRED, code=PdfIngestErrorCode.ocr_required
            )
        metadata: dict[str, Any] = {
            "file_sha256": self._file_sha256,
            "page_count": extracted.page_count,
            "text_page_count": len(drafts),
            "empty_page_numbers": empty_pages,
            "parser_name": extracted.parser_name,
            "parser_version": extracted.parser_version,
            "text_extraction": TEXT_EXTRACTION,
            "pdf_access": extracted.pdf_access,
        }
        if request.note and request.note.strip():
            metadata["note"] = request.note.strip()
        try:
            result = assemble_ingestion_result(
                source_type="pdf",
                title=_choose_title(request.title, self._filename),
                language=request.language,
                drafts=drafts,
                adapter_version=self.adapter_version,
                ingested_at=ingested_at,
                canonical_locator=self._file_sha256,
                filename=self._filename,
                mime_type="application/pdf",
                metadata=metadata,
            )
        except SourceIngestionError as exc:
            if exc.kind is IngestionFailureKind.input_too_large:
                raise PdfIngestionError(
                    MSG_TEXT_TOO_LARGE, code=PdfIngestErrorCode.text_too_large
                ) from exc
            raise
        if count_letters(result.normalized_content) < MIN_PDF_LETTER_CHARS:
            raise PdfIngestionError(
                MSG_OCR_REQUIRED, code=PdfIngestErrorCode.ocr_required
            )
        return result


def _page_drafts(
    extracted: PdfExtractedDocument,
) -> tuple[list[SourceSegmentDraft], list[int]]:
    expected = list(range(1, extracted.page_count + 1))
    actual = [page.page_number for page in extracted.pages]
    if extracted.page_count != len(extracted.pages) or actual != expected:
        raise PdfIngestionError(
            MSG_MALFORMED_PDF, code=PdfIngestErrorCode.malformed_pdf
        )
    if extracted.pdf_access not in {"open", "owner_restrictions"}:
        raise PdfIngestionError(
            MSG_MALFORMED_PDF, code=PdfIngestErrorCode.malformed_pdf
        )
    drafts: list[SourceSegmentDraft] = []
    empty_pages: list[int] = []
    for page in extracted.pages:
        cleaned = normalize_pdf_page_text(page.text)
        if not normalize_source_text(cleaned):
            empty_pages.append(page.page_number)
            continue
        drafts.append(SourceSegmentDraft(text=cleaned, page_number=page.page_number))
    return drafts, empty_pages


def _choose_title(override: str | None, filename: str) -> str:
    chosen = override.strip() if override else ""
    if not chosen:
        chosen = _stem(filename)
    collapsed = " ".join(chosen.split())
    bounded = collapsed[:MAX_SHORT_FIELD_CHARS].strip()
    return bounded or "PDF"


def _stem(filename: str) -> str:
    dot = filename.rfind(".")
    if dot <= 0:
        return "" if dot == 0 else filename
    return filename[:dot]
