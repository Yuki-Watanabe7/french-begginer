"""Source ingestion の共通契約（Issue #189）。

外部入力を、下流の Candidate 抽出が既に理解している `SourceDocument` へ
渡す前に、plain text と provenance へ正規化する境界。

```text
external input
  -> SourceIngestionRequest
  -> SourceIngestionAdapter（形式ごとの実装は後続）
  -> normalize_source_text / SourceSegment
  -> SourceIngestionResult
  -> SourceDocument.content（plain text が source of truth）
```

このモジュールが依存してよいのは Python 標準ライブラリと Pydantic のみ。
HTTP client / PDF parser / OpenAI SDK には依存しない。個別の URL / PDF /
transcript adapter はここには置かない。

## 正規化（`source-ingest-v1`）

`normalize_source_text` は adapter 横断で一度だけ適用する。

- Unicode NFC
- BOM を除去
- CRLF / CR / U+2028 / U+2029 / U+0085 を LF にする
- 各行末の空白とタブを除去
- 3 連続以上の改行は段落区切り 1 つ（LF 2 つ）に畳む
- 全文の前後空白を除去

結果は不動点である。同じ入力と同じ `INGESTION_VERSION` から
`normalized_content` と `content_hash` は deterministic に決まる。

EvidenceSpan の座標は、正規化後に保存された `SourceDocument.content` の
Unicode コードポイント（`len` / スライス）である。検証の前後で本文を
再正規化しない。手入力 API は従来どおり、投稿された `content` を
そのまま保存する（この正規化を通さない）。

## 再投入

canonical locator がない入力（典型は手貼り付け）は毎回新しい Source になる。
locator があるとき:

- 同じ source_type / locator / content_hash / ingestion_version なら既存を再利用
- 本文または ingestion_version が変わったら新しい Source を追加する
- 既存行の content は更新しない

web_url のホスト正規化と SSRF 対策は `app.ingestion`（Issue #190）。
このモジュールの locator 比較は、前後空白を除いた文字列の一致である。
URL を同一視する正規化は、web adapter が `canonical_locator` に書く前に行う。
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Protocol

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

UtcDatetime = Annotated[AwareDatetime, AfterValidator(lambda dt: dt.astimezone(UTC))]

INGESTION_VERSION = "source-ingest-v1"
"""共有正規化規則の版。規則を変えるときは bump し、保存済み content は書き換えない。"""

MANUAL_TEXT_ADAPTER_VERSION = "manual-text-v1"

MAX_SOURCE_TEXT_CHARS = 200_000
"""正規化前・正規化後の本文上限（Unicode コードポイント）。"""

MAX_LOCATOR_CHARS = 2_000
MAX_SHORT_FIELD_CHARS = 500

SourceType = Literal[
    "manual_text",
    "web_url",
    "pdf",
    "youtube_transcript",
    "subtitle",
    "audio_transcript",
    "conversation_log",
]

SOURCE_TYPES: tuple[SourceType, ...] = (
    "manual_text",
    "web_url",
    "pdf",
    "youtube_transcript",
    "subtitle",
    "audio_transcript",
    "conversation_log",
)

WEB_URL_MEDIA_TYPES = frozenset({"text/html", "application/xhtml+xml", "text/plain"})
"""web_url が保存してよい応答の media type。charset パラメータは含めない。"""

_ALLOWED_MIME_TYPES: dict[SourceType, frozenset[str]] = {
    "manual_text": frozenset({"text/plain"}),
    "web_url": WEB_URL_MEDIA_TYPES,
    "pdf": frozenset({"application/pdf"}),
    "youtube_transcript": frozenset({"text/plain", "application/json"}),
    "subtitle": frozenset({"text/vtt", "application/x-subrip", "text/plain"}),
    "audio_transcript": frozenset({"text/plain", "application/json"}),
    "conversation_log": frozenset({"text/plain", "application/json"}),
}

_ALLOWED_EXTENSIONS: dict[SourceType, frozenset[str]] = {
    "pdf": frozenset({".pdf"}),
    "subtitle": frozenset({".vtt", ".srt"}),
    "audio_transcript": frozenset({".txt", ".json"}),
    "conversation_log": frozenset({".txt", ".json", ".log"}),
}

_SECRET_KEY_RE = re.compile(
    r"(^|[^a-z0-9])("
    r"api[_-]?key|secret|password|passwd|token|authorization|credential|cookie"
    r")([^a-z0-9]|$)",
    re.IGNORECASE,
)
_BLANK_LINE_RE = re.compile(r"\n{3,}")
_RAW_PAYLOAD_KEYS = frozenset(
    {
        "raw_html",
        "raw_pdf",
        "pdf_bytes",
        "file_bytes",
        "binary",
        "html_body",
    }
)


class IngestionFailureKind(StrEnum):
    """adapter 共通の失敗分類。timeout / provider だけ再試行できる。"""

    validation = "validation"
    unsupported_media = "unsupported_media"
    input_too_large = "input_too_large"
    timeout = "timeout"
    provider = "provider"
    not_implemented = "not_implemented"


_RETRYABLE_KINDS = frozenset(
    {IngestionFailureKind.timeout, IngestionFailureKind.provider}
)


class SourceIngestionError(Exception):
    """ingestion 境界で拒否した入力、または外部 provider の失敗。"""

    def __init__(self, message: str, *, kind: IngestionFailureKind) -> None:
        super().__init__(message)
        self.kind = kind

    @property
    def retryable(self) -> bool:
        return self.kind in _RETRYABLE_KINDS


class IngestAction(StrEnum):
    """再投入時の扱い。既存 Source の content を上書きする action は無い。"""

    create = "create"
    reuse = "reuse"
    append_version = "append_version"


def content_digest(text: str) -> str:
    """正規化後（または正規化前）本文の安定なダイジェスト。

    アルゴリズムは prefix `sha256:` に固定する。将来アルゴリズムを増やす場合も
    この prefix の検証は残し、保存済み行を開けなくしない。
    """

    encoded = text.encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def normalize_source_text(text: str) -> str:
    """adapter 横断の plain text 正規化。同じ入力なら常に同じ文字列を返す。"""

    if text.startswith("\ufeff"):
        text = text[1:]
    text = unicodedata.normalize("NFC", text)
    text = (
        text.replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\u2028", "\n")
        .replace("\u2029", "\n")
        .replace("\u0085", "\n")
    )
    text = "\n".join(line.rstrip(" \t") for line in text.split("\n"))
    text = _BLANK_LINE_RE.sub("\n\n", text)
    return text.strip()


def provider_timeout(message: str) -> SourceIngestionError:
    """外部取得が時間内に終わらなかったとき。再試行してよい。"""

    return SourceIngestionError(message, kind=IngestionFailureKind.timeout)


def provider_failure(message: str) -> SourceIngestionError:
    """外部 provider の一時的な失敗。再試行してよい。"""

    return SourceIngestionError(message, kind=IngestionFailureKind.provider)


class SourceSegment(BaseModel):
    """正規化後 content 上の区間と、元 Source の位置。

    `normalized_start` / `normalized_end` は `SourceDocument.content` および
    EvidenceSpan と同じ半開区間（コードポイント）である。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    normalized_start: int = Field(ge=0)
    normalized_end: int = Field(ge=0)
    page_number: int | None = Field(default=None, ge=1)
    start_seconds: float | None = Field(default=None, ge=0)
    end_seconds: float | None = Field(default=None, ge=0)
    speaker: str | None = Field(default=None, max_length=200)
    external_locator: str | None = Field(default=None, max_length=MAX_LOCATOR_CHARS)

    @field_validator("speaker", "external_locator", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @model_validator(mode="after")
    def _check_range(self) -> SourceSegment:
        if self.normalized_end <= self.normalized_start:
            raise ValueError(
                "SourceSegment の normalized_end は start より大きい必要がある: "
                f"start={self.normalized_start}, end={self.normalized_end}"
            )
        _require_timecode_pair(self.start_seconds, self.end_seconds)
        return self


class SourceSegmentDraft(BaseModel):
    """adapter が切り出した、正規化前の plain text 断片。"""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    page_number: int | None = Field(default=None, ge=1)
    start_seconds: float | None = Field(default=None, ge=0)
    end_seconds: float | None = Field(default=None, ge=0)
    speaker: str | None = Field(default=None, max_length=200)
    external_locator: str | None = Field(default=None, max_length=MAX_LOCATOR_CHARS)

    @field_validator("speaker", "external_locator", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @model_validator(mode="after")
    def _check_timecode(self) -> SourceSegmentDraft:
        _require_timecode_pair(self.start_seconds, self.end_seconds)
        return self


class SourceProvenance(BaseModel):
    """正規化後本文を、元の URL / ファイル / 発話位置へ戻すための記録。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    canonical_locator: str | None = None
    filename: str | None = None
    external_id: str | None = None
    fetched_at: UtcDatetime | None = None
    ingested_at: UtcDatetime
    adapter_version: str = Field(min_length=1, max_length=MAX_SHORT_FIELD_CHARS)
    provider: str | None = Field(default=None, max_length=MAX_SHORT_FIELD_CHARS)
    provider_model: str | None = Field(default=None, max_length=MAX_SHORT_FIELD_CHARS)
    original_content_hash: str = Field(min_length=1)
    mime_type: str | None = None
    ingestion_version: str = Field(min_length=1)


class SourceIngestionRequest(BaseModel):
    """adapter に渡す入力。ファイルバイトや HTML そのものは持たない。"""

    model_config = ConfigDict(extra="forbid")

    source_type: SourceType
    locator: str | None = Field(default=None, max_length=MAX_LOCATOR_CHARS)
    filename: str | None = Field(default=None, max_length=MAX_SHORT_FIELD_CHARS)
    mime_type: str | None = Field(default=None, max_length=200)
    external_id: str | None = Field(default=None, max_length=MAX_SHORT_FIELD_CHARS)
    title: str | None = Field(default=None, max_length=MAX_SHORT_FIELD_CHARS)
    note: str | None = Field(default=None, max_length=2_000)
    language: str = Field(default="fr", min_length=1, max_length=32)
    text: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceIngestionResult(BaseModel):
    """正規化済み plain text と、それを再現するための provenance。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str = Field(min_length=1, max_length=MAX_SHORT_FIELD_CHARS)
    normalized_content: str = Field(min_length=1)
    language: str = Field(min_length=1, max_length=32)
    source_type: SourceType
    provenance: SourceProvenance
    segments: list[SourceSegment] = Field(min_length=1)
    content_hash: str = Field(min_length=1)
    ingestion_version: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_contract(self) -> SourceIngestionResult:
        if self.ingestion_version != INGESTION_VERSION:
            raise ValueError(
                f"ingestion_version は {INGESTION_VERSION} である必要がある"
            )
        if self.provenance.ingestion_version != self.ingestion_version:
            raise ValueError("provenance.ingestion_version が一致しない")
        if normalize_source_text(self.normalized_content) != self.normalized_content:
            raise ValueError("normalized_content は共有正規化の不動点である必要がある")
        if self.content_hash != content_digest(self.normalized_content):
            raise ValueError("content_hash が normalized_content と一致しない")
        ensure_segment_layout(self.normalized_content, self.segments)
        try:
            _reject_secret_mapping(self.metadata)
        except SourceIngestionError as exc:
            raise ValueError(str(exc)) from exc
        return self


@dataclass(frozen=True)
class StoredSourceIdentity:
    """再投入の判定に使う、保存済み Source の同一性。"""

    id: str
    source_type: str
    canonical_locator: str | None
    content_hash: str | None
    ingestion_version: str | None
    created_at: datetime


@dataclass(frozen=True)
class IngestPlan:
    action: IngestAction
    existing_id: str | None = None
    prior_source_id: str | None = None


class SourceIngestionAdapter(Protocol):
    """形式ごとの変換。HTTP / PDF / SDK への依存はこの実装側に閉じ込める。"""

    source_type: SourceType
    adapter_version: str

    def ingest(
        self, request: SourceIngestionRequest, *, ingested_at: datetime
    ) -> SourceIngestionResult: ...


def ensure_segment_layout(content: str, segments: Sequence[SourceSegment]) -> None:
    """segment は content 内の半開区間で、互いに重ならない。隙間は許す。"""

    last_end = 0
    length = len(content)
    for index, segment in enumerate(segments):
        if segment.normalized_start < last_end or segment.normalized_end > length:
            raise ValueError(
                "SourceSegment が content の範囲外か、前の segment と重なっている: "
                f"index={index}, start={segment.normalized_start}, "
                f"end={segment.normalized_end}, content_length={length}"
            )
        last_end = segment.normalized_end


def segment_for_span(
    segments: Sequence[SourceSegment], *, start: int, end: int
) -> SourceSegment:
    """正規化後の半開区間を、それを含む segment（page / time / speaker）へ戻す。"""

    if end <= start:
        raise SourceIngestionError(
            f"span の end は start より大きい必要がある: start={start}, end={end}",
            kind=IngestionFailureKind.validation,
        )
    matches = [
        segment
        for segment in segments
        if segment.normalized_start <= start and end <= segment.normalized_end
    ]
    if len(matches) != 1:
        raise SourceIngestionError(
            "span がちょうど 1 つの SourceSegment に収まらない: "
            f"start={start}, end={end}, matches={len(matches)}",
            kind=IngestionFailureKind.validation,
        )
    return matches[0]


def validate_ingestion_request(request: SourceIngestionRequest) -> None:
    """形式共通の拒否と、source_type ごとの必須項目。取得はしない。"""

    _reject_secret_mapping(request.metadata, path="metadata")
    _reject_raw_metadata_keys(request.metadata)
    language = request.language.strip()
    if not language:
        raise SourceIngestionError(
            "language が空",
            kind=IngestionFailureKind.validation,
        )
    _validate_media(request)
    _validate_locator(request)
    _require_source_fields(request)
    if request.text is not None:
        if request.text == "":
            raise SourceIngestionError(
                "text が空",
                kind=IngestionFailureKind.validation,
            )
        _reject_oversized(request.text, label="text")
        _reject_raw_payload(request.text)
    if request.note is not None and request.metadata.get("note") not in (
        None,
        request.note,
    ):
        raise SourceIngestionError(
            "note が metadata.note と矛盾している",
            kind=IngestionFailureKind.validation,
        )
    if "prior_source_id" in request.metadata:
        raise SourceIngestionError(
            "prior_source_id は再投入の判定が付与する",
            kind=IngestionFailureKind.validation,
        )


def assemble_ingestion_result(
    *,
    source_type: SourceType,
    title: str,
    language: str,
    drafts: Sequence[SourceSegmentDraft],
    adapter_version: str,
    ingested_at: datetime,
    canonical_locator: str | None = None,
    filename: str | None = None,
    external_id: str | None = None,
    fetched_at: datetime | None = None,
    provider: str | None = None,
    provider_model: str | None = None,
    mime_type: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> SourceIngestionResult:
    """正規化前の plain text 断片を、共有契約の結果へまとめる。

    HTML / PDF の raw payload は受け取らない。adapter は本文抽出のあとで
    この関数を通す。
    """

    cleaned_title = title.strip()
    if not cleaned_title:
        raise SourceIngestionError(
            "title が空",
            kind=IngestionFailureKind.validation,
        )
    cleaned_language = language.strip()
    if not cleaned_language:
        raise SourceIngestionError(
            "language が空",
            kind=IngestionFailureKind.validation,
        )
    if not adapter_version.strip():
        raise SourceIngestionError(
            "adapter_version が空",
            kind=IngestionFailureKind.validation,
        )
    extra = dict(metadata or {})
    _reject_secret_mapping(extra)
    _reject_raw_metadata_keys(extra)
    content, segments, original_hash = _compose_plain_text(drafts)
    provenance = SourceProvenance(
        canonical_locator=_clean(canonical_locator),
        filename=_clean(filename),
        external_id=_clean(external_id),
        fetched_at=fetched_at,
        ingested_at=ingested_at,
        adapter_version=adapter_version.strip(),
        provider=_clean(provider),
        provider_model=_clean(provider_model),
        original_content_hash=original_hash,
        mime_type=_canonical_mime(mime_type),
        ingestion_version=INGESTION_VERSION,
    )
    return SourceIngestionResult(
        title=cleaned_title,
        normalized_content=content,
        language=cleaned_language,
        source_type=source_type,
        provenance=provenance,
        segments=segments,
        content_hash=content_digest(content),
        ingestion_version=INGESTION_VERSION,
        metadata=extra,
    )


def ingest_manual_text(
    request: SourceIngestionRequest, *, ingested_at: datetime
) -> SourceIngestionResult:
    """手入力テキストを共有契約へ載せる。投稿 API の無変換保存とは別経路。"""

    validate_ingestion_request(request)
    if request.source_type != "manual_text":
        raise SourceIngestionError(
            "ingest_manual_text は manual_text 専用",
            kind=IngestionFailureKind.validation,
        )
    assert request.text is not None
    assert request.title is not None
    metadata = dict(request.metadata)
    if request.note:
        metadata["note"] = request.note
    return assemble_ingestion_result(
        source_type="manual_text",
        title=request.title,
        language=request.language,
        drafts=[SourceSegmentDraft(text=request.text)],
        adapter_version=MANUAL_TEXT_ADAPTER_VERSION,
        ingested_at=ingested_at,
        canonical_locator=request.locator,
        filename=request.filename,
        external_id=request.external_id,
        mime_type=request.mime_type,
        metadata=metadata,
    )


def ingest_source(
    request: SourceIngestionRequest,
    *,
    ingested_at: datetime,
    adapter: SourceIngestionAdapter | None = None,
) -> SourceIngestionResult:
    """実装済み adapter へ振り分ける。未実装の形式は取得せずに拒否する。"""

    validate_ingestion_request(request)
    if request.source_type == "manual_text":
        return ingest_manual_text(request, ingested_at=ingested_at)
    if adapter is None:
        raise SourceIngestionError(
            f"{request.source_type} の adapter は未実装",
            kind=IngestionFailureKind.not_implemented,
        )
    if adapter.source_type != request.source_type:
        raise SourceIngestionError(
            "adapter の source_type が request と一致しない: "
            f"adapter={adapter.source_type}, request={request.source_type}",
            kind=IngestionFailureKind.validation,
        )
    result = adapter.ingest(request, ingested_at=ingested_at)
    if result.source_type != request.source_type:
        raise SourceIngestionError(
            "adapter の結果 source_type が request と一致しない",
            kind=IngestionFailureKind.validation,
        )
    if result.provenance.adapter_version != adapter.adapter_version:
        raise SourceIngestionError(
            "adapter_version が provenance と一致しない",
            kind=IngestionFailureKind.validation,
        )
    return result


def plan_source_ingestion(
    existing: Sequence[StoredSourceIdentity], result: SourceIngestionResult
) -> IngestPlan:
    """同じ外部 Source の再投入を、上書きせずに振り分ける。

    locator が無いときは常に create。同一本文は reuse。本文または
    ingestion_version が違えば append_version とし、既存行は変更しない。
    """

    locator = result.provenance.canonical_locator
    if locator is None:
        return IngestPlan(action=IngestAction.create)
    matches = [
        item
        for item in existing
        if item.source_type == result.source_type and item.canonical_locator == locator
    ]
    identical = [
        item
        for item in matches
        if item.content_hash == result.content_hash
        and item.ingestion_version == result.ingestion_version
    ]
    if identical:
        chosen = min(identical, key=lambda item: (item.created_at, item.id))
        return IngestPlan(action=IngestAction.reuse, existing_id=chosen.id)
    if matches:
        prior = max(matches, key=lambda item: (item.created_at, item.id))
        return IngestPlan(action=IngestAction.append_version, prior_source_id=prior.id)
    return IngestPlan(action=IngestAction.create)


def _compose_plain_text(
    drafts: Sequence[SourceSegmentDraft],
) -> tuple[str, list[SourceSegment], str]:
    if not drafts:
        raise SourceIngestionError(
            "segment が空",
            kind=IngestionFailureKind.validation,
        )
    raw_parts: list[str] = []
    pieces: list[str] = []
    for draft in drafts:
        _reject_oversized(draft.text, label="segment")
        _reject_raw_payload(draft.text)
        raw_parts.append(draft.text)
        piece = normalize_source_text(draft.text)
        if not piece:
            raise SourceIngestionError(
                "正規化後の segment が空",
                kind=IngestionFailureKind.validation,
            )
        pieces.append(piece)
    raw_joined = "\n\n".join(raw_parts)
    _reject_oversized(raw_joined, label="text")
    content = "\n\n".join(pieces)
    _reject_oversized(content, label="normalized_content")
    if normalize_source_text(content) != content:
        raise SourceIngestionError(
            "共有正規化が安定しない",
            kind=IngestionFailureKind.validation,
        )
    segments: list[SourceSegment] = []
    cursor = 0
    for index, (piece, draft) in enumerate(zip(pieces, drafts, strict=True)):
        if index:
            cursor += 2
        segments.append(
            SourceSegment(
                normalized_start=cursor,
                normalized_end=cursor + len(piece),
                page_number=draft.page_number,
                start_seconds=draft.start_seconds,
                end_seconds=draft.end_seconds,
                speaker=draft.speaker,
                external_locator=draft.external_locator,
            )
        )
        cursor += len(piece)
    return content, segments, content_digest(raw_joined)


def _require_timecode_pair(
    start_seconds: float | None, end_seconds: float | None
) -> None:
    if (start_seconds is None) != (end_seconds is None):
        raise ValueError("start_seconds と end_seconds は揃っている必要がある")
    if (
        start_seconds is not None
        and end_seconds is not None
        and end_seconds <= start_seconds
    ):
        raise ValueError(
            "end_seconds は start_seconds より大きい必要がある: "
            f"start={start_seconds}, end={end_seconds}"
        )


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _canonical_mime(mime_type: str | None) -> str | None:
    cleaned = _clean(mime_type)
    if cleaned is None:
        return None
    return cleaned.lower()


def _reject_oversized(text: str, *, label: str) -> None:
    if len(text) > MAX_SOURCE_TEXT_CHARS:
        raise SourceIngestionError(
            f"{label} が上限 {MAX_SOURCE_TEXT_CHARS} 文字を超えている",
            kind=IngestionFailureKind.input_too_large,
        )


def _reject_raw_payload(text: str) -> None:
    if "\x00" in text:
        raise SourceIngestionError(
            "NUL を含む入力は plain text として扱えない",
            kind=IngestionFailureKind.validation,
        )
    probe = text.lstrip("\ufeff \t\r\n")
    lowered = probe[:64].lower()
    if probe.startswith("%PDF"):
        raise SourceIngestionError(
            "PDF の raw payload は SourceDocument.content にできない",
            kind=IngestionFailureKind.validation,
        )
    if lowered.startswith("<!doctype html") or lowered.startswith("<html"):
        raise SourceIngestionError(
            "HTML 文書は SourceDocument.content にできない",
            kind=IngestionFailureKind.validation,
        )


def _reject_raw_metadata_keys(metadata: dict[str, Any]) -> None:
    for key in metadata:
        if isinstance(key, str) and key.lower() in _RAW_PAYLOAD_KEYS:
            raise SourceIngestionError(
                f"raw payload は metadata に保存できない: {key}",
                kind=IngestionFailureKind.validation,
            )


def _reject_secret_mapping(value: object, *, path: str = "metadata") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = key if isinstance(key, str) else ""
            if not isinstance(key, str) or _SECRET_KEY_RE.search(key_text):
                raise SourceIngestionError(
                    f"secret を含むキーは保存できない: {path}.{key}",
                    kind=IngestionFailureKind.validation,
                )
            _reject_secret_mapping(item, path=f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _reject_secret_mapping(item, path=f"{path}[{index}]")


def _validate_media(request: SourceIngestionRequest) -> None:
    mime = _canonical_mime(request.mime_type)
    if mime is not None and mime not in _ALLOWED_MIME_TYPES[request.source_type]:
        raise SourceIngestionError(
            f"{request.source_type} では MIME {mime} を受け付けない",
            kind=IngestionFailureKind.unsupported_media,
        )
    filename = _clean(request.filename)
    if filename is None:
        return
    allowed = _ALLOWED_EXTENSIONS.get(request.source_type)
    if allowed is None:
        return
    suffix = _suffix(filename)
    if suffix not in allowed:
        raise SourceIngestionError(
            f"{request.source_type} では拡張子 {suffix or '(なし)'} を受け付けない",
            kind=IngestionFailureKind.unsupported_media,
        )


def _suffix(filename: str) -> str:
    dot = filename.rfind(".")
    slash = max(filename.rfind("/"), filename.rfind("\\"))
    if dot <= slash:
        return ""
    return filename[dot:].lower()


def _validate_locator(request: SourceIngestionRequest) -> None:
    locator = _clean(request.locator)
    if locator is None or request.source_type != "web_url":
        if locator is not None and "://" in locator:
            _reject_locator_userinfo(locator)
        return
    lowered = locator.lower()
    if not (lowered.startswith("https://") or lowered.startswith("http://")):
        raise SourceIngestionError(
            "web_url の locator は http(s) URL である必要がある",
            kind=IngestionFailureKind.validation,
        )
    if any(character.isspace() for character in locator):
        raise SourceIngestionError(
            "web_url の locator に空白は使えない",
            kind=IngestionFailureKind.validation,
        )
    _reject_locator_userinfo(locator)


def _reject_locator_userinfo(locator: str) -> None:
    rest = locator.split("://", 1)[1]
    authority = rest.split("/", 1)[0]
    if "@" in authority:
        raise SourceIngestionError(
            "locator に認証情報を含められない",
            kind=IngestionFailureKind.validation,
        )


def _require_source_fields(request: SourceIngestionRequest) -> None:
    locator = _clean(request.locator)
    filename = _clean(request.filename)
    external_id = _clean(request.external_id)
    title = _clean(request.title)
    text = request.text
    source_type = request.source_type
    if source_type == "manual_text":
        if title is None or text is None:
            raise SourceIngestionError(
                "manual_text には title と text が必要",
                kind=IngestionFailureKind.validation,
            )
        return
    if source_type == "web_url" and locator is None:
        raise SourceIngestionError(
            "web_url には locator が必要",
            kind=IngestionFailureKind.validation,
        )
    if source_type == "pdf" and locator is None and filename is None:
        raise SourceIngestionError(
            "pdf には filename または locator が必要",
            kind=IngestionFailureKind.validation,
        )
    if source_type == "youtube_transcript" and locator is None and external_id is None:
        raise SourceIngestionError(
            "youtube_transcript には locator または external_id が必要",
            kind=IngestionFailureKind.validation,
        )
    if source_type == "subtitle" and filename is None:
        raise SourceIngestionError(
            "subtitle には filename が必要",
            kind=IngestionFailureKind.validation,
        )
    if source_type == "audio_transcript" and locator is None and filename is None:
        raise SourceIngestionError(
            "audio_transcript には locator または filename が必要",
            kind=IngestionFailureKind.validation,
        )
    if source_type == "conversation_log" and text is None and locator is None:
        raise SourceIngestionError(
            "conversation_log には text または locator が必要",
            kind=IngestionFailureKind.validation,
        )
