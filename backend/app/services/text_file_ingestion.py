"""テキスト / Markdown を取り込み、既存 Source を上書きせずに保存する（Issue #194）。

ファイルの読み取り以外には依存しない。URL は取得しない。
保存の再利用は `SourceIngestionService.commit` が担う。
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
from app.ingestion.text_file import (
    MAX_TEXT_FILE_BYTES,
    TextFileIngestionAdapter,
    decode_text_file,
    ensure_nonempty_file,
    ensure_text_media_type,
    file_digest,
    read_bounded,
    sanitize_text_filename,
    stored_mime_type,
    text_file_format,
)
from app.ingestion.text_file_errors import (
    MSG_INVALID_TEXT_FILE,
    MSG_TEXT_TOO_LARGE,
    TextFileIngestErrorCode,
    TextFileIngestionError,
)
from app.repositories.protocols import SourceDocumentRepository
from app.services.source_ingestion_service import (
    CommittedIngestion,
    SourceIngestionService,
)


class TextFileIngestionService:
    def __init__(
        self,
        sources: SourceDocumentRepository,
        *,
        clock: Callable[[], datetime] = utcnow,
        max_bytes: int = MAX_TEXT_FILE_BYTES,
    ) -> None:
        self._clock = clock
        self._max_bytes = max_bytes
        self._commit = SourceIngestionService(sources, clock=clock)

    def ingest_text_file(
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
        safe_name = sanitize_text_filename(filename)
        text_format = text_file_format(safe_name)
        ensure_text_media_type(declared_media_type, text_format)
        decode_text_file(data)
        cleaned_title = _optional(title, limit=MAX_SHORT_FIELD_CHARS)
        cleaned_note = _optional(note, limit=2_000)
        cleaned_language = language.strip()
        if not cleaned_language or len(cleaned_language) > 32:
            raise TextFileIngestionError(
                MSG_INVALID_TEXT_FILE, code=TextFileIngestErrorCode.invalid_text_file
            )
        digest = file_digest(data)
        request = SourceIngestionRequest(
            source_type="conversation_log",
            locator=digest,
            filename=safe_name,
            mime_type=stored_mime_type(text_format),
            title=cleaned_title,
            note=cleaned_note,
            language=cleaned_language,
        )
        try:
            result = ingest_source(
                request,
                ingested_at=self._clock(),
                adapter=TextFileIngestionAdapter(
                    data,
                    filename=safe_name,
                    text_format=text_format,
                    file_sha256=digest,
                ),
            )
        except TextFileIngestionError:
            raise
        except SourceIngestionError as exc:
            if exc.kind is IngestionFailureKind.input_too_large:
                raise TextFileIngestionError(
                    MSG_TEXT_TOO_LARGE, code=TextFileIngestErrorCode.text_too_large
                ) from exc
            raise TextFileIngestionError(
                MSG_INVALID_TEXT_FILE, code=TextFileIngestErrorCode.invalid_text_file
            ) from exc
        return self._commit.commit(result)


def _optional(value: str | None, *, limit: int) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned or len(cleaned) > limit:
        raise TextFileIngestionError(
            MSG_INVALID_TEXT_FILE, code=TextFileIngestErrorCode.invalid_text_file
        )
    return cleaned
