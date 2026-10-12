"""YouTube transcript 取り込みの失敗分類（Issue #192）。

メッセージは利用者向けで、字幕本文や取得先の URL は含めない。
音声の download へ切り替える失敗コードは無い。
"""

from __future__ import annotations

from enum import StrEnum

from app.domain.source_ingestion import IngestionFailureKind, SourceIngestionError


class YoutubeIngestErrorCode(StrEnum):
    """API が利用者へ区別して返す失敗コード。"""

    invalid_video = "invalid_video"
    transcript_unavailable = "transcript_unavailable"
    transcript_disabled = "transcript_disabled"
    video_unavailable = "video_unavailable"
    malformed_transcript = "malformed_transcript"
    transcript_empty = "transcript_empty"
    text_too_large = "text_too_large"
    transcript_timeout = "transcript_timeout"
    transcript_provider_error = "transcript_provider_error"


_KIND_BY_CODE: dict[YoutubeIngestErrorCode, IngestionFailureKind] = {
    YoutubeIngestErrorCode.invalid_video: IngestionFailureKind.validation,
    YoutubeIngestErrorCode.transcript_unavailable: IngestionFailureKind.validation,
    YoutubeIngestErrorCode.transcript_disabled: IngestionFailureKind.validation,
    YoutubeIngestErrorCode.video_unavailable: IngestionFailureKind.validation,
    YoutubeIngestErrorCode.malformed_transcript: IngestionFailureKind.validation,
    YoutubeIngestErrorCode.transcript_empty: IngestionFailureKind.validation,
    YoutubeIngestErrorCode.text_too_large: IngestionFailureKind.input_too_large,
    YoutubeIngestErrorCode.transcript_timeout: IngestionFailureKind.timeout,
    YoutubeIngestErrorCode.transcript_provider_error: IngestionFailureKind.provider,
}


class YoutubeIngestionError(SourceIngestionError):
    """YouTube の指定、または公開字幕の取得で拒否した。"""

    def __init__(
        self,
        message: str,
        *,
        code: YoutubeIngestErrorCode,
        available_languages: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message, kind=_KIND_BY_CODE[code])
        self.code = code
        self.available_languages = available_languages


MSG_INVALID_VIDEO = "YouTube の URL または video ID が不正"
MSG_PLAYLIST_UNSUPPORTED = "playlist の一括取り込みはできない"
MSG_TRANSCRIPT_UNAVAILABLE = "指定した言語の公開字幕が無い"
MSG_TRANSCRIPT_DISABLED = "この動画では字幕が無効"
MSG_VIDEO_UNAVAILABLE = "この動画の公開字幕は取得できない"
MSG_MALFORMED_TRANSCRIPT = "字幕の時刻が不正"
MSG_TRANSCRIPT_EMPTY = "字幕の本文が空"
MSG_TEXT_TOO_LARGE = "字幕から取り出した本文が上限を超えている"
MSG_TRANSCRIPT_TIMEOUT = "字幕の取得が時間内に終わらなかった"
MSG_TRANSCRIPT_PROVIDER = "字幕の取得に失敗した"
