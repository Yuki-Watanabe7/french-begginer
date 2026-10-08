"""SRT / VTT 取り込みの失敗分類（Issue #192）。

メッセージは利用者向けで、字幕本文は含めない。
"""

from __future__ import annotations

from enum import StrEnum

from app.domain.source_ingestion import IngestionFailureKind, SourceIngestionError


class SubtitleIngestErrorCode(StrEnum):
    """API が利用者へ区別して返す失敗コード。"""

    invalid_subtitle = "invalid_subtitle"
    malformed_subtitle = "malformed_subtitle"
    unsupported_media = "unsupported_media"
    file_too_large = "file_too_large"
    text_too_large = "text_too_large"
    subtitle_empty = "subtitle_empty"


_KIND_BY_CODE: dict[SubtitleIngestErrorCode, IngestionFailureKind] = {
    SubtitleIngestErrorCode.invalid_subtitle: IngestionFailureKind.validation,
    SubtitleIngestErrorCode.malformed_subtitle: IngestionFailureKind.validation,
    SubtitleIngestErrorCode.unsupported_media: IngestionFailureKind.unsupported_media,
    SubtitleIngestErrorCode.file_too_large: IngestionFailureKind.input_too_large,
    SubtitleIngestErrorCode.text_too_large: IngestionFailureKind.input_too_large,
    SubtitleIngestErrorCode.subtitle_empty: IngestionFailureKind.validation,
}


class SubtitleIngestionError(SourceIngestionError):
    """字幕ファイルの検証または解析で拒否した。"""

    def __init__(self, message: str, *, code: SubtitleIngestErrorCode) -> None:
        super().__init__(message, kind=_KIND_BY_CODE[code])
        self.code = code


MSG_INVALID_SUBTITLE = "字幕ファイルの指定が不正"
MSG_EMPTY_FILE = "ファイルが空"
MSG_FILENAME = "ファイル名が不正"
MSG_MALFORMED_SUBTITLE = "字幕の時刻を読み取れなかった"
MSG_UNSUPPORTED_MEDIA = "SRT / VTT 以外のファイルは取り込めない"
MSG_FILE_TOO_LARGE = "字幕ファイルのサイズが上限を超えている"
MSG_TEXT_TOO_LARGE = "字幕から取り出した本文が上限を超えている"
MSG_SUBTITLE_EMPTY = "字幕の本文が空"
