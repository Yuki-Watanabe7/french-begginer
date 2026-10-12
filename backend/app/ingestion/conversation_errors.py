"""structured conversation JSON 取り込みの失敗分類（Issue #194）。

メッセージは利用者向けで、会話本文や未知フィールドの値は含めない。
"""

from __future__ import annotations

from enum import StrEnum

from app.domain.source_ingestion import IngestionFailureKind, SourceIngestionError


class ConversationIngestErrorCode(StrEnum):
    """API が利用者へ区別して返す失敗コード。"""

    invalid_conversation = "invalid_conversation"
    malformed_conversation = "malformed_conversation"
    unsupported_media = "unsupported_media"
    file_too_large = "file_too_large"
    text_too_large = "text_too_large"
    conversation_empty = "conversation_empty"


_KIND_BY_CODE: dict[ConversationIngestErrorCode, IngestionFailureKind] = {
    ConversationIngestErrorCode.invalid_conversation: IngestionFailureKind.validation,
    ConversationIngestErrorCode.malformed_conversation: (
        IngestionFailureKind.validation
    ),
    ConversationIngestErrorCode.unsupported_media: (
        IngestionFailureKind.unsupported_media
    ),
    ConversationIngestErrorCode.file_too_large: IngestionFailureKind.input_too_large,
    ConversationIngestErrorCode.text_too_large: IngestionFailureKind.input_too_large,
    ConversationIngestErrorCode.conversation_empty: IngestionFailureKind.validation,
}


class ConversationIngestionError(SourceIngestionError):
    """会話 JSON の検証または正規化で拒否した。"""

    def __init__(self, message: str, *, code: ConversationIngestErrorCode) -> None:
        super().__init__(message, kind=_KIND_BY_CODE[code])
        self.code = code


MSG_INVALID_CONVERSATION = "会話ログの指定が不正"
MSG_EMPTY_FILE = "ファイルが空"
MSG_FILENAME = "ファイル名が不正"
MSG_MALFORMED_CONVERSATION = "会話ログの形式を読み取れなかった"
MSG_UNSUPPORTED_MEDIA = "会話ログは JSON 以外を取り込めない"
MSG_FILE_TOO_LARGE = "会話ログのサイズが上限を超えている"
MSG_TEXT_TOO_LARGE = "会話ログから取り出した本文が上限を超えている"
MSG_CONVERSATION_EMPTY = "会話ログの本文が空"
