"""Candidate の抽出保存と採否（Issue #134）。

ExtractionService は Candidate をメモリ上で返すだけ。このサービスが
Source 単位の保存、再抽出時の重複抑止、accept 時の LearningItem 化を行う。
router は HTTP 変換だけ行い、LLM / SQL / domain rule はここに置かない。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.domain.candidate_normalization import (
    CandidateExclusion,
    candidate_normalization_key,
    learning_item_normalization_key,
)
from app.domain.conjugation_adapter import (
    conjugation_item_metadata,
    merge_conjugation_item_metadata,
)
from app.domain.tutor import (
    EvidenceSpan,
    LearningItem,
    LearningItemCandidate,
    SourceDocument,
    SourceRef,
    apply_candidate_status,
    read_source_evidence,
)
from app.repositories.exceptions import DuplicateEntityError, ReferentialIntegrityError
from app.repositories.protocols import (
    CandidatePromotionRepository,
    KnownItemRepository,
    LearningItemCandidateRepository,
    LearningItemRepository,
    SourceDocumentRepository,
)
from app.services.exceptions import (
    InvalidCandidateTransitionError,
    TutorConflictError,
    TutorInvalidCandidateError,
    TutorNotFoundError,
)
from app.services.extraction_service import ExtractionService


@dataclass(frozen=True)
class CandidateView:
    """API 向け。evidence 断片は Source 本文から再構成する。"""

    candidate: LearningItemCandidate
    evidence_text: str
    learning_item_id: str | None = None
    explicit_known: bool = False


@dataclass(frozen=True)
class ExtractCandidatesResult:
    source_document_id: str
    extraction_version: str
    created: tuple[CandidateView, ...]
    skipped: tuple[CandidateView, ...]
    exclusions: tuple[CandidateExclusion, ...] = ()


@dataclass(frozen=True)
class AcceptCandidateResult:
    candidate: CandidateView
    item: LearningItem
    merged: bool


class _CandidateStore(Protocol):
    source_documents: SourceDocumentRepository
    learning_items: LearningItemRepository
    learning_item_candidates: LearningItemCandidateRepository
    candidate_promotions: CandidatePromotionRepository
    known_items: KnownItemRepository


def build_candidate_service(
    store: _CandidateStore,
    extraction: ExtractionService,
) -> CandidateService:
    """repository 一式と ExtractionService から CandidateService を組み立てる。"""
    return CandidateService(
        sources=store.source_documents,
        items=store.learning_items,
        candidates=store.learning_item_candidates,
        promotions=store.candidate_promotions,
        known=store.known_items,
        extraction=extraction,
    )


class CandidateService:
    def __init__(
        self,
        *,
        sources: SourceDocumentRepository,
        items: LearningItemRepository,
        candidates: LearningItemCandidateRepository,
        promotions: CandidatePromotionRepository,
        known: KnownItemRepository,
        extraction: ExtractionService,
    ) -> None:
        self._sources = sources
        self._items = items
        self._candidates = candidates
        self._promotions = promotions
        self._known = known
        self._extraction = extraction

    def extract_for_source(self, source_id: str) -> ExtractCandidatesResult:
        """Source から抽出し、未保存の Candidate だけを保存する。

        同じ normalization key の既存 Candidate（accepted / rejected /
        candidate）は追加しない。終端状態を復活させず、重複爆発もしない。
        LLM 障害時は保存しない。
        """
        source = self._require_source(source_id)
        extracted = self._extraction.extract(source)
        existing = self._candidates.list_by_source(source_id)
        existing_by_key = _index_by_normalization_key(existing)

        to_create: list[LearningItemCandidate] = []
        skipped: list[LearningItemCandidate] = []
        for candidate in extracted.candidates:
            key = candidate_normalization_key(candidate)
            previous = existing_by_key.get(key)
            if previous is not None:
                skipped.append(previous)
                continue
            to_create.append(candidate)
            existing_by_key[key] = candidate

        created = self._candidates.create_many(to_create)
        return ExtractCandidatesResult(
            source_document_id=source.id,
            extraction_version=extracted.extraction_version,
            created=tuple(self._view(item, source) for item in created),
            skipped=tuple(self._view(item, source) for item in skipped),
            exclusions=extracted.exclusions,
        )

    def list_for_source(self, source_id: str) -> list[CandidateView]:
        source = self._require_source(source_id)
        return [
            self._view(candidate, source)
            for candidate in self._candidates.list_by_source(source_id)
        ]

    def accept(self, candidate_id: str) -> AcceptCandidateResult:
        """Candidate を採用し、LearningItem を作成または既存へ統合する。

        再 accept は冪等。rejected からの accept は拒否する。
        """
        candidate = self._require_candidate(candidate_id)
        if candidate.status == "rejected":
            raise InvalidCandidateTransitionError(
                candidate_id, candidate.status, "accepted"
            )

        source = self._require_source(candidate.source_document_id)
        self._require_acceptable_evidence(candidate, source)

        if candidate.status == "accepted":
            item = self._find_matching_item(candidate)
            if item is None:
                item = self._new_item_from_candidate(candidate)
                accepted, item = self._persist_accept(candidate, item, create_item=True)
                return AcceptCandidateResult(
                    candidate=self._view(accepted, source),
                    item=item,
                    merged=False,
                )
            return AcceptCandidateResult(
                candidate=self._view(candidate, source),
                item=item,
                merged=True,
            )

        accepted = apply_candidate_status(candidate, "accepted")
        existing_item = self._find_matching_item(accepted)
        if existing_item is None:
            item = self._new_item_from_candidate(accepted)
            persisted, item = self._persist_accept(accepted, item, create_item=True)
            return AcceptCandidateResult(
                candidate=self._view(persisted, source),
                item=item,
                merged=False,
            )

        item = self._with_source_ref(existing_item, accepted)
        persisted, item = self._persist_accept(accepted, item, create_item=False)
        return AcceptCandidateResult(
            candidate=self._view(persisted, source),
            item=item,
            merged=True,
        )

    def reject(self, candidate_id: str) -> CandidateView:
        """Candidate を却下する。LearningItem は作らない。再 reject は冪等。"""
        candidate = self._require_candidate(candidate_id)
        if candidate.status == "accepted":
            raise InvalidCandidateTransitionError(
                candidate_id, candidate.status, "rejected"
            )
        source = self._require_source(candidate.source_document_id)
        if candidate.status == "rejected":
            return self._view(candidate, source)
        try:
            updated = self._candidates.update_status(candidate_id, "rejected")
        except ReferentialIntegrityError as exc:
            raise TutorNotFoundError("LearningItemCandidate", candidate_id) from exc
        except ValueError as exc:
            raise InvalidCandidateTransitionError(
                candidate_id, candidate.status, "rejected"
            ) from exc
        return self._view(updated, source)

    def _persist_accept(
        self,
        candidate: LearningItemCandidate,
        item: LearningItem,
        *,
        create_item: bool,
    ) -> tuple[LearningItemCandidate, LearningItem]:
        try:
            return self._promotions.persist_accept(
                candidate, item, create_item=create_item
            )
        except ReferentialIntegrityError as exc:
            message = str(exc)
            if "LearningItemCandidate" in message:
                raise TutorNotFoundError("LearningItemCandidate", candidate.id) from exc
            raise TutorNotFoundError("LearningItem", item.id) from exc
        except DuplicateEntityError as exc:
            raise TutorConflictError(exc.entity_type, exc.entity_id) from exc
        except ValueError as exc:
            raise InvalidCandidateTransitionError(
                candidate.id, "unknown", candidate.status
            ) from exc

    def _require_source(self, source_id: str) -> SourceDocument:
        document = self._sources.get(source_id)
        if document is None:
            raise TutorNotFoundError("SourceDocument", source_id)
        return document

    def _require_candidate(self, candidate_id: str) -> LearningItemCandidate:
        candidate = self._candidates.get(candidate_id)
        if candidate is None:
            raise TutorNotFoundError("LearningItemCandidate", candidate_id)
        return candidate

    def _require_acceptable_evidence(
        self, candidate: LearningItemCandidate, source: SourceDocument
    ) -> str:
        try:
            fragment = read_source_evidence(source.content, candidate.evidence_span)
        except ValueError as exc:
            raise TutorInvalidCandidateError(candidate.id, str(exc)) from exc
        if fragment.strip() == "":
            raise TutorInvalidCandidateError(
                candidate.id, "evidence が空、または whitespace のみ"
            )
        return fragment

    def _find_matching_item(
        self, candidate: LearningItemCandidate
    ) -> LearningItem | None:
        key = candidate_normalization_key(candidate)
        for item in self._items.list():
            if learning_item_normalization_key(item) == key:
                return item
        return None

    def _new_item_from_candidate(
        self, candidate: LearningItemCandidate
    ) -> LearningItem:
        return LearningItem(
            item_type=candidate.item_type,
            canonical_form=candidate.canonical_form,
            meaning_ja=candidate.meaning_ja,
            explanation_ja=candidate.explanation_ja,
            level=candidate.level,
            source_refs=[_source_ref_from_candidate(candidate)],
            metadata=conjugation_item_metadata(candidate),
        )

    def _with_source_ref(
        self, item: LearningItem, candidate: LearningItemCandidate
    ) -> LearningItem:
        source_id = candidate.source_document_id
        if any(ref.source_document_id == source_id for ref in item.source_refs):
            return item
        return item.model_copy(
            update={
                "source_refs": [
                    *item.source_refs,
                    _source_ref_from_candidate(candidate),
                ],
                "metadata": merge_conjugation_item_metadata(item, candidate),
            }
        )

    def _view(
        self, candidate: LearningItemCandidate, source: SourceDocument
    ) -> CandidateView:
        try:
            evidence_text = read_source_evidence(
                source.content, candidate.evidence_span
            )
        except ValueError:
            evidence_text = ""
        learning_item_id = None
        explicit_known = False
        if candidate.status == "accepted":
            item = self._find_matching_item(candidate)
            if item is not None:
                learning_item_id = item.id
                override = self._known.get(item.id)
                explicit_known = override is not None and override.active
        return CandidateView(
            candidate=candidate,
            evidence_text=evidence_text,
            learning_item_id=learning_item_id,
            explicit_known=explicit_known,
        )


def _index_by_normalization_key(
    candidates: Sequence[LearningItemCandidate],
) -> dict[str, LearningItemCandidate]:
    index: dict[str, LearningItemCandidate] = {}
    for candidate in candidates:
        key = candidate_normalization_key(candidate)
        previous = index.get(key)
        if previous is None or (
            previous.status == "candidate" and candidate.status != "candidate"
        ):
            index[key] = candidate
    return index


def _source_ref_from_candidate(candidate: LearningItemCandidate) -> SourceRef:
    span = candidate.evidence_span
    return SourceRef(
        source_document_id=candidate.source_document_id,
        evidence_span=EvidenceSpan(start=span.start, end=span.end),
        confidence=candidate.confidence,
    )
