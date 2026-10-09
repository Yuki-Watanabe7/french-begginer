"""アップロードされた音声を SourceIngestionResult にする（Issue #193）。

ファイル検証と `TranscriptionProvider` の境界はここにある。
OpenAI SDK は `audio_api` に閉じ、通常のテストは fake provider を渡す。
翻訳 API は呼ばない。raw audio は Source に保存しない。

扱える上限はファイル 25_000_000 バイト、再生時間を読めたとき 600 秒。
長時間録音の分割と再開アップロードはしない。
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, BinaryIO, Literal, Protocol

from app.domain.source_ingestion import (
    MAX_SHORT_FIELD_CHARS,
    IngestionFailureKind,
    SourceIngestionError,
    SourceIngestionRequest,
    SourceIngestionResult,
    SourceSegmentDraft,
    SourceType,
    assemble_ingestion_result,
    normalize_source_text,
)
from app.ingestion.audio_errors import (
    MSG_AUDIO_TOO_LONG,
    MSG_EMPTY_FILE,
    MSG_FILE_TOO_LARGE,
    MSG_FILENAME,
    MSG_INVALID_AUDIO,
    MSG_INVALID_TRANSCRIPT,
    MSG_MALFORMED_AUDIO,
    MSG_TEXT_TOO_LARGE,
    MSG_TRANSCRIPT_EMPTY,
    MSG_TRANSLATED,
    MSG_UNSUPPORTED_MEDIA,
    AudioIngestErrorCode,
    AudioIngestionError,
)
from app.ingestion.timed_text import TimedCue, TimedTextError, cues_to_drafts

AUDIO_ADAPTER_VERSION = "audio-transcript-v1"
MAX_AUDIO_BYTES = 25_000_000
MAX_AUDIO_SECONDS = 600.0
MIN_SEGMENT_SECONDS = 0.001

LanguageStatus = Literal["matches_hint", "differs_from_hint", "not_reported"]
TimestampStatus = Literal["segments", "unavailable"]

_AUDIO_EXTENSIONS = frozenset(
    {".mp3", ".mpeg", ".wav", ".m4a", ".mp4", ".webm", ".ogg", ".flac"}
)
_CANONICAL_MEDIA: dict[str, str] = {
    ".mp3": "audio/mpeg",
    ".mpeg": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".webm": "audio/webm",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
}
_ACCEPTED_MEDIA: dict[str, frozenset[str]] = {
    ".mp3": frozenset({"audio/mpeg", "audio/mp3", "application/octet-stream"}),
    ".mpeg": frozenset({"audio/mpeg", "application/octet-stream"}),
    ".wav": frozenset(
        {"audio/wav", "audio/wave", "audio/x-wav", "application/octet-stream"}
    ),
    ".m4a": frozenset(
        {"audio/mp4", "audio/m4a", "audio/x-m4a", "application/octet-stream"}
    ),
    ".mp4": frozenset({"audio/mp4", "video/mp4", "application/octet-stream"}),
    ".webm": frozenset({"audio/webm", "video/webm", "application/octet-stream"}),
    ".ogg": frozenset({"audio/ogg", "application/ogg", "application/octet-stream"}),
    ".flac": frozenset({"audio/flac", "audio/x-flac", "application/octet-stream"}),
}
_NAME_TO_CODE: dict[str, str] = {
    "afrikaans": "af",
    "albanian": "sq",
    "amharic": "am",
    "arabic": "ar",
    "armenian": "hy",
    "assamese": "as",
    "azerbaijani": "az",
    "bashkir": "ba",
    "basque": "eu",
    "belarusian": "be",
    "bengali": "bn",
    "bosnian": "bs",
    "breton": "br",
    "bulgarian": "bg",
    "catalan": "ca",
    "chinese": "zh",
    "croatian": "hr",
    "czech": "cs",
    "danish": "da",
    "dutch": "nl",
    "english": "en",
    "estonian": "et",
    "faroese": "fo",
    "finnish": "fi",
    "francais": "fr",
    "french": "fr",
    "français": "fr",
    "galician": "gl",
    "georgian": "ka",
    "german": "de",
    "greek": "el",
    "gujarati": "gu",
    "haitian creole": "ht",
    "hausa": "ha",
    "hawaiian": "haw",
    "hebrew": "he",
    "hindi": "hi",
    "hungarian": "hu",
    "icelandic": "is",
    "indonesian": "id",
    "italian": "it",
    "japanese": "ja",
    "javanese": "jw",
    "kannada": "kn",
    "kazakh": "kk",
    "khmer": "km",
    "korean": "ko",
    "lao": "lo",
    "latin": "la",
    "latvian": "lv",
    "lingala": "ln",
    "lithuanian": "lt",
    "luxembourgish": "lb",
    "macedonian": "mk",
    "malagasy": "mg",
    "malay": "ms",
    "malayalam": "ml",
    "maltese": "mt",
    "maori": "mi",
    "marathi": "mr",
    "mongolian": "mn",
    "myanmar": "my",
    "nepali": "ne",
    "norwegian": "no",
    "nynorsk": "nn",
    "occitan": "oc",
    "pashto": "ps",
    "persian": "fa",
    "polish": "pl",
    "portuguese": "pt",
    "punjabi": "pa",
    "romanian": "ro",
    "russian": "ru",
    "sanskrit": "sa",
    "serbian": "sr",
    "shona": "sn",
    "sindhi": "sd",
    "sinhala": "si",
    "slovak": "sk",
    "slovenian": "sl",
    "somali": "so",
    "spanish": "es",
    "sundanese": "su",
    "swahili": "sw",
    "swedish": "sv",
    "tagalog": "tl",
    "tajik": "tg",
    "tamil": "ta",
    "tatar": "tt",
    "telugu": "te",
    "thai": "th",
    "tibetan": "bo",
    "turkish": "tr",
    "turkmen": "tk",
    "ukrainian": "uk",
    "urdu": "ur",
    "uzbek": "uz",
    "vietnamese": "vi",
    "welsh": "cy",
    "yiddish": "yi",
    "yoruba": "yo",
}
_ISO639_1 = re.compile(r"^[a-z]{2}$")
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class AudioPayload:
    """provider へ渡す、検証済みの音声。永続化しない。"""

    data: bytes
    filename: str
    media_type: str


@dataclass(frozen=True)
class TranscriptSegment:
    """1 断片。時刻が無ければ start / end は None のままにする。"""

    text: str
    start_seconds: float | None = None
    end_seconds: float | None = None


@dataclass(frozen=True)
class TranscriptionResult:
    """文字起こし結果。翻訳である場合は `is_translation` を立てる。"""

    text: str
    segments: tuple[TranscriptSegment, ...] | None
    detected_language: str | None = None
    is_translation: bool = False


class TranscriptionProvider(Protocol):
    """音声を原文の文字起こしにする。翻訳は返してよいが、保存側が拒否する。"""

    provider_name: str
    model: str
    transcription_version: str

    def transcribe(
        self, audio: AudioPayload, language_hint: str
    ) -> TranscriptionResult: ...


@dataclass(frozen=True)
class LanguageDecision:
    document_language: str
    status: LanguageStatus
    detected_language: str | None
    detected_code: str | None


def file_digest(data: bytes) -> str:
    """生ファイルのダイジェスト。再投入の locator に使い、ファイル自体は保存しない。"""

    return "sha256:" + hashlib.sha256(data).hexdigest()


def read_bounded(source: BinaryIO, limit: int) -> bytes:
    """上限を 1 バイト超えたところで読み止める。"""

    data = source.read(limit + 1)
    if not isinstance(data, bytes):
        raise AudioIngestionError(
            MSG_INVALID_AUDIO, code=AudioIngestErrorCode.invalid_audio
        )
    if len(data) > limit:
        raise AudioIngestionError(
            MSG_FILE_TOO_LARGE, code=AudioIngestErrorCode.file_too_large
        )
    return data


def ensure_nonempty_file(data: bytes) -> None:
    if not data:
        raise AudioIngestionError(
            MSG_EMPTY_FILE, code=AudioIngestErrorCode.invalid_audio
        )


def canonical_media_type(value: str | None) -> str | None:
    """`type/subtype` だけを残す。パラメータと大小文字は捨てる。"""

    if value is None:
        return None
    media = value.split(";", 1)[0].strip().lower()
    return media or None


def sanitize_audio_filename(filename: str | None) -> str:
    """パスを捨て、制御文字を除いた basename だけを残す。"""

    if filename is None or not filename.strip():
        raise AudioIngestionError(MSG_FILENAME, code=AudioIngestErrorCode.invalid_audio)
    basename = filename.replace("\\", "/").split("/")[-1]
    cleaned = _CONTROL_CHARS.sub("", basename).strip()
    cleaned = unicodedata.normalize("NFC", cleaned)
    if cleaned in {"", ".", ".."}:
        raise AudioIngestionError(MSG_FILENAME, code=AudioIngestErrorCode.invalid_audio)
    suffix = filename_suffix(cleaned)
    if len(cleaned) > MAX_SHORT_FIELD_CHARS:
        keep = MAX_SHORT_FIELD_CHARS - len(suffix)
        cleaned = (cleaned[:keep].rstrip() + suffix) if keep > 0 else suffix
    if not cleaned or filename_suffix(cleaned) not in _AUDIO_EXTENSIONS:
        raise AudioIngestionError(
            MSG_UNSUPPORTED_MEDIA, code=AudioIngestErrorCode.unsupported_media
        )
    return cleaned


def filename_suffix(filename: str) -> str:
    dot = filename.rfind(".")
    if dot <= 0:
        return ""
    return filename[dot:].lower()


def stored_mime_type(extension: str) -> str:
    """保存する audio MIME。宣言された Content-Type ではなく拡張子の代表値。"""

    try:
        return _CANONICAL_MEDIA[extension]
    except KeyError as exc:
        raise AudioIngestionError(
            MSG_UNSUPPORTED_MEDIA, code=AudioIngestErrorCode.unsupported_media
        ) from exc


def ensure_audio_media_type(declared: str | None, extension: str) -> None:
    """宣言された MIME が拡張子と矛盾したら拒否する。未指定は中身の判定に任せる。"""

    media = canonical_media_type(declared)
    if media is None:
        return
    allowed = _ACCEPTED_MEDIA.get(extension)
    if allowed is None or media not in allowed:
        raise AudioIngestionError(
            MSG_UNSUPPORTED_MEDIA, code=AudioIngestErrorCode.unsupported_media
        )


def measure_duration_seconds(data: bytes, extension: str) -> float | None:
    """コンテナから再生時間を読む。読めない形式は None で、時刻は作らない。"""

    if extension == ".wav":
        return _wav_duration_seconds(data)
    if extension in {".m4a", ".mp4"}:
        _require_ftyp(data)
        return _mp4_duration_seconds(data)
    if extension in {".mp3", ".mpeg"}:
        if not _has_mp3_magic(data):
            raise AudioIngestionError(
                MSG_MALFORMED_AUDIO, code=AudioIngestErrorCode.malformed_audio
            )
        return None
    if extension == ".flac":
        if not data.startswith(b"fLaC"):
            raise AudioIngestionError(
                MSG_MALFORMED_AUDIO, code=AudioIngestErrorCode.malformed_audio
            )
        return None
    if extension == ".ogg":
        if not data.startswith(b"OggS"):
            raise AudioIngestionError(
                MSG_MALFORMED_AUDIO, code=AudioIngestErrorCode.malformed_audio
            )
        return None
    if extension == ".webm":
        if not data.startswith(b"\x1a\x45\xdf\xa3"):
            raise AudioIngestionError(
                MSG_MALFORMED_AUDIO, code=AudioIngestErrorCode.malformed_audio
            )
        return None
    raise AudioIngestionError(
        MSG_UNSUPPORTED_MEDIA, code=AudioIngestErrorCode.unsupported_media
    )


def ensure_duration_allowed(duration_seconds: float | None) -> None:
    """読めた再生時間だけを上限と比較する。不明な時間はファイルサイズが上限。"""

    if duration_seconds is None:
        return
    if not math.isfinite(duration_seconds) or duration_seconds <= 0:
        raise AudioIngestionError(
            MSG_MALFORMED_AUDIO, code=AudioIngestErrorCode.malformed_audio
        )
    if duration_seconds > MAX_AUDIO_SECONDS:
        raise AudioIngestionError(
            MSG_AUDIO_TOO_LONG, code=AudioIngestErrorCode.audio_too_long
        )


def language_code(value: str) -> str:
    """`fr-FR` と `french` を、比較用の `fr` にする。"""

    token = value.strip().lower().replace("_", "-")
    if token in _NAME_TO_CODE:
        return _NAME_TO_CODE[token]
    primary = token.split("-", 1)[0]
    return _NAME_TO_CODE.get(primary, primary)


def hint_to_iso639_1(hint: str) -> str | None:
    """provider へ渡せる ISO 639-1。2 文字にならない hint は送らない。"""

    code = language_code(hint)
    if _ISO639_1.fullmatch(code):
        return code
    return None


def resolve_transcript_language(hint: str, detected: str | None) -> LanguageDecision:
    """検出言語を記録する。hint と違っても、原文の言語のままにする。"""

    cleaned_hint = hint.strip()
    if not cleaned_hint or len(cleaned_hint) > 32:
        raise AudioIngestionError(
            MSG_INVALID_AUDIO, code=AudioIngestErrorCode.invalid_audio
        )
    if detected is None or not detected.strip():
        return LanguageDecision(
            document_language=cleaned_hint,
            status="not_reported",
            detected_language=None,
            detected_code=None,
        )
    raw = detected.strip()
    code = language_code(raw)
    if not code or len(raw) > 200 or len(code) > 32:
        raise AudioIngestionError(
            MSG_INVALID_TRANSCRIPT, code=AudioIngestErrorCode.invalid_transcript
        )
    status: LanguageStatus = (
        "matches_hint" if code == language_code(cleaned_hint) else "differs_from_hint"
    )
    return LanguageDecision(
        document_language=code,
        status=status,
        detected_language=raw,
        detected_code=code,
    )


class AudioIngestionAdapter:
    """検証済みの 1 ファイルを、原文の plain text にする。"""

    source_type: SourceType = "audio_transcript"
    adapter_version = AUDIO_ADAPTER_VERSION

    def __init__(
        self,
        data: bytes,
        provider: TranscriptionProvider,
        *,
        filename: str,
        media_type: str,
        file_sha256: str,
        duration_seconds: float | None,
    ) -> None:
        self._data = data
        self._provider = provider
        self._filename = filename
        self._media_type = media_type
        self._file_sha256 = file_sha256
        self._duration_seconds = duration_seconds

    def ingest(
        self, request: SourceIngestionRequest, *, ingested_at: datetime
    ) -> SourceIngestionResult:
        if request.source_type != "audio_transcript":
            raise SourceIngestionError(
                "AudioIngestionAdapter は audio_transcript 専用",
                kind=IngestionFailureKind.validation,
            )
        if request.locator not in (None, self._file_sha256):
            raise AudioIngestionError(
                MSG_INVALID_AUDIO, code=AudioIngestErrorCode.invalid_audio
            )
        result = self._provider.transcribe(
            AudioPayload(
                data=self._data,
                filename=self._filename,
                media_type=self._media_type,
            ),
            request.language.strip(),
        )
        self._data = b""
        if result.is_translation:
            raise AudioIngestionError(
                MSG_TRANSLATED, code=AudioIngestErrorCode.translated_transcript
            )
        drafts, timestamps = _drafts_from_result(result)
        decision = resolve_transcript_language(
            request.language, result.detected_language
        )
        metadata = _metadata(
            filename=self._filename,
            media_type=self._media_type,
            file_sha256=self._file_sha256,
            duration_seconds=self._duration_seconds,
            provider=self._provider,
            ingested_at=ingested_at,
            decision=decision,
            language_hint=request.language.strip(),
            timestamps=timestamps,
            segment_count=len(drafts),
            note=request.note,
        )
        try:
            return assemble_ingestion_result(
                source_type="audio_transcript",
                title=_choose_title(request.title, self._filename),
                language=decision.document_language,
                drafts=drafts,
                adapter_version=self.adapter_version,
                ingested_at=ingested_at,
                canonical_locator=self._file_sha256,
                filename=self._filename,
                fetched_at=ingested_at,
                provider=self._provider.provider_name,
                provider_model=self._provider.model,
                mime_type=self._media_type,
                metadata=metadata,
            )
        except SourceIngestionError as exc:
            if exc.kind is IngestionFailureKind.input_too_large:
                raise AudioIngestionError(
                    MSG_TEXT_TOO_LARGE, code=AudioIngestErrorCode.text_too_large
                ) from exc
            raise


def _drafts_from_result(
    result: TranscriptionResult,
) -> tuple[tuple[SourceSegmentDraft, ...], TimestampStatus]:
    segments = result.segments
    if not segments:
        return _untimed_drafts((result.text,)), "unavailable"
    timed: list[bool] = []
    for segment in segments:
        start = segment.start_seconds
        end = segment.end_seconds
        if (start is None) != (end is None):
            raise AudioIngestionError(
                MSG_INVALID_TRANSCRIPT, code=AudioIngestErrorCode.invalid_transcript
            )
        timed.append(start is not None)
    if any(timed) and not all(timed):
        raise AudioIngestionError(
            MSG_INVALID_TRANSCRIPT, code=AudioIngestErrorCode.invalid_transcript
        )
    if not any(timed):
        return (
            _untimed_drafts(tuple(segment.text for segment in segments)),
            "unavailable",
        )
    cues: list[TimedCue] = []
    for segment in segments:
        start = segment.start_seconds
        end = segment.end_seconds
        assert start is not None and end is not None
        if (
            not math.isfinite(start)
            or not math.isfinite(end)
            or start < 0
            or end < start
        ):
            raise AudioIngestionError(
                MSG_INVALID_TRANSCRIPT, code=AudioIngestErrorCode.invalid_transcript
            )
        if end == start:
            end = start + MIN_SEGMENT_SECONDS
        cues.append(TimedCue(start_seconds=start, end_seconds=end, text=segment.text))
    try:
        built = cues_to_drafts(cues)
    except TimedTextError as exc:
        raise AudioIngestionError(
            MSG_INVALID_TRANSCRIPT, code=AudioIngestErrorCode.invalid_transcript
        ) from exc
    if not built.drafts:
        raise AudioIngestionError(
            MSG_TRANSCRIPT_EMPTY, code=AudioIngestErrorCode.transcript_empty
        )
    return built.drafts, "segments"


def _untimed_drafts(texts: Sequence[str]) -> tuple[SourceSegmentDraft, ...]:
    drafts: list[SourceSegmentDraft] = []
    for text in texts:
        if "\x00" in text:
            raise AudioIngestionError(
                MSG_INVALID_TRANSCRIPT, code=AudioIngestErrorCode.invalid_transcript
            )
        if normalize_source_text(text):
            drafts.append(SourceSegmentDraft(text=text))
    if not drafts:
        raise AudioIngestionError(
            MSG_TRANSCRIPT_EMPTY, code=AudioIngestErrorCode.transcript_empty
        )
    return tuple(drafts)


def _metadata(
    *,
    filename: str,
    media_type: str,
    file_sha256: str,
    duration_seconds: float | None,
    provider: TranscriptionProvider,
    ingested_at: datetime,
    decision: LanguageDecision,
    language_hint: str,
    timestamps: TimestampStatus,
    segment_count: int,
    note: str | None,
) -> dict[str, Any]:
    version = provider.transcription_version.strip()
    if not provider.provider_name.strip() or not provider.model.strip() or not version:
        raise AudioIngestionError(
            MSG_INVALID_TRANSCRIPT, code=AudioIngestErrorCode.invalid_transcript
        )
    metadata: dict[str, Any] = {
        "original_filename": filename,
        "audio_mime": media_type,
        "audio_sha256": file_sha256,
        "language_hint": language_hint,
        "language_status": decision.status,
        "is_translation": False,
        "timestamps": timestamps,
        "segment_count": segment_count,
        "transcription_version": version,
        "transcribed_at": ingested_at.isoformat(),
    }
    if decision.detected_language is not None:
        metadata["detected_language"] = decision.detected_language
    if decision.detected_code is not None:
        metadata["detected_language_code"] = decision.detected_code
    if duration_seconds is not None:
        metadata["duration_seconds"] = duration_seconds
    if note and note.strip():
        metadata["note"] = note.strip()
    return metadata


def _choose_title(override: str | None, filename: str) -> str:
    chosen = override.strip() if override else ""
    if not chosen:
        chosen = _stem(filename)
    collapsed = " ".join(chosen.split())
    bounded = collapsed[:MAX_SHORT_FIELD_CHARS].strip()
    return bounded or "音声"


def _stem(filename: str) -> str:
    dot = filename.rfind(".")
    if dot <= 0:
        return "" if dot == 0 else filename
    return filename[:dot]


def _wav_duration_seconds(data: bytes) -> float:
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise AudioIngestionError(
            MSG_MALFORMED_AUDIO, code=AudioIngestErrorCode.malformed_audio
        )
    offset = 12
    byte_rate: int | None = None
    data_size: int | None = None
    while offset + 8 <= len(data):
        chunk_id = data[offset : offset + 4]
        chunk_size = int.from_bytes(data[offset + 4 : offset + 8], "little")
        body_at = offset + 8
        if body_at + chunk_size > len(data):
            raise AudioIngestionError(
                MSG_MALFORMED_AUDIO, code=AudioIngestErrorCode.malformed_audio
            )
        if chunk_id == b"fmt " and chunk_size >= 16:
            byte_rate = int.from_bytes(data[body_at + 8 : body_at + 12], "little")
        elif chunk_id == b"data":
            data_size = chunk_size
            break
        offset = body_at + chunk_size + (chunk_size & 1)
    if byte_rate is None or byte_rate <= 0 or data_size is None:
        raise AudioIngestionError(
            MSG_MALFORMED_AUDIO, code=AudioIngestErrorCode.malformed_audio
        )
    return data_size / byte_rate


def _require_ftyp(data: bytes) -> None:
    if len(data) < 12 or data[4:8] != b"ftyp":
        raise AudioIngestionError(
            MSG_MALFORMED_AUDIO, code=AudioIngestErrorCode.malformed_audio
        )
    size = int.from_bytes(data[:4], "big")
    if size < 16 or size > len(data):
        raise AudioIngestionError(
            MSG_MALFORMED_AUDIO, code=AudioIngestErrorCode.malformed_audio
        )


def _mp4_duration_seconds(data: bytes) -> float | None:
    start = 0
    while True:
        pos = data.find(b"mvhd", start)
        if pos < 4:
            return None
        version = data[pos + 4] if pos + 4 < len(data) else None
        if version == 0 and pos + 24 <= len(data):
            timescale = int.from_bytes(data[pos + 16 : pos + 20], "big")
            duration = int.from_bytes(data[pos + 20 : pos + 24], "big")
            if timescale > 0:
                return duration / timescale
        elif version == 1 and pos + 36 <= len(data):
            timescale = int.from_bytes(data[pos + 24 : pos + 28], "big")
            duration = int.from_bytes(data[pos + 28 : pos + 36], "big")
            if timescale > 0:
                return duration / timescale
        start = pos + 4


def _has_mp3_magic(data: bytes) -> bool:
    if len(data) >= 10 and data.startswith(b"ID3"):
        return True
    window = data[:4096]
    return any(
        window[index] == 0xFF and window[index + 1] & 0xE0 == 0xE0
        for index in range(len(window) - 1)
    )
