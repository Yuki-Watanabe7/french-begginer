"""UTF-8 テキストと Markdown を SourceIngestionResult にする（Issue #194）。

Markdown は学習本文に必要な最小限だけを plain text にする。リンク先は残さず、
取得もしない。話者ラベルは付けない。正規化の本体は共有の
`assemble_ingestion_result` を一度だけ通す。
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime
from typing import Any, BinaryIO, Literal

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
from app.ingestion.text_file_errors import (
    MSG_EMPTY_FILE,
    MSG_FILE_TOO_LARGE,
    MSG_FILENAME,
    MSG_INVALID_TEXT_FILE,
    MSG_MALFORMED_TEXT,
    MSG_TEXT_EMPTY,
    MSG_TEXT_TOO_LARGE,
    MSG_UNSUPPORTED_MEDIA,
    TextFileIngestErrorCode,
    TextFileIngestionError,
)

TEXT_FILE_ADAPTER_VERSION = "text-file-v1"
MAX_TEXT_FILE_BYTES = 2_000_000
TextFileFormat = Literal["plain_text", "markdown"]

_PLAIN_EXTENSIONS = frozenset({".txt", ".log"})
_MARKDOWN_EXTENSIONS = frozenset({".md", ".markdown"})
_TEXT_EXTENSIONS = _PLAIN_EXTENSIONS | _MARKDOWN_EXTENSIONS
_PLAIN_MEDIA_TYPES = frozenset({"text/plain", "application/octet-stream"})
_MARKDOWN_MEDIA_TYPES = _PLAIN_MEDIA_TYPES | frozenset(
    {"text/markdown", "text/x-markdown"}
)
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_FENCE_RE = re.compile(r"^(?P<mark>`{3,}|~{3,})(?P<info>.*)$")
_HR_RE = re.compile(r"^(?:(?:\*\s*){3,}|(?:-\s*){3,}|(?:_\s*){3,})$")
_HEADING_RE = re.compile(r"^#{1,6}\s+")
_UL_RE = re.compile(r"^[-*+]\s+")
_OL_RE = re.compile(r"^\d{1,9}[.)]\s+")
_REF_DEF_RE = re.compile(r"^\[[^\]\n]+\]:\s+\S+")
_IMAGE_RE = re.compile(r"!\[([^\]\n]*)\]\([^)\n]*\)")
_LINK_RE = re.compile(r"\[([^\]\n]*)\]\([^)\n]*\)")
_REF_LINK_RE = re.compile(r"\[([^\]\n]+)\]\[[^\]\n]*\]")
_AUTOLINK_RE = re.compile(r"<https?://[^>\s]+>", re.IGNORECASE)
_CODE_RE = re.compile(r"`([^`\n]*)`")
_BOLD_RE = re.compile(r"\*\*([^*\n]+)\*\*|__([^_\n]+)__")
_ITALIC_STAR_RE = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
_ITALIC_UNDER_RE = re.compile(r"(?<![\w_])_([^_\n]+)_(?![\w_])")
_STRIKE_RE = re.compile(r"~~([^~\n]+)~~")


def file_digest(data: bytes) -> str:
    """生ファイルのダイジェスト。再投入の locator に使う。"""

    return "sha256:" + hashlib.sha256(data).hexdigest()


def read_bounded(source: BinaryIO, limit: int) -> bytes:
    """上限を 1 バイト超えたところで読み止める。"""

    data = source.read(limit + 1)
    if not isinstance(data, bytes):
        raise TextFileIngestionError(
            MSG_INVALID_TEXT_FILE, code=TextFileIngestErrorCode.invalid_text_file
        )
    if len(data) > limit:
        raise TextFileIngestionError(
            MSG_FILE_TOO_LARGE, code=TextFileIngestErrorCode.file_too_large
        )
    return data


def ensure_nonempty_file(data: bytes) -> None:
    if not data:
        raise TextFileIngestionError(
            MSG_EMPTY_FILE, code=TextFileIngestErrorCode.invalid_text_file
        )


def canonical_media_type(value: str | None) -> str | None:
    """`type/subtype` だけを残す。パラメータと大小文字は捨てる。"""

    if value is None:
        return None
    media = value.split(";", 1)[0].strip().lower()
    return media or None


def sanitize_text_filename(filename: str | None) -> str:
    """パスを捨て、制御文字を除いた basename だけを残す。"""

    if filename is None or not filename.strip():
        raise TextFileIngestionError(
            MSG_FILENAME, code=TextFileIngestErrorCode.invalid_text_file
        )
    basename = filename.replace("\\", "/").split("/")[-1]
    cleaned = _CONTROL_CHARS.sub("", basename).strip()
    cleaned = unicodedata.normalize("NFC", cleaned)
    if cleaned in {"", ".", ".."}:
        raise TextFileIngestionError(
            MSG_FILENAME, code=TextFileIngestErrorCode.invalid_text_file
        )
    suffix = filename_suffix(cleaned)
    if len(cleaned) > MAX_SHORT_FIELD_CHARS:
        keep = MAX_SHORT_FIELD_CHARS - len(suffix)
        cleaned = (cleaned[:keep].rstrip() + suffix) if keep > 0 else suffix
    if not cleaned or filename_suffix(cleaned) not in _TEXT_EXTENSIONS:
        raise TextFileIngestionError(
            MSG_UNSUPPORTED_MEDIA, code=TextFileIngestErrorCode.unsupported_media
        )
    return cleaned


def filename_suffix(filename: str) -> str:
    dot = filename.rfind(".")
    if dot <= 0:
        return ""
    return filename[dot:].lower()


def text_file_format(filename: str) -> TextFileFormat:
    suffix = filename_suffix(filename)
    if suffix in _MARKDOWN_EXTENSIONS:
        return "markdown"
    if suffix in _PLAIN_EXTENSIONS:
        return "plain_text"
    raise TextFileIngestionError(
        MSG_UNSUPPORTED_MEDIA, code=TextFileIngestErrorCode.unsupported_media
    )


def ensure_text_media_type(declared: str | None, text_format: TextFileFormat) -> None:
    media = canonical_media_type(declared)
    if media is None:
        return
    allowed = _MARKDOWN_MEDIA_TYPES if text_format == "markdown" else _PLAIN_MEDIA_TYPES
    if media not in allowed:
        raise TextFileIngestionError(
            MSG_UNSUPPORTED_MEDIA, code=TextFileIngestErrorCode.unsupported_media
        )


def stored_mime_type(text_format: TextFileFormat) -> str:
    if text_format == "markdown":
        return "text/markdown"
    return "text/plain"


def decode_text_file(data: bytes) -> str:
    """UTF-8（BOM 可）だけを受ける。別の文字コードへは推測しない。"""

    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise TextFileIngestionError(
            MSG_MALFORMED_TEXT, code=TextFileIngestErrorCode.malformed_text
        ) from exc


def markdown_to_plain(text: str) -> str:
    """見出し・強調・リスト・リンク記法を外し、リンク先 URL は捨てる。

    コードフェンスの中は記法として解釈しない。参照定義の URL 行は残さない。
    取得はしない。共通の `normalize_source_text` はここでは掛けない。
    """

    normalized_newlines = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized_newlines.split("\n")
    output: list[str] = []
    fence_mark = ""
    fence_length = 0
    index = 0
    while index < len(lines):
        line = lines[index]
        if fence_mark:
            if _closes_fence(line, fence_mark, fence_length):
                fence_mark = ""
                fence_length = 0
            else:
                output.append(line)
            index += 1
            continue
        opened = _opens_fence(line)
        if opened is not None:
            fence_mark, fence_length = opened
            index += 1
            continue
        if not line.strip():
            output.append("")
            index += 1
            continue
        stripped = _strip_indent(line)
        if _REF_DEF_RE.match(stripped):
            index += 1
            continue
        body = _strip_block_markers(stripped)
        if _HR_RE.match(body.strip()):
            index += 1
            continue
        output.append(_inline(body))
        index += 1
    return "\n".join(output)


class TextFileIngestionAdapter:
    """1 件のテキスト / Markdown を、provenance 付きの plain text にする。"""

    source_type: SourceType = "conversation_log"
    adapter_version = TEXT_FILE_ADAPTER_VERSION

    def __init__(
        self,
        data: bytes,
        *,
        filename: str,
        text_format: TextFileFormat,
        file_sha256: str,
    ) -> None:
        self._data = data
        self._filename = filename
        self._format: TextFileFormat = text_format
        self._file_sha256 = file_sha256

    def ingest(
        self, request: SourceIngestionRequest, *, ingested_at: datetime
    ) -> SourceIngestionResult:
        if request.source_type != "conversation_log":
            raise SourceIngestionError(
                "TextFileIngestionAdapter は conversation_log 専用",
                kind=IngestionFailureKind.validation,
            )
        if request.locator not in (None, self._file_sha256):
            raise TextFileIngestionError(
                MSG_INVALID_TEXT_FILE, code=TextFileIngestErrorCode.invalid_text_file
            )
        if text_file_format(self._filename) != self._format:
            raise TextFileIngestionError(
                MSG_MALFORMED_TEXT, code=TextFileIngestErrorCode.malformed_text
            )
        decoded = decode_text_file(self._data)
        plain = markdown_to_plain(decoded) if self._format == "markdown" else decoded
        if not normalize_source_text(plain):
            raise TextFileIngestionError(
                MSG_TEXT_EMPTY, code=TextFileIngestErrorCode.text_empty
            )
        metadata: dict[str, Any] = {
            "source_format": self._format,
            "file_sha256": self._file_sha256,
        }
        if request.note and request.note.strip():
            metadata["note"] = request.note.strip()
        try:
            return assemble_ingestion_result(
                source_type="conversation_log",
                title=_choose_title(request.title, self._filename, fallback="テキスト"),
                language=request.language,
                drafts=[SourceSegmentDraft(text=plain)],
                adapter_version=self.adapter_version,
                ingested_at=ingested_at,
                canonical_locator=self._file_sha256,
                filename=self._filename,
                mime_type=stored_mime_type(self._format),
                metadata=metadata,
            )
        except SourceIngestionError as exc:
            if exc.kind is IngestionFailureKind.input_too_large:
                raise TextFileIngestionError(
                    MSG_TEXT_TOO_LARGE, code=TextFileIngestErrorCode.text_too_large
                ) from exc
            raise TextFileIngestionError(
                MSG_MALFORMED_TEXT, code=TextFileIngestErrorCode.malformed_text
            ) from exc


def _choose_title(override: str | None, filename: str, *, fallback: str) -> str:
    chosen = override.strip() if override else ""
    if not chosen:
        chosen = _stem(filename)
    collapsed = " ".join(chosen.split())
    bounded = collapsed[:MAX_SHORT_FIELD_CHARS].strip()
    return bounded or fallback


def _stem(filename: str) -> str:
    dot = filename.rfind(".")
    if dot <= 0:
        return "" if dot == 0 else filename
    return filename[:dot]


def _strip_indent(line: str) -> str:
    stripped = line.lstrip(" ")
    if len(line) - len(stripped) > 3:
        return line
    return stripped


def _opens_fence(line: str) -> tuple[str, int] | None:
    match = _FENCE_RE.match(_strip_indent(line))
    if match is None:
        return None
    mark = match.group("mark")
    info = match.group("info")
    if mark.startswith("`") and "`" in info:
        return None
    return mark[0], len(mark)


def _closes_fence(line: str, mark: str, length: int) -> bool:
    stripped = _strip_indent(line)
    if not stripped.startswith(mark * 3):
        return False
    count = 0
    for char in stripped:
        if char != mark:
            break
        count += 1
    return count >= length and stripped[count:].strip() == ""


def _strip_block_markers(line: str) -> str:
    rest = line
    while True:
        if rest.startswith(">"):
            rest = rest[1:]
            if rest.startswith(" "):
                rest = rest[1:]
            rest = _strip_indent(rest)
            continue
        marker = _UL_RE.match(rest) or _OL_RE.match(rest)
        if marker is not None:
            rest = rest[marker.end() :]
            continue
        heading = _HEADING_RE.match(rest)
        if heading is not None:
            rest = rest[heading.end() :]
            continue
        return rest


def _inline(line: str) -> str:
    current = line
    for _ in range(8):
        updated = _IMAGE_RE.sub(r"\1", current)
        updated = _LINK_RE.sub(r"\1", updated)
        updated = _REF_LINK_RE.sub(r"\1", updated)
        updated = _AUTOLINK_RE.sub("", updated)
        updated = _CODE_RE.sub(r"\1", updated)
        updated = _BOLD_RE.sub(lambda match: match.group(1) or match.group(2), updated)
        updated = _ITALIC_STAR_RE.sub(r"\1", updated)
        updated = _ITALIC_UNDER_RE.sub(r"\1", updated)
        updated = _STRIKE_RE.sub(r"\1", updated)
        if updated == current:
            return current
        current = updated
    return current
