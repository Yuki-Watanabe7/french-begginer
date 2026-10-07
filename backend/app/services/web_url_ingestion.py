"""Web URL を取得し、既存 Source を上書きせずに保存する（Issue #190）。

HTTP client には依存しない。取得は `WebPageFetcher`、保存の再利用は
`SourceIngestionService.commit` が担う。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from app.domain.source_ingestion import SourceIngestionRequest, ingest_source
from app.domain.tutor import utcnow
from app.ingestion.fetcher import WebPageFetcher
from app.ingestion.web_url import WebUrlIngestionAdapter
from app.repositories.protocols import SourceDocumentRepository
from app.services.source_ingestion_service import (
    CommittedIngestion,
    SourceIngestionService,
)


class WebUrlIngestionService:
    def __init__(
        self,
        sources: SourceDocumentRepository,
        fetcher: WebPageFetcher,
        *,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._fetcher = fetcher
        self._clock = clock
        self._commit = SourceIngestionService(sources, clock=clock)

    def ingest_url(
        self,
        *,
        url: str,
        title: str | None = None,
        note: str | None = None,
        language: str = "fr",
    ) -> CommittedIngestion:
        """同じ正規化 URL と本文なら既存を返し、本文が変わったら版を追加する。"""

        ingested_at = self._clock()
        request = SourceIngestionRequest(
            source_type="web_url",
            locator=url.strip(),
            title=title,
            note=note,
            language=language,
        )
        result = ingest_source(
            request,
            ingested_at=ingested_at,
            adapter=WebUrlIngestionAdapter(self._fetcher),
        )
        return self._commit.commit(result)
