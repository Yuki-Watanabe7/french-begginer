"""youtube-transcript-api による公開字幕の取得（Issue #192）。

このモジュールだけが字幕ライブラリと HTTP client を import する。
公開済みの caption track だけを読む。翻訳用の字幕は作らず、
動画の音声も取得しない。
"""

from __future__ import annotations

import importlib.metadata
from collections.abc import Callable, Iterable
from typing import Protocol

import requests
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    AgeRestricted,
    FailedToCreateConsentCookie,
    InvalidVideoId,
    IpBlocked,
    NoTranscriptFound,
    PoTokenRequired,
    RequestBlocked,
    TranscriptsDisabled,
    VideoUnavailable,
    VideoUnplayable,
    YouTubeDataUnparsable,
    YouTubeRequestFailed,
    YouTubeTranscriptApiException,
)

from app.ingestion.youtube import (
    YOUTUBE_FETCH_TIMEOUT_SECONDS,
    TranscriptSnippet,
    TranscriptTrack,
    require_video_id,
)
from app.ingestion.youtube_errors import (
    MSG_INVALID_VIDEO,
    MSG_MALFORMED_TRANSCRIPT,
    MSG_TRANSCRIPT_DISABLED,
    MSG_TRANSCRIPT_PROVIDER,
    MSG_TRANSCRIPT_TIMEOUT,
    MSG_TRANSCRIPT_UNAVAILABLE,
    MSG_VIDEO_UNAVAILABLE,
    YoutubeIngestErrorCode,
    YoutubeIngestionError,
)

PROVIDER_NAME = "youtube-transcript-api"


class _ListedTranscript(Protocol):
    language_code: str
    is_generated: bool

    def fetch(self) -> Iterable[object]: ...


class _TranscriptClient(Protocol):
    def list(self, video_id: str) -> Iterable[_ListedTranscript]: ...


class YoutubeTranscriptApiProvider:
    """1 リクエストにつき 1 インスタンスで使う。セッションはスレッド間で共有しない。"""

    provider_name = PROVIDER_NAME

    def __init__(
        self,
        *,
        client_factory: Callable[[], _TranscriptClient] | None = None,
        timeout_seconds: float = YOUTUBE_FETCH_TIMEOUT_SECONDS,
    ) -> None:
        self._client_factory = client_factory or self._default_client
        self._timeout_seconds = timeout_seconds
        self._cached: dict[tuple[str, str], _ListedTranscript] = {}
        self.provider_version = _package_version()

    def list_tracks(self, video_id: str) -> tuple[TranscriptTrack, ...]:
        video_id = require_video_id(video_id)
        client = self._client_factory()
        transcripts = self._invoke(lambda: tuple(client.list(video_id)))
        self._cached = {
            key: value for key, value in self._cached.items() if key[0] != video_id
        }
        tracks: list[TranscriptTrack] = []
        assert isinstance(transcripts, tuple)
        for transcript in transcripts:
            language_code = str(transcript.language_code)
            track_id = _track_id(
                language_code,
                is_generated=bool(transcript.is_generated),
                taken={track.track_id for track in tracks},
            )
            tracks.append(
                TranscriptTrack(
                    track_id=track_id,
                    language_code=language_code,
                    is_generated=bool(transcript.is_generated),
                    is_translation=False,
                    translated_from=None,
                )
            )
            self._cached[(video_id, track_id)] = transcript
        return tuple(tracks)

    def fetch_track(
        self, video_id: str, track: TranscriptTrack
    ) -> tuple[TranscriptSnippet, ...]:
        video_id = require_video_id(video_id)
        transcript = self._cached.get((video_id, track.track_id))
        if transcript is None:
            self.list_tracks(video_id)
            transcript = self._cached.get((video_id, track.track_id))
        if transcript is None:
            raise YoutubeIngestionError(
                MSG_TRANSCRIPT_UNAVAILABLE,
                code=YoutubeIngestErrorCode.transcript_unavailable,
            )
        fetched = self._invoke(lambda: tuple(transcript.fetch()))
        assert isinstance(fetched, tuple)
        return tuple(_snippet(item) for item in fetched)

    def _default_client(self) -> YouTubeTranscriptApi:
        return YouTubeTranscriptApi(http_client=_TimeoutSession(self._timeout_seconds))

    def _invoke(self, operation: Callable[[], object]) -> object:
        try:
            return operation()
        except YoutubeIngestionError:
            raise
        except Exception as exc:
            raise map_youtube_library_error(exc) from exc


class _TimeoutSession(requests.Session):
    """ライブラリが timeout を付けない GET / POST に、上限を足す。"""

    def __init__(self, timeout: float) -> None:
        super().__init__()
        self._timeout = timeout

    def request(self, method: str, url: str, **kwargs: object) -> requests.Response:
        kwargs.setdefault("timeout", self._timeout)
        return super().request(method, url, **kwargs)


def map_youtube_library_error(exc: Exception) -> YoutubeIngestionError:
    """ライブラリの例外を、本文も取得 URL も含まない公開エラーへ移す。"""

    if isinstance(exc, InvalidVideoId):
        return YoutubeIngestionError(
            MSG_INVALID_VIDEO, code=YoutubeIngestErrorCode.invalid_video
        )
    if isinstance(exc, TranscriptsDisabled):
        return YoutubeIngestionError(
            MSG_TRANSCRIPT_DISABLED, code=YoutubeIngestErrorCode.transcript_disabled
        )
    if isinstance(exc, NoTranscriptFound):
        return YoutubeIngestionError(
            MSG_TRANSCRIPT_UNAVAILABLE,
            code=YoutubeIngestErrorCode.transcript_unavailable,
        )
    if isinstance(exc, (VideoUnavailable, VideoUnplayable, AgeRestricted)):
        return YoutubeIngestionError(
            MSG_VIDEO_UNAVAILABLE, code=YoutubeIngestErrorCode.video_unavailable
        )
    if isinstance(exc, (requests.Timeout, TimeoutError)):
        return YoutubeIngestionError(
            MSG_TRANSCRIPT_TIMEOUT, code=YoutubeIngestErrorCode.transcript_timeout
        )
    if isinstance(
        exc,
        (
            RequestBlocked,
            IpBlocked,
            PoTokenRequired,
            YouTubeRequestFailed,
            YouTubeDataUnparsable,
            FailedToCreateConsentCookie,
            requests.RequestException,
            YouTubeTranscriptApiException,
        ),
    ):
        return YoutubeIngestionError(
            MSG_TRANSCRIPT_PROVIDER,
            code=YoutubeIngestErrorCode.transcript_provider_error,
        )
    return YoutubeIngestionError(
        MSG_TRANSCRIPT_PROVIDER, code=YoutubeIngestErrorCode.transcript_provider_error
    )


def _snippet(item: object) -> TranscriptSnippet:
    try:
        text = item.text if isinstance(item.text, str) else ""
        start = float(item.start)
        duration = float(item.duration)
    except (AttributeError, TypeError, ValueError) as exc:
        raise YoutubeIngestionError(
            MSG_MALFORMED_TRANSCRIPT,
            code=YoutubeIngestErrorCode.malformed_transcript,
        ) from exc
    return TranscriptSnippet(text=text, start_seconds=start, duration_seconds=duration)


def _track_id(language_code: str, *, is_generated: bool, taken: set[str]) -> str:
    kind = "generated" if is_generated else "manual"
    base = f"{kind}:{language_code}"
    track_id = base
    suffix = 2
    while track_id in taken:
        track_id = f"{base}#{suffix}"
        suffix += 1
    return track_id


def _package_version() -> str | None:
    try:
        return importlib.metadata.version(PROVIDER_NAME)
    except importlib.metadata.PackageNotFoundError:
        return None
