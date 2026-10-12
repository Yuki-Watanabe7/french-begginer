"""音声文字起こしの失敗分類（Issue #193）。

メッセージは利用者向けで、音声バイト列、API key、provider の応答本文は含めない。
翻訳結果を原文として保存したことにはしない。
"""

from __future__ import annotations

from enum import StrEnum

from app.domain.source_ingestion import IngestionFailureKind, SourceIngestionError


class AudioIngestErrorCode(StrEnum):
    """API が利用者へ区別して返す失敗コード。"""

    invalid_audio = "invalid_audio"
    malformed_audio = "malformed_audio"
    unsupported_media = "unsupported_media"
    file_too_large = "file_too_large"
    audio_too_long = "audio_too_long"
    text_too_large = "text_too_large"
    transcript_empty = "transcript_empty"
    invalid_transcript = "invalid_transcript"
    translated_transcript = "translated_transcript"
    transcription_not_configured = "transcription_not_configured"
    transcription_timeout = "transcription_timeout"
    transcription_provider_error = "transcription_provider_error"


_KIND_BY_CODE: dict[AudioIngestErrorCode, IngestionFailureKind] = {
    AudioIngestErrorCode.invalid_audio: IngestionFailureKind.validation,
    AudioIngestErrorCode.malformed_audio: IngestionFailureKind.validation,
    AudioIngestErrorCode.unsupported_media: IngestionFailureKind.unsupported_media,
    AudioIngestErrorCode.file_too_large: IngestionFailureKind.input_too_large,
    AudioIngestErrorCode.audio_too_long: IngestionFailureKind.input_too_large,
    AudioIngestErrorCode.text_too_large: IngestionFailureKind.input_too_large,
    AudioIngestErrorCode.transcript_empty: IngestionFailureKind.validation,
    AudioIngestErrorCode.invalid_transcript: IngestionFailureKind.validation,
    AudioIngestErrorCode.translated_transcript: IngestionFailureKind.validation,
    AudioIngestErrorCode.transcription_not_configured: (
        IngestionFailureKind.not_implemented
    ),
    AudioIngestErrorCode.transcription_timeout: IngestionFailureKind.timeout,
    AudioIngestErrorCode.transcription_provider_error: IngestionFailureKind.provider,
}


class AudioIngestionError(SourceIngestionError):
    """音声の検証、または文字起こし provider の呼び出しで拒否した。"""

    def __init__(self, message: str, *, code: AudioIngestErrorCode) -> None:
        super().__init__(message, kind=_KIND_BY_CODE[code])
        self.code = code


MSG_INVALID_AUDIO = "音声ファイルの指定が不正"
MSG_EMPTY_FILE = "ファイルが空"
MSG_FILENAME = "ファイル名が不正"
MSG_MALFORMED_AUDIO = "音声ファイルを読み取れなかった"
MSG_UNSUPPORTED_MEDIA = "対応していない音声形式"
MSG_FILE_TOO_LARGE = "音声ファイルのサイズが上限を超えている"
MSG_AUDIO_TOO_LONG = "音声の長さが上限を超えている"
MSG_TEXT_TOO_LARGE = "文字起こしの本文が上限を超えている"
MSG_TRANSCRIPT_EMPTY = "文字起こしの本文が空"
MSG_INVALID_TRANSCRIPT = "文字起こしの応答が不正"
MSG_TRANSLATED = "自動翻訳の結果は原文として保存しない"
MSG_NOT_CONFIGURED = "音声の文字起こしが設定されていない"
MSG_AUTH_FAILED = "音声の文字起こしの認証に失敗した"
MSG_TIMEOUT = "音声の文字起こしが時間内に終わらなかった"
MSG_PROVIDER = "音声の文字起こしに失敗した"
