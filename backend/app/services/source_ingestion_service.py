"""Source ingestion の結果を、既存 Source を上書きせずに保存する（Issue #189）。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from app.domain.source_ingestion import (
    IngestAction,
    IngestionFailureKind,
    SourceIngestionError,
    SourceIngestionRequest,
    SourceIngestionResult,
    StoredSourceIdentity,
    plan_source_ingestion,
)
from app.domain.source_ingestion import (
    ingest_manual_text as build_manual_text_ingestion,
)
from app.domain.tutor import SourceDocument, source_document_from_ingestion, utcnow
from app.repositories.protocols import SourceDocumentRepository


@dataclass(frozen=True)
class CommittedIngestion:
    document: SourceDocument
    action: IngestAction
    created: bool


class SourceIngestionService:
    def __init__(
        self,
        sources: SourceDocumentRepository,
        *,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._sources = sources
        self._clock = clock

    def ingest_manual_text(self, request: SourceIngestionRequest) -> CommittedIngestion:
        result = build_manual_text_ingestion(request, ingested_at=self._clock())
        return self.commit(result)

    def commit(self, result: SourceIngestionResult) -> CommittedIngestion:
        locator = result.provenance.canonical_locator
        existing: list[SourceDocument] = []
        if locator is not None:
            existing = self._sources.list_by_locator(
                source_type=result.source_type,
                canonical_locator=locator,
            )
        plan = plan_source_ingestion(
            [_identity(document) for document in existing], result
        )
        if plan.action is IngestAction.reuse:
            if plan.existing_id is None:
                raise SourceIngestionError(
                    "再利用対象の Source が決まっていない",
                    kind=IngestionFailureKind.validation,
                )
            document = self._sources.get(plan.existing_id)
            if document is None:
                raise SourceIngestionError(
                    "再利用対象の Source が見つからない",
                    kind=IngestionFailureKind.validation,
                )
            return CommittedIngestion(
                document=document, action=plan.action, created=False
            )
        document = source_document_from_ingestion(
            result, prior_source_id=plan.prior_source_id
        )
        saved = self._sources.create(document)
        return CommittedIngestion(document=saved, action=plan.action, created=True)


def _identity(document: SourceDocument) -> StoredSourceIdentity:
    provenance = document.provenance
    return StoredSourceIdentity(
        id=document.id,
        source_type=document.source_type,
        canonical_locator=None if provenance is None else provenance.canonical_locator,
        content_hash=document.content_hash,
        ingestion_version=document.ingestion_version,
        created_at=document.created_at,
    )
