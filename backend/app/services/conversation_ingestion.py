"""会話 JSON を取り込み、既存 Source を上書きせずに保存する（Issue #194）。

schema 以外の JSON は解釈しない。添付 URL は取得しない。
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
from app.ingestion.conversation_errors import (
    MSG_INVALID_CONVERSATION,
    MSG_TEXT_TOO_LARGE,
    ConversationIngestErrorCode,
    ConversationIngestionError,
)
from app.ingestion.conversation_log import (
    MAX_CONVERSATION_BYTES,
    STORED_CONVERSATION_MIME,
    ConversationIngestionAdapter,
    ensure_conversation_media_type,
    ensure_nonempty_file,
    file_digest,
    read_bounded,
    sanitize_conversation_filename,
)
from app.repositories.protocols import SourceDocumentRepository
from app.services.source_ingestion_service import (
    CommittedIngestion,
    SourceIngestionService,
)


class ConversationIngestionService:
    def __init__(
        self,
        sources: SourceDocumentRepository,
        *,
        clock: Callable[[], datetime] = utcnow,
        max_bytes: int = MAX_CONVERSATION_BYTES,
    ) -> None:
        self._clock = clock
        self._max_bytes = max_bytes
        self._commit = SourceIngestionService(sources, clock=clock)

    def ingest_conversation(
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
        safe_name = sanitize_conversation_filename(filename)
        ensure_conversation_media_type(declared_media_type, filename=safe_name)
        cleaned_title = _optional(title, limit=MAX_SHORT_FIELD_CHARS)
        cleaned_note = _optional(note, limit=2_000)
        cleaned_language = language.strip()
        if not cleaned_language or len(cleaned_language) > 32:
            raise ConversationIngestionError(
                MSG_INVALID_CONVERSATION,
                code=ConversationIngestErrorCode.invalid_conversation,
            )
        digest = file_digest(data)
        request = SourceIngestionRequest(
            source_type="conversation_log",
            locator=digest,
            filename=safe_name,
            mime_type=STORED_CONVERSATION_MIME,
            title=cleaned_title,
            note=cleaned_note,
            language=cleaned_language,
        )
        try:
            result = ingest_source(
                request,
                ingested_at=self._clock(),
                adapter=ConversationIngestionAdapter(
                    data,
                    filename=safe_name,
                    file_sha256=digest,
                ),
            )
        except ConversationIngestionError:
            raise
        except SourceIngestionError as exc:
            if exc.kind is IngestionFailureKind.input_too_large:
                raise ConversationIngestionError(
                    MSG_TEXT_TOO_LARGE, code=ConversationIngestErrorCode.text_too_large
                ) from exc
            raise ConversationIngestionError(
                MSG_INVALID_CONVERSATION,
                code=ConversationIngestErrorCode.invalid_conversation,
            ) from exc
        return self._commit.commit(result)


def _optional(value: str | None, *, limit: int) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned or len(cleaned) > limit:
        raise ConversationIngestionError(
            MSG_INVALID_CONVERSATION,
            code=ConversationIngestErrorCode.invalid_conversation,
        )
    return cleaned
