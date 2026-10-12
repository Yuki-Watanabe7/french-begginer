"""structured conversation JSON を SourceIngestionResult にする（Issue #194）。

受け付ける形は `title` と `messages[].speaker/text/timestamp` だけである。
未知のキーは保存せず、別サービスの export として解釈しない。話者名は本文に
足さず `SourceSegment.speaker` に置く。発話時刻は `timestamp` に置く。
添付や URL は取得しない。
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import UTC, datetime
from typing import Any, BinaryIO

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

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
from app.ingestion.conversation_errors import (
    MSG_CONVERSATION_EMPTY,
    MSG_EMPTY_FILE,
    MSG_FILE_TOO_LARGE,
    MSG_FILENAME,
    MSG_INVALID_CONVERSATION,
    MSG_MALFORMED_CONVERSATION,
    MSG_TEXT_TOO_LARGE,
    MSG_UNSUPPORTED_MEDIA,
    ConversationIngestErrorCode,
    ConversationIngestionError,
)

CONVERSATION_ADAPTER_VERSION = "conversation-log-v1"
MAX_CONVERSATION_BYTES = 2_000_000
STORED_CONVERSATION_MIME = "application/json"

_JSON_EXTENSION = ".json"
_JSON_MEDIA_TYPES = frozenset(
    {"application/json", "text/plain", "application/octet-stream"}
)
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$"
)


class ConversationMessage(BaseModel):
    """1 発話。未知キーは拒否する。"""

    model_config = ConfigDict(extra="forbid")

    speaker: str | None = Field(default=None, max_length=200)
    text: str
    timestamp: str | None = None

    @field_validator("speaker")
    @classmethod
    def _clean_speaker(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        if _CONTROL_CHARS.search(cleaned) or len(cleaned) > 200:
            raise ValueError("speaker")
        return cleaned

    @field_validator("timestamp")
    @classmethod
    def _clean_timestamp(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        return _canonicalize_timestamp(cleaned)


class ConversationDocument(BaseModel):
    """会話ログの唯一の schema。この形以外は推測しない。"""

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    messages: list[ConversationMessage]


def file_digest(data: bytes) -> str:
    """生ファイルのダイジェスト。再投入の locator に使う。"""

    return "sha256:" + hashlib.sha256(data).hexdigest()


def read_bounded(source: BinaryIO, limit: int) -> bytes:
    """上限を 1 バイト超えたところで読み止める。"""

    data = source.read(limit + 1)
    if not isinstance(data, bytes):
        raise ConversationIngestionError(
            MSG_INVALID_CONVERSATION,
            code=ConversationIngestErrorCode.invalid_conversation,
        )
    if len(data) > limit:
        raise ConversationIngestionError(
            MSG_FILE_TOO_LARGE, code=ConversationIngestErrorCode.file_too_large
        )
    return data


def ensure_nonempty_file(data: bytes) -> None:
    if not data:
        raise ConversationIngestionError(
            MSG_EMPTY_FILE, code=ConversationIngestErrorCode.invalid_conversation
        )


def canonical_media_type(value: str | None) -> str | None:
    """`type/subtype` だけを残す。パラメータと大小文字は捨てる。"""

    if value is None:
        return None
    media = value.split(";", 1)[0].strip().lower()
    return media or None


def sanitize_conversation_filename(filename: str | None) -> str | None:
    """ファイル名は任意。あるときは basename の `.json` だけを受ける。"""

    if filename is None or not filename.strip():
        return None
    basename = filename.replace("\\", "/").split("/")[-1]
    cleaned = _CONTROL_CHARS.sub("", basename).strip()
    cleaned = unicodedata.normalize("NFC", cleaned)
    if cleaned in {"", ".", ".."}:
        raise ConversationIngestionError(
            MSG_FILENAME, code=ConversationIngestErrorCode.invalid_conversation
        )
    suffix = _suffix(cleaned)
    if len(cleaned) > MAX_SHORT_FIELD_CHARS:
        keep = MAX_SHORT_FIELD_CHARS - len(suffix)
        cleaned = (cleaned[:keep].rstrip() + suffix) if keep > 0 else suffix
    if not cleaned or _suffix(cleaned) != _JSON_EXTENSION:
        raise ConversationIngestionError(
            MSG_UNSUPPORTED_MEDIA, code=ConversationIngestErrorCode.unsupported_media
        )
    return cleaned


def ensure_conversation_media_type(
    declared: str | None, *, filename: str | None
) -> None:
    media = canonical_media_type(declared)
    if filename is None and media != "application/json":
        raise ConversationIngestionError(
            MSG_INVALID_CONVERSATION,
            code=ConversationIngestErrorCode.invalid_conversation,
        )
    if media is not None and media not in _JSON_MEDIA_TYPES:
        raise ConversationIngestionError(
            MSG_UNSUPPORTED_MEDIA, code=ConversationIngestErrorCode.unsupported_media
        )


def parse_conversation(data: bytes) -> tuple[ConversationDocument, int]:
    """schema に合う JSON と、空発話の件数を返す。未知の形は拒否する。"""

    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ConversationIngestionError(
            MSG_MALFORMED_CONVERSATION,
            code=ConversationIngestErrorCode.malformed_conversation,
        ) from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConversationIngestionError(
            MSG_MALFORMED_CONVERSATION,
            code=ConversationIngestErrorCode.malformed_conversation,
        ) from exc
    if not isinstance(payload, dict):
        raise ConversationIngestionError(
            MSG_MALFORMED_CONVERSATION,
            code=ConversationIngestErrorCode.malformed_conversation,
        )
    try:
        document = ConversationDocument.model_validate(payload)
    except ValidationError as exc:
        raise ConversationIngestionError(
            MSG_MALFORMED_CONVERSATION,
            code=ConversationIngestErrorCode.malformed_conversation,
        ) from exc
    _reject_oversized_title(document.title)
    return document, _empty_message_count(document)


class ConversationIngestionAdapter:
    """1 件の会話 JSON を、話者と発話時刻付きの plain text にする。"""

    source_type: SourceType = "conversation_log"
    adapter_version = CONVERSATION_ADAPTER_VERSION

    def __init__(
        self,
        data: bytes,
        *,
        filename: str | None,
        file_sha256: str,
    ) -> None:
        self._data = data
        self._filename = filename
        self._file_sha256 = file_sha256

    def ingest(
        self, request: SourceIngestionRequest, *, ingested_at: datetime
    ) -> SourceIngestionResult:
        if request.source_type != "conversation_log":
            raise SourceIngestionError(
                "ConversationIngestionAdapter は conversation_log 専用",
                kind=IngestionFailureKind.validation,
            )
        if request.locator not in (None, self._file_sha256):
            raise ConversationIngestionError(
                MSG_INVALID_CONVERSATION,
                code=ConversationIngestErrorCode.invalid_conversation,
            )
        document, empty_count = parse_conversation(self._data)
        drafts = _message_drafts(document)
        if not drafts:
            raise ConversationIngestionError(
                MSG_CONVERSATION_EMPTY,
                code=ConversationIngestErrorCode.conversation_empty,
            )
        metadata: dict[str, Any] = {
            "source_format": "conversation_json",
            "file_sha256": self._file_sha256,
            "message_count": len(drafts),
            "empty_message_count": empty_count,
        }
        if request.note and request.note.strip():
            metadata["note"] = request.note.strip()
        try:
            return assemble_ingestion_result(
                source_type="conversation_log",
                title=_choose_title(request.title, document.title, self._filename),
                language=request.language,
                drafts=drafts,
                adapter_version=self.adapter_version,
                ingested_at=ingested_at,
                canonical_locator=self._file_sha256,
                filename=self._filename,
                mime_type=STORED_CONVERSATION_MIME,
                metadata=metadata,
            )
        except SourceIngestionError as exc:
            if exc.kind is IngestionFailureKind.input_too_large:
                raise ConversationIngestionError(
                    MSG_TEXT_TOO_LARGE,
                    code=ConversationIngestErrorCode.text_too_large,
                ) from exc
            raise ConversationIngestionError(
                MSG_MALFORMED_CONVERSATION,
                code=ConversationIngestErrorCode.malformed_conversation,
            ) from exc


def _message_drafts(document: ConversationDocument) -> list[SourceSegmentDraft]:
    drafts: list[SourceSegmentDraft] = []
    for message in document.messages:
        if not normalize_source_text(message.text):
            continue
        drafts.append(
            SourceSegmentDraft(
                text=message.text,
                speaker=message.speaker,
                timestamp=message.timestamp,
            )
        )
    return drafts


def _empty_message_count(document: ConversationDocument) -> int:
    return sum(
        1 for message in document.messages if not normalize_source_text(message.text)
    )


def _reject_oversized_title(title: str | None) -> None:
    if title is None:
        return
    if len(title.strip()) > MAX_SHORT_FIELD_CHARS:
        raise ConversationIngestionError(
            MSG_MALFORMED_CONVERSATION,
            code=ConversationIngestErrorCode.malformed_conversation,
        )


def _canonicalize_timestamp(value: str) -> str:
    if _TIMESTAMP_RE.fullmatch(value) is None:
        raise ValueError("timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("timestamp")
    utc = parsed.astimezone(UTC)
    timespec = "microseconds" if utc.microsecond else "seconds"
    return utc.isoformat(timespec=timespec).replace("+00:00", "Z")


def _choose_title(
    override: str | None, document_title: str | None, filename: str | None
) -> str:
    for candidate in (override, document_title, _stem(filename) if filename else None):
        if candidate and candidate.strip():
            collapsed = " ".join(candidate.split())
            bounded = collapsed[:MAX_SHORT_FIELD_CHARS].strip()
            if bounded:
                return bounded
    return "会話"


def _stem(filename: str) -> str:
    dot = filename.rfind(".")
    if dot <= 0:
        return "" if dot == 0 else filename
    return filename[:dot]


def _suffix(filename: str) -> str:
    dot = filename.rfind(".")
    if dot <= 0:
        return ""
    return filename[dot:].lower()
