"""YouTube の公開字幕を SourceIngestionResult にする（Issue #192）。

video ID の検証と言語選択はここにある。取得そのものは
`YoutubeTranscriptProvider` の実装に閉じ、通常のテストは fake を渡す。
翻訳字幕を新たに作る処理と、動画音声の取得は持たない。
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from urllib.parse import parse_qs, urlsplit, urlunsplit

from app.domain.source_ingestion import (
    MAX_LOCATOR_CHARS,
    MAX_SHORT_FIELD_CHARS,
    IngestionFailureKind,
    SourceIngestionError,
    SourceIngestionRequest,
    SourceIngestionResult,
    SourceType,
    assemble_ingestion_result,
)
from app.ingestion.timed_text import TimedCue, TimedTextError, cues_to_drafts
from app.ingestion.youtube_errors import (
    MSG_INVALID_VIDEO,
    MSG_MALFORMED_TRANSCRIPT,
    MSG_PLAYLIST_UNSUPPORTED,
    MSG_TEXT_TOO_LARGE,
    MSG_TRANSCRIPT_EMPTY,
    MSG_TRANSCRIPT_UNAVAILABLE,
    YoutubeIngestErrorCode,
    YoutubeIngestionError,
)

YOUTUBE_ADAPTER_VERSION = "youtube-transcript-v1"
YOUTUBE_FETCH_TIMEOUT_SECONDS = 10.0
MIN_CUE_SECONDS = 0.001

_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_WATCH_HOSTS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtube-nocookie.com",
        "www.youtube-nocookie.com",
    }
)
_SHORT_HOSTS = frozenset({"youtu.be", "www.youtu.be"})
_DIRECT_PATHS = frozenset({"embed", "shorts", "live", "v"})


@dataclass(frozen=True)
class YoutubeVideoRef:
    """検証済みの 1 本の動画。playlist は持たない。"""

    video_id: str
    original_url: str
    canonical_locator: str


@dataclass(frozen=True)
class TranscriptTrack:
    """公開されている 1 本の字幕トラック。翻訳 API で作ったトラックは含めない。"""

    track_id: str
    language_code: str
    is_generated: bool
    is_translation: bool
    translated_from: str | None


@dataclass(frozen=True)
class TranscriptSnippet:
    text: str
    start_seconds: float
    duration_seconds: float


@dataclass(frozen=True)
class SelectedTranscript:
    track: TranscriptTrack
    rule: str


class YoutubeTranscriptProvider(Protocol):
    """公開字幕の一覧と、選んだ 1 トラックの取得。音声取得は持たない。"""

    provider_name: str
    provider_version: str | None

    def list_tracks(self, video_id: str) -> tuple[TranscriptTrack, ...]: ...

    def fetch_track(
        self, video_id: str, track: TranscriptTrack
    ) -> tuple[TranscriptSnippet, ...]: ...


def parse_youtube_video(value: str) -> YoutubeVideoRef:
    """URL または 11 文字の video ID を、同一動画として比較できる形にする。"""

    raw = value.strip()
    if not raw or len(raw) > MAX_LOCATOR_CHARS or any(char.isspace() for char in raw):
        raise YoutubeIngestionError(
            MSG_INVALID_VIDEO, code=YoutubeIngestErrorCode.invalid_video
        )
    if _VIDEO_ID.fullmatch(raw):
        return _video_ref(raw, f"https://www.youtube.com/watch?v={raw}")
    if "://" not in raw:
        raise YoutubeIngestionError(
            MSG_INVALID_VIDEO, code=YoutubeIngestErrorCode.invalid_video
        )
    parsed = urlsplit(raw)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise YoutubeIngestionError(
            MSG_INVALID_VIDEO, code=YoutubeIngestErrorCode.invalid_video
        )
    if parsed.username or parsed.password or "@" in parsed.netloc:
        raise YoutubeIngestionError(
            MSG_INVALID_VIDEO, code=YoutubeIngestErrorCode.invalid_video
        )
    host = (parsed.hostname or "").lower().rstrip(".")
    video_id = _video_id_from_url(host, parsed.path, parsed.query)
    original = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
    return _video_ref(video_id, original)


def require_video_id(video_id: str) -> str:
    """provider に渡す直前の ID。URL のままライブラリへ渡さない。"""

    if not _VIDEO_ID.fullmatch(video_id):
        raise YoutubeIngestionError(
            MSG_INVALID_VIDEO, code=YoutubeIngestErrorCode.invalid_video
        )
    return video_id


def language_primary(code: str) -> str:
    """`fr-FR` と `fr_FR` を、比較用の `fr` にする。"""

    token = code.strip().lower().replace("_", "-")
    return token.split("-", 1)[0]


def select_transcript_track(
    tracks: Sequence[TranscriptTrack], preferred_language: str
) -> SelectedTranscript:
    """希望言語の公開字幕を 1 本選ぶ。別言語へのフォールバックはしない。

    同じ言語では、翻訳でない手動字幕、翻訳でない自動字幕、翻訳字幕の順。
    同点は language code と track id の辞書順で決める。
    """

    preferred = preferred_language.strip()
    if not preferred:
        raise YoutubeIngestionError(
            MSG_INVALID_VIDEO, code=YoutubeIngestErrorCode.invalid_video
        )
    preferred_primary = language_primary(preferred)
    matches = [
        track
        for track in tracks
        if language_primary(track.language_code) == preferred_primary
    ]
    if not matches:
        codes = tuple(sorted({track.language_code for track in tracks}))
        raise YoutubeIngestionError(
            MSG_TRANSCRIPT_UNAVAILABLE,
            code=YoutubeIngestErrorCode.transcript_unavailable,
            available_languages=codes,
        )
    chosen = min(matches, key=lambda track: _track_rank(track, preferred))
    return SelectedTranscript(track=chosen, rule=_selection_rule(chosen))


def asr_language(tracks: Sequence[TranscriptTrack]) -> str | None:
    """自動字幕が 1 言語だけのとき、その言語を発話の根拠にする。"""

    codes = sorted(
        {
            language_primary(track.language_code)
            for track in tracks
            if track.is_generated and not track.is_translation
        }
    )
    if len(codes) == 1:
        return codes[0]
    return None


class YoutubeIngestionAdapter:
    """1 本の動画の公開字幕を、時刻 provenance 付きの plain text にする。"""

    source_type: SourceType = "youtube_transcript"
    adapter_version = YOUTUBE_ADAPTER_VERSION

    def __init__(
        self, provider: YoutubeTranscriptProvider, video: YoutubeVideoRef
    ) -> None:
        self._provider = provider
        self._video = video

    def ingest(
        self, request: SourceIngestionRequest, *, ingested_at: datetime
    ) -> SourceIngestionResult:
        if request.source_type != "youtube_transcript":
            raise SourceIngestionError(
                "YoutubeIngestionAdapter は youtube_transcript 専用",
                kind=IngestionFailureKind.validation,
            )
        video_id = self._video.video_id
        if request.locator not in (None, self._video.canonical_locator):
            raise YoutubeIngestionError(
                MSG_INVALID_VIDEO, code=YoutubeIngestErrorCode.invalid_video
            )
        if request.external_id not in (None, video_id):
            raise YoutubeIngestionError(
                MSG_INVALID_VIDEO, code=YoutubeIngestErrorCode.invalid_video
            )
        tracks = self._provider.list_tracks(video_id)
        if not tracks:
            raise YoutubeIngestionError(
                MSG_TRANSCRIPT_UNAVAILABLE,
                code=YoutubeIngestErrorCode.transcript_unavailable,
            )
        selected = select_transcript_track(tracks, request.language)
        snippets = self._provider.fetch_track(video_id, selected.track)
        try:
            built = cues_to_drafts(_snippets_to_cues(snippets))
        except TimedTextError as exc:
            raise YoutubeIngestionError(
                MSG_MALFORMED_TRANSCRIPT,
                code=YoutubeIngestErrorCode.malformed_transcript,
            ) from exc
        if not built.drafts:
            raise YoutubeIngestionError(
                MSG_TRANSCRIPT_EMPTY, code=YoutubeIngestErrorCode.transcript_empty
            )
        metadata = _metadata(
            video=self._video,
            tracks=tracks,
            selected=selected,
            requested_language=request.language.strip(),
            cue_count=len(built.drafts),
            empty_cue_count=built.empty_cue_count,
            provider_version=self._provider.provider_version,
            note=request.note,
        )
        try:
            return assemble_ingestion_result(
                source_type="youtube_transcript",
                title=_choose_title(request.title, video_id),
                language=selected.track.language_code,
                drafts=built.drafts,
                adapter_version=self.adapter_version,
                ingested_at=ingested_at,
                canonical_locator=self._video.canonical_locator,
                external_id=video_id,
                fetched_at=ingested_at,
                provider=self._provider.provider_name,
                mime_type="text/plain",
                metadata=metadata,
            )
        except SourceIngestionError as exc:
            if exc.kind is IngestionFailureKind.input_too_large:
                raise YoutubeIngestionError(
                    MSG_TEXT_TOO_LARGE, code=YoutubeIngestErrorCode.text_too_large
                ) from exc
            raise


def _snippets_to_cues(snippets: Sequence[TranscriptSnippet]) -> tuple[TimedCue, ...]:
    cues: list[TimedCue] = []
    for snippet in snippets:
        start = snippet.start_seconds
        duration = snippet.duration_seconds
        if (
            not math.isfinite(start)
            or not math.isfinite(duration)
            or start < 0
            or duration < 0
        ):
            raise YoutubeIngestionError(
                MSG_MALFORMED_TRANSCRIPT,
                code=YoutubeIngestErrorCode.malformed_transcript,
            )
        if duration >= MIN_CUE_SECONDS:
            end = start + duration
        else:
            end = start + MIN_CUE_SECONDS
        cues.append(TimedCue(start_seconds=start, end_seconds=end, text=snippet.text))
    return tuple(cues)


def _metadata(
    *,
    video: YoutubeVideoRef,
    tracks: Sequence[TranscriptTrack],
    selected: SelectedTranscript,
    requested_language: str,
    cue_count: int,
    empty_cue_count: int,
    provider_version: str | None,
    note: str | None,
) -> dict[str, Any]:
    track = selected.track
    metadata: dict[str, Any] = {
        "video_id": video.video_id,
        "original_url": video.original_url,
        "requested_language": requested_language,
        "transcript_language": track.language_code,
        "caption_kind": "generated" if track.is_generated else "manual",
        "transcript_is_translation": track.is_translation,
        "selection_rule": selected.rule,
        "track_id": track.track_id,
        "available_language_codes": sorted({item.language_code for item in tracks}),
        "cue_count": cue_count,
        "empty_cue_count": empty_cue_count,
    }
    if track.is_translation and track.translated_from:
        metadata["translated_from"] = track.translated_from
    spoken = asr_language(tracks)
    if spoken is not None:
        metadata["asr_language"] = spoken
        metadata["speech_language"] = spoken
        metadata["transcript_matches_speech"] = (
            not track.is_translation and language_primary(track.language_code) == spoken
        )
    if provider_version:
        metadata["provider_version"] = provider_version
    if note and note.strip():
        metadata["note"] = note.strip()
    return metadata


def _track_rank(
    track: TranscriptTrack, preferred: str
) -> tuple[bool, bool, int, str, str]:
    exact = 0 if track.language_code.lower() == preferred.lower() else 1
    return (
        track.is_translation,
        track.is_generated,
        exact,
        track.language_code.lower(),
        track.track_id,
    )


def _selection_rule(track: TranscriptTrack) -> str:
    if track.is_translation and track.is_generated:
        return "generated_translation"
    if track.is_translation:
        return "manual_translation"
    if track.is_generated:
        return "generated_caption"
    return "manual_caption"


def _video_ref(video_id: str, original_url: str) -> YoutubeVideoRef:
    return YoutubeVideoRef(
        video_id=video_id,
        original_url=original_url,
        canonical_locator=f"youtube:{video_id}",
    )


def _video_id_from_url(host: str, path: str, query: str) -> str:
    parts = [segment for segment in path.split("/") if segment]
    parameters = parse_qs(query, keep_blank_values=False)
    if host in _SHORT_HOSTS:
        if len(parts) == 1 and _VIDEO_ID.fullmatch(parts[0]):
            return parts[0]
        raise YoutubeIngestionError(
            MSG_INVALID_VIDEO, code=YoutubeIngestErrorCode.invalid_video
        )
    if host not in _WATCH_HOSTS:
        raise YoutubeIngestionError(
            MSG_INVALID_VIDEO, code=YoutubeIngestErrorCode.invalid_video
        )
    if not parts or parts[0] == "watch":
        return _id_from_watch_query(parameters)
    if parts[0] in _DIRECT_PATHS:
        if len(parts) == 2 and _VIDEO_ID.fullmatch(parts[1]):
            return parts[1]
        raise YoutubeIngestionError(
            MSG_INVALID_VIDEO, code=YoutubeIngestErrorCode.invalid_video
        )
    if parts[0] == "playlist" or ("list" in parameters and "v" not in parameters):
        raise YoutubeIngestionError(
            MSG_PLAYLIST_UNSUPPORTED, code=YoutubeIngestErrorCode.invalid_video
        )
    raise YoutubeIngestionError(
        MSG_INVALID_VIDEO, code=YoutubeIngestErrorCode.invalid_video
    )


def _id_from_watch_query(parameters: dict[str, list[str]]) -> str:
    video_ids = parameters.get("v", [])
    if len(video_ids) == 1 and _VIDEO_ID.fullmatch(video_ids[0]):
        return video_ids[0]
    if "list" in parameters and "v" not in parameters:
        raise YoutubeIngestionError(
            MSG_PLAYLIST_UNSUPPORTED, code=YoutubeIngestErrorCode.invalid_video
        )
    raise YoutubeIngestionError(
        MSG_INVALID_VIDEO, code=YoutubeIngestErrorCode.invalid_video
    )


def _choose_title(override: str | None, video_id: str) -> str:
    chosen = override.strip() if override else ""
    if not chosen:
        chosen = f"YouTube {video_id}"
    collapsed = " ".join(chosen.split())
    bounded = collapsed[:MAX_SHORT_FIELD_CHARS].strip()
    return bounded or f"YouTube {video_id}"
