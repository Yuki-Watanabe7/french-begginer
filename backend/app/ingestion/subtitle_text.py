"""SRT / VTT の検証と cue 分解（Issue #192）。

時刻の解釈と本文の決定的な切り出しだけを持つ。外部の字幕ライブラリは使わない。
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import BinaryIO, Literal

from app.domain.source_ingestion import MAX_SHORT_FIELD_CHARS
from app.ingestion.subtitle_errors import (
    MSG_EMPTY_FILE,
    MSG_FILE_TOO_LARGE,
    MSG_FILENAME,
    MSG_INVALID_SUBTITLE,
    MSG_MALFORMED_SUBTITLE,
    MSG_SUBTITLE_EMPTY,
    MSG_UNSUPPORTED_MEDIA,
    SubtitleIngestErrorCode,
    SubtitleIngestionError,
)
from app.ingestion.timed_text import TimedCue

SUBTITLE_ADAPTER_VERSION = "subtitle-v1"
MAX_SUBTITLE_BYTES = 2_000_000
SubtitleFormat = Literal["srt", "vtt"]

_SRT_MEDIA_TYPES = frozenset(
    {
        "application/x-subrip",
        "application/x-srt",
        "text/plain",
        "application/octet-stream",
    }
)
_VTT_MEDIA_TYPES = frozenset(
    {
        "text/vtt",
        "text/plain",
        "application/octet-stream",
    }
)
_VTT_METADATA = frozenset({"NOTE", "STYLE", "REGION", "WEBVTT"})
_HEADER_LINE = re.compile(r"^[A-Za-z][A-Za-z0-9-]*[:=]")
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def file_digest(data: bytes) -> str:
    """生ファイルのダイジェスト。再投入の locator に使う。"""

    return "sha256:" + hashlib.sha256(data).hexdigest()


def read_bounded(source: BinaryIO, limit: int) -> bytes:
    """上限を 1 バイト超えたところで読み止める。"""

    data = source.read(limit + 1)
    if not isinstance(data, bytes):
        raise SubtitleIngestionError(
            MSG_INVALID_SUBTITLE, code=SubtitleIngestErrorCode.invalid_subtitle
        )
    if len(data) > limit:
        raise SubtitleIngestionError(
            MSG_FILE_TOO_LARGE, code=SubtitleIngestErrorCode.file_too_large
        )
    return data


def ensure_nonempty_file(data: bytes) -> None:
    if not data:
        raise SubtitleIngestionError(
            MSG_EMPTY_FILE, code=SubtitleIngestErrorCode.invalid_subtitle
        )


def canonical_media_type(value: str | None) -> str | None:
    """`type/subtype` だけを残す。パラメータと大小文字は捨てる。"""

    if value is None:
        return None
    media = value.split(";", 1)[0].strip().lower()
    return media or None


def sanitize_subtitle_filename(filename: str | None) -> str:
    """パスを捨て、制御文字を除いた basename だけを残す。拡張子は切らない。"""

    if filename is None or not filename.strip():
        raise SubtitleIngestionError(
            MSG_FILENAME, code=SubtitleIngestErrorCode.invalid_subtitle
        )
    basename = filename.replace("\\", "/").split("/")[-1]
    cleaned = _CONTROL_CHARS.sub("", basename).strip()
    cleaned = unicodedata.normalize("NFC", cleaned)
    if cleaned in {"", ".", ".."}:
        raise SubtitleIngestionError(
            MSG_FILENAME, code=SubtitleIngestErrorCode.invalid_subtitle
        )
    suffix = filename_suffix(cleaned)
    if len(cleaned) > MAX_SHORT_FIELD_CHARS:
        keep = MAX_SHORT_FIELD_CHARS - len(suffix)
        cleaned = (cleaned[:keep].rstrip() + suffix) if keep > 0 else suffix
    if not cleaned:
        raise SubtitleIngestionError(
            MSG_FILENAME, code=SubtitleIngestErrorCode.invalid_subtitle
        )
    if filename_suffix(cleaned) not in {".srt", ".vtt"}:
        raise SubtitleIngestionError(
            MSG_UNSUPPORTED_MEDIA, code=SubtitleIngestErrorCode.unsupported_media
        )
    return cleaned


def filename_suffix(filename: str) -> str:
    dot = filename.rfind(".")
    if dot <= 0:
        return ""
    return filename[dot:].lower()


def ensure_subtitle_media_type(declared: str | None, extension: str) -> None:
    """宣言された MIME が拡張子と矛盾したら拒否する。未指定は中身の判定に任せる。"""

    media = canonical_media_type(declared)
    allowed = _VTT_MEDIA_TYPES if extension == ".vtt" else _SRT_MEDIA_TYPES
    if media is not None and media not in allowed:
        raise SubtitleIngestionError(
            MSG_UNSUPPORTED_MEDIA, code=SubtitleIngestErrorCode.unsupported_media
        )
    if media == "text/vtt" and extension != ".vtt":
        raise SubtitleIngestionError(
            MSG_UNSUPPORTED_MEDIA, code=SubtitleIngestErrorCode.unsupported_media
        )
    if media in {"application/x-subrip", "application/x-srt"} and extension != ".srt":
        raise SubtitleIngestionError(
            MSG_UNSUPPORTED_MEDIA, code=SubtitleIngestErrorCode.unsupported_media
        )


def stored_mime_type(subtitle_format: SubtitleFormat) -> str:
    if subtitle_format == "vtt":
        return "text/vtt"
    return "application/x-subrip"


def decode_subtitle(data: bytes) -> str:
    """UTF-8 として読む。BOM は除く。本文はエラーに載せない。"""

    if b"\x00" in data:
        raise SubtitleIngestionError(
            MSG_MALFORMED_SUBTITLE, code=SubtitleIngestErrorCode.malformed_subtitle
        )
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SubtitleIngestionError(
            MSG_MALFORMED_SUBTITLE, code=SubtitleIngestErrorCode.malformed_subtitle
        ) from exc


def sniff_subtitle_format(text: str) -> SubtitleFormat:
    """先頭が `WEBVTT` なら VTT、それ以外の非空テキストは SRT として検査する。"""

    stripped = text.lstrip("\ufeff \t\r\n")
    if not stripped:
        raise SubtitleIngestionError(
            MSG_SUBTITLE_EMPTY, code=SubtitleIngestErrorCode.subtitle_empty
        )
    if stripped.startswith("WEBVTT") and (
        len(stripped) == 6 or stripped[6] in " \t\r\n"
    ):
        return "vtt"
    return "srt"


def parse_subtitle_text(
    text: str, *, subtitle_format: SubtitleFormat
) -> tuple[TimedCue, ...]:
    """cue をファイル順に返す。空 cue は残し、時刻の逆転は拒否する。"""

    if "\x00" in text:
        raise SubtitleIngestionError(
            MSG_MALFORMED_SUBTITLE, code=SubtitleIngestErrorCode.malformed_subtitle
        )
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = [
        block.strip("\n")
        for block in re.split(r"\n{2,}", normalized.strip("\n"))
        if block.strip()
    ]
    if subtitle_format == "vtt":
        cues = _parse_vtt_blocks(blocks)
    else:
        cues = _parse_srt_blocks(blocks)
    if not cues:
        raise SubtitleIngestionError(
            MSG_SUBTITLE_EMPTY, code=SubtitleIngestErrorCode.subtitle_empty
        )
    return tuple(cues)


def parse_timestamp(value: str) -> float:
    """`HH:MM:SS,mmm` または `MM:SS.mmm` を秒へ換算する。"""

    if not value or any(character.isspace() for character in value):
        raise ValueError("blank timestamp")
    if value.count(",") + value.count(".") != 1:
        raise ValueError("timestamp separator")
    separator = "," if "," in value else "."
    clock, millis = value.split(separator, 1)
    if not millis.isdigit() or len(millis) != 3:
        raise ValueError("milliseconds")
    parts = clock.split(":")
    if len(parts) == 3:
        hours = _component(parts[0], digits=(1, 4), maximum=None)
        minutes = _component(parts[1], digits=(2, 2), maximum=59)
        seconds = _component(parts[2], digits=(2, 2), maximum=59)
    elif len(parts) == 2:
        hours = 0
        minutes = _component(parts[0], digits=(1, 4), maximum=None)
        seconds = _component(parts[1], digits=(2, 2), maximum=59)
    else:
        raise ValueError("timestamp parts")
    return hours * 3600 + minutes * 60 + seconds + int(millis) / 1000


def _parse_srt_blocks(blocks: list[str]) -> list[TimedCue]:
    cues: list[TimedCue] = []
    for block in blocks:
        lines = block.split("\n")
        if lines and re.fullmatch(r"\d+", lines[0].strip()):
            lines = lines[1:]
        if not lines or "-->" not in lines[0]:
            raise SubtitleIngestionError(
                MSG_MALFORMED_SUBTITLE,
                code=SubtitleIngestErrorCode.malformed_subtitle,
            )
        start, end = _parse_arrow(lines[0])
        cues.append(TimedCue(start, end, "\n".join(lines[1:])))
    return cues


def _parse_vtt_blocks(blocks: list[str]) -> list[TimedCue]:
    if not blocks or not blocks[0].lstrip().startswith("WEBVTT"):
        raise SubtitleIngestionError(
            MSG_MALFORMED_SUBTITLE, code=SubtitleIngestErrorCode.malformed_subtitle
        )
    cues: list[TimedCue] = []
    for block in blocks[1:]:
        lines = block.split("\n")
        first = lines[0].strip()
        if _is_vtt_metadata(first, block):
            continue
        arrow_at = next(
            (index for index, line in enumerate(lines) if "-->" in line),
            None,
        )
        if arrow_at is None:
            raise SubtitleIngestionError(
                MSG_MALFORMED_SUBTITLE,
                code=SubtitleIngestErrorCode.malformed_subtitle,
            )
        start, end = _parse_arrow(lines[arrow_at])
        cues.append(TimedCue(start, end, "\n".join(lines[arrow_at + 1 :])))
    return cues


def _is_vtt_metadata(first: str, block: str) -> bool:
    token = first.split(" ", 1)[0].rstrip(":").upper()
    if token in _VTT_METADATA:
        return True
    if "-->" in block:
        return False
    return _HEADER_LINE.match(first) is not None


def _parse_arrow(line: str) -> tuple[float, float]:
    if "-->" not in line:
        raise SubtitleIngestionError(
            MSG_MALFORMED_SUBTITLE, code=SubtitleIngestErrorCode.malformed_subtitle
        )
    left, right = line.split("-->", 1)
    end_token = right.strip().split(" ", 1)[0] if right.strip() else ""
    try:
        start = parse_timestamp(left.strip())
        end = parse_timestamp(end_token)
    except ValueError as exc:
        raise SubtitleIngestionError(
            MSG_MALFORMED_SUBTITLE, code=SubtitleIngestErrorCode.malformed_subtitle
        ) from exc
    if end <= start:
        raise SubtitleIngestionError(
            MSG_MALFORMED_SUBTITLE, code=SubtitleIngestErrorCode.malformed_subtitle
        )
    return start, end


def _component(value: str, *, digits: tuple[int, int], maximum: int | None) -> int:
    if not value.isdigit() or not digits[0] <= len(value) <= digits[1]:
        raise ValueError("timestamp component")
    number = int(value)
    if maximum is not None and number > maximum:
        raise ValueError("timestamp range")
    return number
