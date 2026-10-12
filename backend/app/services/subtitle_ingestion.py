"""SRT / VTT を取り込み、既存 Source を上書きせずに保存する（Issue #192）。

字幕パーサ以外には依存しない。保存の再利用は `SourceIngestionService.commit` が担う。
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
from app.ingestion.subtitle import SubtitleIngestionAdapter
from app.ingestion.subtitle_errors import (
    MSG_INVALID_SUBTITLE,
    MSG_MALFORMED_SUBTITLE,
    MSG_TEXT_TOO_LARGE,
    SubtitleIngestErrorCode,
    SubtitleIngestionError,
)
from app.ingestion.subtitle_text import (
    MAX_SUBTITLE_BYTES,
    decode_subtitle,
    ensure_nonempty_file,
    ensure_subtitle_media_type,
    file_digest,
    filename_suffix,
    read_bounded,
    sanitize_subtitle_filename,
    sniff_subtitle_format,
    stored_mime_type,
)
from app.repositories.protocols import SourceDocumentRepository
from app.services.source_ingestion_service import (
    CommittedIngestion,
    SourceIngestionService,
)


class SubtitleIngestionService:
    def __init__(
        self,
        sources: SourceDocumentRepository,
        *,
        clock: Callable[[], datetime] = utcnow,
        max_bytes: int = MAX_SUBTITLE_BYTES,
    ) -> None:
        self._clock = clock
        self._max_bytes = max_bytes
        self._commit = SourceIngestionService(sources, clock=clock)

    def ingest_subtitle(
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
        safe_name = sanitize_subtitle_filename(filename)
        extension = filename_suffix(safe_name)
        ensure_subtitle_media_type(declared_media_type, extension)
        subtitle_format = sniff_subtitle_format(decode_subtitle(data))
        expected = "vtt" if extension == ".vtt" else "srt"
        if subtitle_format != expected:
            raise SubtitleIngestionError(
                MSG_MALFORMED_SUBTITLE,
                code=SubtitleIngestErrorCode.malformed_subtitle,
            )
        cleaned_title = _optional(title, limit=MAX_SHORT_FIELD_CHARS)
        cleaned_note = _optional(note, limit=2_000)
        cleaned_language = language.strip()
        if not cleaned_language or len(cleaned_language) > 32:
            raise SubtitleIngestionError(
                MSG_INVALID_SUBTITLE, code=SubtitleIngestErrorCode.invalid_subtitle
            )
        digest = file_digest(data)
        request = SourceIngestionRequest(
            source_type="subtitle",
            locator=digest,
            filename=safe_name,
            mime_type=stored_mime_type(subtitle_format),
            title=cleaned_title,
            note=cleaned_note,
            language=cleaned_language,
        )
        try:
            result = ingest_source(
                request,
                ingested_at=self._clock(),
                adapter=SubtitleIngestionAdapter(
                    data,
                    filename=safe_name,
                    subtitle_format=subtitle_format,
                    file_sha256=digest,
                ),
            )
        except SubtitleIngestionError:
            raise
        except SourceIngestionError as exc:
            if exc.kind is IngestionFailureKind.input_too_large:
                raise SubtitleIngestionError(
                    MSG_TEXT_TOO_LARGE, code=SubtitleIngestErrorCode.text_too_large
                ) from exc
            raise SubtitleIngestionError(
                MSG_INVALID_SUBTITLE, code=SubtitleIngestErrorCode.invalid_subtitle
            ) from exc
        return self._commit.commit(result)


def _optional(value: str | None, *, limit: int) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned or len(cleaned) > limit:
        raise SubtitleIngestionError(
            MSG_INVALID_SUBTITLE, code=SubtitleIngestErrorCode.invalid_subtitle
        )
    return cleaned
