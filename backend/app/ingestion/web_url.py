"""Web URL を SourceIngestionResult にする adapter（Issue #190）。

取得は `WebPageFetcher`、本文抽出は `html_extract` に閉じる。
正規化と provenance の組み立ては共有の `assemble_ingestion_result` を通す。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import urljoin

from app.domain.source_ingestion import (
    MAX_LOCATOR_CHARS,
    MAX_SHORT_FIELD_CHARS,
    IngestionFailureKind,
    SourceIngestionError,
    SourceIngestionRequest,
    SourceIngestionResult,
    SourceSegmentDraft,
    SourceType,
    assemble_ingestion_result,
)
from app.ingestion.errors import (
    MSG_EXTRACTION_EMPTY,
    MSG_RESPONSE_TOO_LARGE,
    WebFetchErrorCode,
    WebUrlIngestionError,
)
from app.ingestion.fetcher import WebPageFetcher
from app.ingestion.html_extract import (
    decode_page_text,
    extract_html,
    plain_text_paragraphs,
)
from app.ingestion.url_policy import validate_web_url

WEB_URL_ADAPTER_VERSION = "web-url-v1"
MIN_EXTRACTED_CHARS = 40


class WebUrlIngestionAdapter:
    """1 件の http(s) URL を plain text の Source 材料にする。"""

    source_type: SourceType = "web_url"
    adapter_version = WEB_URL_ADAPTER_VERSION

    def __init__(self, fetcher: WebPageFetcher) -> None:
        self._fetcher = fetcher

    def ingest(
        self, request: SourceIngestionRequest, *, ingested_at: datetime
    ) -> SourceIngestionResult:
        if request.source_type != "web_url":
            raise SourceIngestionError(
                "WebUrlIngestionAdapter は web_url 専用",
                kind=IngestionFailureKind.validation,
            )
        page = self._fetcher.fetch(request.locator or "", fetched_at=ingested_at)
        requested = validate_web_url(page.requested_url)
        final = validate_web_url(page.final_url)
        text = decode_page_text(
            page.body,
            media_type=page.media_type,
            content_type_header=page.content_type_header,
        )
        if page.media_type == "text/plain":
            title_from_page = None
            paragraphs = list(plain_text_paragraphs(text))
            canonical_href = None
        else:
            extracted = extract_html(text)
            title_from_page = extracted.title
            paragraphs = list(extracted.paragraphs)
            canonical_href = extracted.canonical_href
        paragraphs = [paragraph for paragraph in paragraphs if paragraph.strip()]
        if not paragraphs:
            raise WebUrlIngestionError(
                MSG_EXTRACTION_EMPTY, code=WebFetchErrorCode.extraction_empty
            )
        title = _choose_title(
            override=request.title,
            extracted=title_from_page,
            fallback=final.hostname,
        )
        locator = final.normalized_url
        external_locator = locator if len(locator) <= MAX_LOCATOR_CHARS else None
        drafts = [
            SourceSegmentDraft(text=paragraph, external_locator=external_locator)
            for paragraph in paragraphs
        ]
        metadata: dict[str, Any] = {
            "requested_url": requested.normalized_url,
            "final_url": final.normalized_url,
        }
        canonical = _safe_canonical(canonical_href, final.normalized_url)
        if canonical is not None:
            metadata["canonical_url"] = canonical
        if request.note and request.note.strip():
            metadata["note"] = request.note.strip()
        try:
            result = assemble_ingestion_result(
                source_type="web_url",
                title=title,
                language=request.language,
                drafts=drafts,
                adapter_version=self.adapter_version,
                ingested_at=ingested_at,
                canonical_locator=requested.normalized_url,
                fetched_at=page.fetched_at,
                mime_type=page.media_type,
                metadata=metadata,
            )
        except SourceIngestionError as exc:
            if exc.kind is IngestionFailureKind.input_too_large:
                raise WebUrlIngestionError(
                    MSG_RESPONSE_TOO_LARGE,
                    code=WebFetchErrorCode.response_too_large,
                ) from exc
            raise
        if len(result.normalized_content) < MIN_EXTRACTED_CHARS:
            raise WebUrlIngestionError(
                MSG_EXTRACTION_EMPTY, code=WebFetchErrorCode.extraction_empty
            )
        return result


def _choose_title(*, override: str | None, extracted: str | None, fallback: str) -> str:
    chosen = override.strip() if override else ""
    if not chosen and extracted:
        chosen = extracted.strip()
    if not chosen:
        chosen = fallback.strip() or "Web page"
    collapsed = " ".join(chosen.split())
    bounded = collapsed[:MAX_SHORT_FIELD_CHARS].strip()
    return bounded or "Web page"


def _safe_canonical(href: str | None, base_url: str) -> str | None:
    if href is None or not href.strip():
        return None
    try:
        return validate_web_url(urljoin(base_url, href.strip())).normalized_url
    except WebUrlIngestionError:
        return None
