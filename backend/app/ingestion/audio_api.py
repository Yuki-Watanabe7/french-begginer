"""OpenAI Audio transcriptions による文字起こし（Issue #193）。

このモジュールだけが文字起こし用の OpenAI SDK を import する。
`audio.transcriptions` だけを呼ぶ。翻訳エンドポイントと TTS は使わない。
API key は metadata に残さない。retry は一時障害だけ、回数上限付き。
"""

from __future__ import annotations

import math
import os
from collections.abc import Callable
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)

from app.ingestion.audio import (
    AudioPayload,
    TranscriptionResult,
    TranscriptSegment,
    hint_to_iso639_1,
)
from app.ingestion.audio_errors import (
    MSG_AUTH_FAILED,
    MSG_INVALID_TRANSCRIPT,
    MSG_NOT_CONFIGURED,
    MSG_PROVIDER,
    MSG_TIMEOUT,
    AudioIngestErrorCode,
    AudioIngestionError,
)

PROVIDER_NAME = "openai"
DEFAULT_TRANSCRIPTION_MODEL = "whisper-1"
TRANSCRIPTION_VERSION = "openai-audio-transcriptions-v1"
TRANSCRIPTION_TIMEOUT_SECONDS = 120.0
MAX_TRANSCRIPTION_ATTEMPTS = 2


class OpenAITranscriptionProvider:
    """検証済みの音声バイト列を、原文の文字起こしにする。"""

    provider_name = PROVIDER_NAME
    transcription_version = TRANSCRIPTION_VERSION

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = DEFAULT_TRANSCRIPTION_MODEL,
        timeout_seconds: float = TRANSCRIPTION_TIMEOUT_SECONDS,
        max_attempts: int = MAX_TRANSCRIPTION_ATTEMPTS,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._api_key = api_key
        self.model = model
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max(1, max_attempts)
        self._client_factory = client_factory or self._default_client

    def transcribe(
        self, audio: AudioPayload, language_hint: str
    ) -> TranscriptionResult:
        client = self._client_factory()
        last: AudioIngestionError | None = None
        for attempt in range(self._max_attempts):
            try:
                return self._once(client, audio, language_hint)
            except AudioIngestionError as exc:
                last = exc
                if not exc.retryable or attempt + 1 >= self._max_attempts:
                    raise
        raise last  # pragma: no cover

    def _default_client(self) -> OpenAI:
        api_key = (
            self._api_key
            if self._api_key is not None
            else os.environ.get("OPENAI_API_KEY")
        )
        if not api_key or not api_key.strip():
            raise AudioIngestionError(
                MSG_NOT_CONFIGURED,
                code=AudioIngestErrorCode.transcription_not_configured,
            )
        return OpenAI(
            api_key=api_key.strip(),
            timeout=self._timeout_seconds,
            max_retries=0,
        )

    def _once(
        self, client: Any, audio: AudioPayload, language_hint: str
    ) -> TranscriptionResult:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "file": (audio.filename, audio.data, audio.media_type),
            "response_format": "verbose_json",
            "timestamp_granularities": ["segment"],
            "timeout": self._timeout_seconds,
        }
        iso = hint_to_iso639_1(language_hint)
        if iso is not None:
            kwargs["language"] = iso
        try:
            payload = client.audio.transcriptions.create(**kwargs)
            return transcription_from_payload(payload)
        except AudioIngestionError:
            raise
        except RateLimitError as exc:
            raise AudioIngestionError(
                MSG_PROVIDER,
                code=AudioIngestErrorCode.transcription_provider_error,
            ) from exc
        except APITimeoutError as exc:
            raise AudioIngestionError(
                MSG_TIMEOUT, code=AudioIngestErrorCode.transcription_timeout
            ) from exc
        except APIConnectionError as exc:
            raise AudioIngestionError(
                MSG_PROVIDER,
                code=AudioIngestErrorCode.transcription_provider_error,
            ) from exc
        except InternalServerError as exc:
            raise AudioIngestionError(
                MSG_PROVIDER,
                code=AudioIngestErrorCode.transcription_provider_error,
            ) from exc
        except AuthenticationError as exc:
            raise AudioIngestionError(
                MSG_AUTH_FAILED,
                code=AudioIngestErrorCode.transcription_not_configured,
            ) from exc
        except BadRequestError as exc:
            raise AudioIngestionError(
                MSG_INVALID_TRANSCRIPT,
                code=AudioIngestErrorCode.invalid_transcript,
            ) from exc
        except APIStatusError as exc:
            if exc.status_code is not None and exc.status_code >= 500:
                raise AudioIngestionError(
                    MSG_PROVIDER,
                    code=AudioIngestErrorCode.transcription_provider_error,
                ) from exc
            raise AudioIngestionError(
                MSG_INVALID_TRANSCRIPT,
                code=AudioIngestErrorCode.invalid_transcript,
            ) from exc


def transcription_from_payload(payload: object) -> TranscriptionResult:
    """SDK の応答を、時刻が無ければ null のままの結果にする。"""

    if isinstance(payload, str):
        return TranscriptionResult(
            text=payload,
            segments=None,
            detected_language=None,
            is_translation=False,
        )
    text = _field(payload, "text")
    if not isinstance(text, str):
        raise AudioIngestionError(
            MSG_INVALID_TRANSCRIPT, code=AudioIngestErrorCode.invalid_transcript
        )
    language = _field(payload, "language")
    detected = (
        language.strip() if isinstance(language, str) and language.strip() else None
    )
    task = _field(payload, "task")
    is_translation = isinstance(task, str) and task.strip().lower() == "translate"
    raw_segments = _field(payload, "segments")
    if raw_segments is None:
        return TranscriptionResult(
            text=text,
            segments=None,
            detected_language=detected,
            is_translation=is_translation,
        )
    if isinstance(raw_segments, str) or not isinstance(raw_segments, (list, tuple)):
        raise AudioIngestionError(
            MSG_INVALID_TRANSCRIPT, code=AudioIngestErrorCode.invalid_transcript
        )
    segments = tuple(_segment(item) for item in raw_segments)
    return TranscriptionResult(
        text=text,
        segments=segments,
        detected_language=detected,
        is_translation=is_translation,
    )


def _segment(item: object) -> TranscriptSegment:
    text = _field(item, "text")
    if not isinstance(text, str):
        raise AudioIngestionError(
            MSG_INVALID_TRANSCRIPT, code=AudioIngestErrorCode.invalid_transcript
        )
    start = _optional_seconds(_field(item, "start"))
    end = _optional_seconds(_field(item, "end"))
    return TranscriptSegment(text=text, start_seconds=start, end_seconds=end)


def _optional_seconds(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AudioIngestionError(
            MSG_INVALID_TRANSCRIPT, code=AudioIngestErrorCode.invalid_transcript
        )
    number = float(value)
    if not math.isfinite(number):
        raise AudioIngestionError(
            MSG_INVALID_TRANSCRIPT, code=AudioIngestErrorCode.invalid_transcript
        )
    return number


def _field(payload: object, name: str) -> object:
    if isinstance(payload, dict):
        return payload.get(name)
    return getattr(payload, name, None)
