"""音声を文字起こしし、既存 Source を上書きせずに保存する（Issue #193）。

文字起こし provider 以外には依存しない。TTS は使わない。
raw audio は保存せず、正規化後の本文を source of truth にする。
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
from app.ingestion.audio import (
    MAX_AUDIO_BYTES,
    AudioIngestionAdapter,
    TranscriptionProvider,
    ensure_audio_media_type,
    ensure_duration_allowed,
    ensure_nonempty_file,
    file_digest,
    filename_suffix,
    measure_duration_seconds,
    read_bounded,
    sanitize_audio_filename,
    stored_mime_type,
)
from app.ingestion.audio_errors import (
    MSG_INVALID_AUDIO,
    MSG_TEXT_TOO_LARGE,
    AudioIngestErrorCode,
    AudioIngestionError,
)
from app.repositories.protocols import SourceDocumentRepository
from app.services.source_ingestion_service import (
    CommittedIngestion,
    SourceIngestionService,
)


class AudioIngestionService:
    def __init__(
        self,
        sources: SourceDocumentRepository,
        provider: TranscriptionProvider,
        *,
        clock: Callable[[], datetime] = utcnow,
        max_bytes: int = MAX_AUDIO_BYTES,
    ) -> None:
        self._provider = provider
        self._clock = clock
        self._max_bytes = max_bytes
        self._commit = SourceIngestionService(sources, clock=clock)

    def ingest_audio(
        self,
        *,
        source: BinaryIO,
        filename: str | None,
        declared_media_type: str | None,
        title: str | None = None,
        note: str | None = None,
        language: str = "fr",
    ) -> CommittedIngestion:
        """同じ音声と同じ文字起こしなら既存を返す。本文は上書きしない。"""

        data = read_bounded(source, self._max_bytes)
        ensure_nonempty_file(data)
        safe_name = sanitize_audio_filename(filename)
        extension = filename_suffix(safe_name)
        ensure_audio_media_type(declared_media_type, extension)
        duration = measure_duration_seconds(data, extension)
        ensure_duration_allowed(duration)
        cleaned_title = _optional(title, limit=MAX_SHORT_FIELD_CHARS)
        cleaned_note = _optional(note, limit=2_000)
        cleaned_language = language.strip()
        if not cleaned_language or len(cleaned_language) > 32:
            raise AudioIngestionError(
                MSG_INVALID_AUDIO, code=AudioIngestErrorCode.invalid_audio
            )
        digest = file_digest(data)
        media_type = stored_mime_type(extension)
        request = SourceIngestionRequest(
            source_type="audio_transcript",
            locator=digest,
            title=cleaned_title,
            note=cleaned_note,
            language=cleaned_language,
        )
        try:
            result = ingest_source(
                request,
                ingested_at=self._clock(),
                adapter=AudioIngestionAdapter(
                    data,
                    self._provider,
                    filename=safe_name,
                    media_type=media_type,
                    file_sha256=digest,
                    duration_seconds=duration,
                ),
            )
        except AudioIngestionError:
            raise
        except SourceIngestionError as exc:
            if exc.kind is IngestionFailureKind.input_too_large:
                raise AudioIngestionError(
                    MSG_TEXT_TOO_LARGE, code=AudioIngestErrorCode.text_too_large
                ) from exc
            raise AudioIngestionError(
                MSG_INVALID_AUDIO, code=AudioIngestErrorCode.invalid_audio
            ) from exc
        return self._commit.commit(result)


def _optional(value: str | None, *, limit: int) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned or len(cleaned) > limit:
        raise AudioIngestionError(
            MSG_INVALID_AUDIO, code=AudioIngestErrorCode.invalid_audio
        )
    return cleaned
