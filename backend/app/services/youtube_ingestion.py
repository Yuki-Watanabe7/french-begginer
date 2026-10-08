"""YouTube の公開字幕を取り込み、既存 Source を上書きせずに保存する（Issue #192）。

字幕 provider 以外には依存しない。音声の取得はしない。
保存の再利用は `SourceIngestionService.commit` が担う。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from app.domain.source_ingestion import (
    MAX_SHORT_FIELD_CHARS,
    IngestionFailureKind,
    SourceIngestionError,
    SourceIngestionRequest,
    ingest_source,
)
from app.domain.tutor import utcnow
from app.ingestion.youtube import (
    YoutubeIngestionAdapter,
    YoutubeTranscriptProvider,
    parse_youtube_video,
)
from app.ingestion.youtube_errors import (
    MSG_INVALID_VIDEO,
    MSG_TEXT_TOO_LARGE,
    YoutubeIngestErrorCode,
    YoutubeIngestionError,
)
from app.repositories.protocols import SourceDocumentRepository
from app.services.source_ingestion_service import (
    CommittedIngestion,
    SourceIngestionService,
)


class YoutubeIngestionService:
    def __init__(
        self,
        sources: SourceDocumentRepository,
        provider: YoutubeTranscriptProvider,
        *,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._provider = provider
        self._clock = clock
        self._commit = SourceIngestionService(sources, clock=clock)

    def ingest_youtube(
        self,
        *,
        video: str,
        title: str | None = None,
        note: str | None = None,
        language: str = "fr",
    ) -> CommittedIngestion:
        """同じ動画と同じ字幕本文なら既存を返す。本文は上書きしない。"""

        parsed = parse_youtube_video(video)
        cleaned_title = _optional(title, limit=MAX_SHORT_FIELD_CHARS)
        cleaned_note = _optional(note, limit=2_000)
        cleaned_language = language.strip()
        if not cleaned_language or len(cleaned_language) > 32:
            raise YoutubeIngestionError(
                MSG_INVALID_VIDEO, code=YoutubeIngestErrorCode.invalid_video
            )
        request = SourceIngestionRequest(
            source_type="youtube_transcript",
            locator=parsed.canonical_locator,
            external_id=parsed.video_id,
            mime_type="text/plain",
            title=cleaned_title,
            note=cleaned_note,
            language=cleaned_language,
        )
        try:
            result = ingest_source(
                request,
                ingested_at=self._clock(),
                adapter=YoutubeIngestionAdapter(self._provider, parsed),
            )
        except YoutubeIngestionError:
            raise
        except SourceIngestionError as exc:
            if exc.kind is IngestionFailureKind.input_too_large:
                raise YoutubeIngestionError(
                    MSG_TEXT_TOO_LARGE, code=YoutubeIngestErrorCode.text_too_large
                ) from exc
            raise YoutubeIngestionError(
                MSG_INVALID_VIDEO, code=YoutubeIngestErrorCode.invalid_video
            ) from exc
        return self._commit.commit(result)


def _optional(value: str | None, *, limit: int) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned or len(cleaned) > limit:
        raise YoutubeIngestionError(
            MSG_INVALID_VIDEO, code=YoutubeIngestErrorCode.invalid_video
        )
    return cleaned
