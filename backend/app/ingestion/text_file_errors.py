"""テキスト / Markdown 取り込みの失敗分類（Issue #194）。

メッセージは利用者向けで、ファイル本文は含めない。
"""

from __future__ import annotations

from enum import StrEnum

from app.domain.source_ingestion import IngestionFailureKind, SourceIngestionError


class TextFileIngestErrorCode(StrEnum):
    """API が利用者へ区別して返す失敗コード。"""

    invalid_text_file = "invalid_text_file"
    malformed_text = "malformed_text"
    unsupported_media = "unsupported_media"
    file_too_large = "file_too_large"
    text_too_large = "text_too_large"
    text_empty = "text_empty"


_KIND_BY_CODE: dict[TextFileIngestErrorCode, IngestionFailureKind] = {
    TextFileIngestErrorCode.invalid_text_file: IngestionFailureKind.validation,
    TextFileIngestErrorCode.malformed_text: IngestionFailureKind.validation,
    TextFileIngestErrorCode.unsupported_media: IngestionFailureKind.unsupported_media,
    TextFileIngestErrorCode.file_too_large: IngestionFailureKind.input_too_large,
    TextFileIngestErrorCode.text_too_large: IngestionFailureKind.input_too_large,
    TextFileIngestErrorCode.text_empty: IngestionFailureKind.validation,
}


class TextFileIngestionError(SourceIngestionError):
    """テキストファイルの検証または正規化で拒否した。"""

    def __init__(self, message: str, *, code: TextFileIngestErrorCode) -> None:
        super().__init__(message, kind=_KIND_BY_CODE[code])
        self.code = code


MSG_INVALID_TEXT_FILE = "テキストファイルの指定が不正"
MSG_EMPTY_FILE = "ファイルが空"
MSG_FILENAME = "ファイル名が不正"
MSG_MALFORMED_TEXT = "テキストファイルを読み取れなかった"
MSG_UNSUPPORTED_MEDIA = "テキストまたは Markdown 以外のファイルは取り込めない"
MSG_FILE_TOO_LARGE = "テキストファイルのサイズが上限を超えている"
MSG_TEXT_TOO_LARGE = "テキストから取り出した本文が上限を超えている"
MSG_TEXT_EMPTY = "テキストの本文が空"
