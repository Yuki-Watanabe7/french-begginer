"""SRT / VTT を SourceIngestionResult にする adapter（Issue #192）。

解析は `subtitle_text`、cue の整形は `timed_text` に閉じる。
正規化と時刻 segment の組み立ては共有の `assemble_ingestion_result` を通す。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.domain.source_ingestion import (
    MAX_SHORT_FIELD_CHARS,
    IngestionFailureKind,
    SourceIngestionError,
    SourceIngestionRequest,
    SourceIngestionResult,
    SourceType,
    assemble_ingestion_result,
)
from app.ingestion.subtitle_errors import (
    MSG_INVALID_SUBTITLE,
    MSG_MALFORMED_SUBTITLE,
    MSG_SUBTITLE_EMPTY,
    MSG_TEXT_TOO_LARGE,
    SubtitleIngestErrorCode,
    SubtitleIngestionError,
)
from app.ingestion.subtitle_text import (
    SUBTITLE_ADAPTER_VERSION,
    SubtitleFormat,
    decode_subtitle,
    parse_subtitle_text,
    sniff_subtitle_format,
    stored_mime_type,
)
from app.ingestion.timed_text import TimedTextError, cues_to_drafts


class SubtitleIngestionAdapter:
    """1 件の字幕ファイルを、時刻 provenance 付きの plain text にする。"""

    source_type: SourceType = "subtitle"
    adapter_version = SUBTITLE_ADAPTER_VERSION

    def __init__(
        self,
        data: bytes,
        *,
        filename: str,
        subtitle_format: SubtitleFormat,
        file_sha256: str,
    ) -> None:
        self._data = data
        self._filename = filename
        self._format: SubtitleFormat = subtitle_format
        self._file_sha256 = file_sha256

    def ingest(
        self, request: SourceIngestionRequest, *, ingested_at: datetime
    ) -> SourceIngestionResult:
        if request.source_type != "subtitle":
            raise SourceIngestionError(
                "SubtitleIngestionAdapter は subtitle 専用",
                kind=IngestionFailureKind.validation,
            )
        if request.locator not in (None, self._file_sha256):
            raise SubtitleIngestionError(
                MSG_INVALID_SUBTITLE, code=SubtitleIngestErrorCode.invalid_subtitle
            )
        text = decode_subtitle(self._data)
        if sniff_subtitle_format(text) != self._format:
            raise SubtitleIngestionError(
                MSG_MALFORMED_SUBTITLE,
                code=SubtitleIngestErrorCode.malformed_subtitle,
            )
        cues = parse_subtitle_text(text, subtitle_format=self._format)
        try:
            built = cues_to_drafts(cues)
        except TimedTextError as exc:
            raise SubtitleIngestionError(
                MSG_MALFORMED_SUBTITLE,
                code=SubtitleIngestErrorCode.malformed_subtitle,
            ) from exc
        if not built.drafts:
            raise SubtitleIngestionError(
                MSG_SUBTITLE_EMPTY, code=SubtitleIngestErrorCode.subtitle_empty
            )
        metadata: dict[str, Any] = {
            "format": self._format,
            "file_sha256": self._file_sha256,
            "cue_count": len(built.drafts),
            "empty_cue_count": built.empty_cue_count,
        }
        if request.note and request.note.strip():
            metadata["note"] = request.note.strip()
        try:
            return assemble_ingestion_result(
                source_type="subtitle",
                title=_choose_title(request.title, self._filename),
                language=request.language,
                drafts=built.drafts,
                adapter_version=self.adapter_version,
                ingested_at=ingested_at,
                canonical_locator=self._file_sha256,
                filename=self._filename,
                mime_type=stored_mime_type(self._format),
                metadata=metadata,
            )
        except SourceIngestionError as exc:
            if exc.kind is IngestionFailureKind.input_too_large:
                raise SubtitleIngestionError(
                    MSG_TEXT_TOO_LARGE, code=SubtitleIngestErrorCode.text_too_large
                ) from exc
            raise


def _choose_title(override: str | None, filename: str) -> str:
    chosen = override.strip() if override else ""
    if not chosen:
        chosen = _stem(filename)
    collapsed = " ".join(chosen.split())
    bounded = collapsed[:MAX_SHORT_FIELD_CHARS].strip()
    return bounded or "字幕"


def _stem(filename: str) -> str:
    dot = filename.rfind(".")
    if dot <= 0:
        return "" if dot == 0 else filename
    return filename[:dot]
