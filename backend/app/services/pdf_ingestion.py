"""テキスト PDF を取得し、既存 Source を上書きせずに保存する（Issue #191）。

PDF パーサには依存しない。解析は `PdfTextParser`、保存の再利用は
`SourceIngestionService.commit` が担う。raw PDF は SQLite に入れない。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import BinaryIO

from app.domain.source_ingestion import (
    MAX_SHORT_FIELD_CHARS,
    IngestionFailureKind,
    SourceIngestionError,
    SourceIngestionRequest,
    ingest_source,
)
from app.domain.tutor import utcnow
from app.ingestion.pdf import PdfIngestionAdapter
from app.ingestion.pdf_errors import (
    MSG_INVALID_PDF,
    MSG_MALFORMED_PDF,
    MSG_TEXT_TOO_LARGE,
    PdfIngestErrorCode,
    PdfIngestionError,
)
from app.ingestion.pdf_text import (
    MAX_PDF_BYTES,
    PdfTextParser,
    ensure_nonempty_file,
    ensure_pdf_media_type,
    file_digest,
    filename_suffix,
    has_pdf_magic,
    read_bounded,
    sanitize_pdf_filename,
)
from app.repositories.protocols import SourceDocumentRepository
from app.services.source_ingestion_service import (
    CommittedIngestion,
    SourceIngestionService,
)


class PdfIngestionService:
    def __init__(
        self,
        sources: SourceDocumentRepository,
        parser: PdfTextParser,
        *,
        clock: Callable[[], datetime] = utcnow,
        max_bytes: int = MAX_PDF_BYTES,
    ) -> None:
        self._parser = parser
        self._clock = clock
        self._max_bytes = max_bytes
        self._commit = SourceIngestionService(sources, clock=clock)

    def ingest_pdf(
        self,
        *,
        source: BinaryIO,
        filename: str | None,
        declared_media_type: str | None,
        title: str | None = None,
        note: str | None = None,
        language: str = "fr",
    ) -> CommittedIngestion:
        """同じファイルバイト列と本文なら既存を返す。本文は上書きしない。"""

        data = read_bounded(source, self._max_bytes)
        ensure_nonempty_file(data)
        safe_name = sanitize_pdf_filename(filename)
        ensure_pdf_media_type(declared_media_type)
        if not has_pdf_magic(data):
            raise PdfIngestionError(
                MSG_MALFORMED_PDF, code=PdfIngestErrorCode.malformed_pdf
            )
        cleaned_title = _optional(title, limit=MAX_SHORT_FIELD_CHARS)
        cleaned_note = _optional(note, limit=2_000)
        cleaned_language = language.strip()
        if not cleaned_language or len(cleaned_language) > 32:
            raise PdfIngestionError(
                MSG_INVALID_PDF, code=PdfIngestErrorCode.invalid_pdf
            )
        digest = file_digest(data)
        request_filename = safe_name if filename_suffix(safe_name) == ".pdf" else None
        request = SourceIngestionRequest(
            source_type="pdf",
            locator=digest,
            filename=request_filename,
            mime_type="application/pdf",
            title=cleaned_title,
            note=cleaned_note,
            language=cleaned_language,
        )
        ingested_at = self._clock()
        try:
            result = ingest_source(
                request,
                ingested_at=ingested_at,
                adapter=PdfIngestionAdapter(
                    data,
                    self._parser,
                    original_filename=safe_name,
                    file_sha256=digest,
                ),
            )
        except PdfIngestionError:
            raise
        except SourceIngestionError as exc:
            if exc.kind is IngestionFailureKind.input_too_large:
                raise PdfIngestionError(
                    MSG_TEXT_TOO_LARGE, code=PdfIngestErrorCode.text_too_large
                ) from exc
            raise PdfIngestionError(
                MSG_INVALID_PDF, code=PdfIngestErrorCode.invalid_pdf
            ) from exc
        return self._commit.commit(result)


def _optional(value: str | None, *, limit: int) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned or len(cleaned) > limit:
        raise PdfIngestionError(MSG_INVALID_PDF, code=PdfIngestErrorCode.invalid_pdf)
    return cleaned
