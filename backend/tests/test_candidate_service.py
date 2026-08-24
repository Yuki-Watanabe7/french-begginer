"""CandidateService（Issue #134）のユースケーステスト。

抽出の保存、再抽出の重複抑止、accept/reject の状態遷移と
LearningItem 化を、fake extractor と in-memory SQLite で確認する。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from sqlalchemy.orm import Session

from app.domain.tutor import (
    EvidenceSpan,
    LearningItem,
    LearningItemCandidate,
    SourceDocument,
    SourceRef,
)
from app.persistence.models import LearningItemRow
from app.repositories.sqlite import TutorSqliteStore
from app.services.candidate_service import CandidateService, build_candidate_service
from app.services.exceptions import (
    ExtractionConfigError,
    ExtractionTransientError,
    InvalidCandidateTransitionError,
    TutorInvalidCandidateError,
    TutorNotFoundError,
)
from app.services.extraction_prompt import EXTRACTION_VERSION
from app.services.extraction_schema import ExtractedCandidate, ExtractedEvidenceSpan
from app.services.extraction_service import ExtractionService
from app.services.extractors import ExtractorResult

CONTENT = "Je me suis rendu compte qu'il fallait changer de stratégie."


@dataclass
class FakeLearningItemExtractor:
    result: ExtractorResult | None = None
    error: Exception | None = None
    seen_sources: list[SourceDocument] = field(default_factory=list)

    def extract(self, source: SourceDocument) -> ExtractorResult:
        self.seen_sources.append(source)
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


def _span_for(fragment: str) -> ExtractedEvidenceSpan:
    start = CONTENT.index(fragment)
    return ExtractedEvidenceSpan(start=start, end=start + len(fragment))


def _extracted(
    *,
    item_type: str = "expression",
    canonical_form: str = "se rendre compte",
    meaning_ja: str = "〜に気づく",
    fragment: str = "rendu compte",
    confidence: float = 0.9,
    **overrides,
) -> ExtractedCandidate:
    values = {
        "item_type": item_type,
        "canonical_form": canonical_form,
        "meaning_ja": meaning_ja,
        "evidence_span": _span_for(fragment),
        "confidence": confidence,
    }
    values.update(overrides)
    return ExtractedCandidate(**values)


def _result(
    candidates: tuple[ExtractedCandidate, ...] | list[ExtractedCandidate],
) -> ExtractorResult:
    return ExtractorResult(
        candidates=tuple(candidates),
        provider="openai",
        model="gpt-4o-mini",
        extraction_version=EXTRACTION_VERSION,
    )


@pytest.fixture
def store() -> TutorSqliteStore:
    return TutorSqliteStore.in_memory()


@pytest.fixture
def fake() -> FakeLearningItemExtractor:
    return FakeLearningItemExtractor(result=_result((_extracted(),)))


@pytest.fixture
def service(
    store: TutorSqliteStore, fake: FakeLearningItemExtractor
) -> CandidateService:
    return build_candidate_service(store, ExtractionService(fake))


def _create_source(store: TutorSqliteStore) -> SourceDocument:
    return store.source_documents.create(SourceDocument(title="記事", content=CONTENT))


def test_extract_saves_candidates(
    store: TutorSqliteStore, service: CandidateService, fake: FakeLearningItemExtractor
):
    source = _create_source(store)
    result = service.extract_for_source(source.id)

    assert fake.seen_sources == [source]
    assert result.source_document_id == source.id
    assert result.extraction_version == EXTRACTION_VERSION
    assert len(result.created) == 1
    assert result.skipped == ()
    saved = store.learning_item_candidates.list_by_source(source.id)
    assert len(saved) == 1
    assert saved[0].canonical_form == "se rendre compte"
    assert saved[0].status == "candidate"
    assert saved[0].extraction_version == EXTRACTION_VERSION
    assert store.learning_items.list() == []


def test_extract_missing_source_raises_not_found_without_calling_llm(
    service: CandidateService, fake: FakeLearningItemExtractor
):
    with pytest.raises(TutorNotFoundError, match="SourceDocument"):
        service.extract_for_source("missing-source")
    assert fake.seen_sources == []


def test_list_for_source_includes_status_and_evidence_text(
    store: TutorSqliteStore, service: CandidateService
):
    source = _create_source(store)
    service.extract_for_source(source.id)

    listed = service.list_for_source(source.id)
    assert len(listed) == 1
    assert listed[0].candidate.status == "candidate"
    assert listed[0].evidence_text == "rendu compte"
    assert "provider" in listed[0].candidate.metadata


def test_list_missing_source_raises_not_found(service: CandidateService):
    with pytest.raises(TutorNotFoundError, match="SourceDocument"):
        service.list_for_source("missing-source")


def test_reextract_does_not_duplicate_pending_candidates(
    store: TutorSqliteStore, service: CandidateService
):
    source = _create_source(store)
    first = service.extract_for_source(source.id)
    second = service.extract_for_source(source.id)

    assert len(first.created) == 1
    assert len(second.created) == 0
    assert [view.candidate.id for view in second.skipped] == [
        first.created[0].candidate.id
    ]
    assert len(store.learning_item_candidates.list_by_source(source.id)) == 1


def test_reextract_does_not_revive_rejected(
    store: TutorSqliteStore, service: CandidateService
):
    source = _create_source(store)
    created = service.extract_for_source(source.id).created[0]
    service.reject(created.candidate.id)

    again = service.extract_for_source(source.id)
    assert again.created == ()
    assert again.skipped[0].candidate.status == "rejected"
    listed = store.learning_item_candidates.list_by_source(source.id)
    assert len(listed) == 1
    assert listed[0].status == "rejected"


def test_reextract_does_not_revive_accepted(
    store: TutorSqliteStore, service: CandidateService
):
    source = _create_source(store)
    created = service.extract_for_source(source.id).created[0]
    service.accept(created.candidate.id)

    again = service.extract_for_source(source.id)
    assert again.created == ()
    assert again.skipped[0].candidate.status == "accepted"
    listed = store.learning_item_candidates.list_by_source(source.id)
    assert len(listed) == 1
    assert listed[0].status == "accepted"


def test_provider_error_leaves_existing_candidates(
    store: TutorSqliteStore, fake: FakeLearningItemExtractor
):
    source = _create_source(store)
    service = build_candidate_service(store, ExtractionService(fake))
    saved = service.extract_for_source(source.id)
    assert len(saved.created) == 1

    fake.error = ExtractionTransientError("timeout", kind="timeout")
    with pytest.raises(ExtractionTransientError):
        service.extract_for_source(source.id)

    remaining = store.learning_item_candidates.list_by_source(source.id)
    assert [row.id for row in remaining] == [saved.created[0].candidate.id]
    assert remaining[0].status == "candidate"


def test_accept_creates_learning_item_with_source_ref_and_evidence(
    store: TutorSqliteStore, service: CandidateService
):
    source = _create_source(store)
    created = service.extract_for_source(source.id).created[0]
    result = service.accept(created.candidate.id)

    assert result.merged is False
    assert result.candidate.candidate.status == "accepted"
    item = result.item
    assert item.item_type == "expression"
    assert item.canonical_form == "se rendre compte"
    assert item.meaning_ja == "〜に気づく"
    assert len(item.source_refs) == 1
    ref = item.source_refs[0]
    assert ref.source_document_id == source.id
    assert ref.confidence == 0.9
    assert ref.evidence_span is not None
    assert source.content[ref.evidence_span.start : ref.evidence_span.end] == (
        "rendu compte"
    )
    assert store.learning_items.get(item.id) == item
    assert store.learning_item_candidates.get(created.candidate.id).status == "accepted"


def test_accept_merges_into_existing_learning_item(
    store: TutorSqliteStore, service: CandidateService
):
    source = _create_source(store)
    existing = store.learning_items.create(
        LearningItem(
            item_type="expression",
            canonical_form="SE RENDRE COMPTE",
            meaning_ja="気づく（手入力）",
        )
    )
    created = service.extract_for_source(source.id).created[0]
    result = service.accept(created.candidate.id)

    assert result.merged is True
    assert result.item.id == existing.id
    assert len(store.learning_items.list()) == 1
    refs = result.item.source_refs
    assert [ref.source_document_id for ref in refs] == [source.id]
    assert result.item.meaning_ja == "気づく（手入力）"


def test_accept_does_not_add_duplicate_source_ref(
    store: TutorSqliteStore, service: CandidateService
):
    source = _create_source(store)
    store.learning_items.create(
        LearningItem(
            item_type="expression",
            canonical_form="se rendre compte",
            meaning_ja="〜に気づく",
            source_refs=[
                SourceRef(
                    source_document_id=source.id,
                    evidence_span=EvidenceSpan(start=6, end=18),
                )
            ],
        )
    )
    created = service.extract_for_source(source.id).created[0]
    result = service.accept(created.candidate.id)

    assert result.merged is True
    assert len(result.item.source_refs) == 1
    assert result.item.source_refs[0].evidence_span is not None
    assert result.item.source_refs[0].evidence_span.start == 6


def test_reaccept_is_idempotent(store: TutorSqliteStore, service: CandidateService):
    source = _create_source(store)
    created = service.extract_for_source(source.id).created[0]
    first = service.accept(created.candidate.id)
    second = service.accept(created.candidate.id)

    assert second.item.id == first.item.id
    assert second.merged is True
    assert len(store.learning_items.list()) == 1
    assert store.learning_item_candidates.get(created.candidate.id).status == "accepted"


def test_reject_does_not_create_learning_item(
    store: TutorSqliteStore, service: CandidateService
):
    source = _create_source(store)
    created = service.extract_for_source(source.id).created[0]
    view = service.reject(created.candidate.id)

    assert view.candidate.status == "rejected"
    assert store.learning_items.list() == []
    assert store.learning_item_candidates.get(created.candidate.id).status == "rejected"


def test_rereject_is_idempotent(store: TutorSqliteStore, service: CandidateService):
    source = _create_source(store)
    created = service.extract_for_source(source.id).created[0]
    first = service.reject(created.candidate.id)
    second = service.reject(created.candidate.id)
    assert second.candidate.id == first.candidate.id
    assert second.candidate.status == "rejected"


def test_accept_rejected_is_forbidden(
    store: TutorSqliteStore, service: CandidateService
):
    source = _create_source(store)
    created = service.extract_for_source(source.id).created[0]
    service.reject(created.candidate.id)
    with pytest.raises(InvalidCandidateTransitionError, match="rejected"):
        service.accept(created.candidate.id)
    assert store.learning_items.list() == []
    assert store.learning_item_candidates.get(created.candidate.id).status == "rejected"


def test_reject_accepted_is_forbidden(
    store: TutorSqliteStore, service: CandidateService
):
    source = _create_source(store)
    created = service.extract_for_source(source.id).created[0]
    service.accept(created.candidate.id)
    with pytest.raises(InvalidCandidateTransitionError, match="accepted"):
        service.reject(created.candidate.id)
    assert store.learning_item_candidates.get(created.candidate.id).status == "accepted"


def test_accept_invalid_evidence_is_rejected(
    store: TutorSqliteStore, service: CandidateService
):
    source = _create_source(store)
    invalid = store.learning_item_candidates.create(
        LearningItemCandidate(
            source_document_id=source.id,
            item_type="vocabulary",
            canonical_form="ghost",
            meaning_ja="幽霊",
            evidence_span=EvidenceSpan(start=0, end=len(CONTENT) + 10),
            extraction_version="extract-v1",
        )
    )
    with pytest.raises(TutorInvalidCandidateError):
        service.accept(invalid.id)
    assert store.learning_items.list() == []
    assert store.learning_item_candidates.get(invalid.id).status == "candidate"


def test_accept_missing_candidate_raises_not_found(service: CandidateService):
    with pytest.raises(TutorNotFoundError, match="LearningItemCandidate"):
        service.accept("missing-candidate")


def test_item_write_failure_leaves_candidate_pending(
    store: TutorSqliteStore,
    service: CandidateService,
    monkeypatch: pytest.MonkeyPatch,
):
    source = _create_source(store)
    created = service.extract_for_source(source.id).created[0]
    original_add = Session.add

    def fail_item_add(self: Session, instance: object, _warn: bool = True) -> None:
        if isinstance(instance, LearningItemRow):
            raise RuntimeError("item write failed")
        original_add(self, instance, _warn=_warn)

    monkeypatch.setattr(Session, "add", fail_item_add)

    with pytest.raises(RuntimeError, match="item write failed"):
        service.accept(created.candidate.id)

    assert store.learning_items.list() == []
    remaining = store.learning_item_candidates.get(created.candidate.id)
    assert remaining is not None
    assert remaining.status == "candidate"


def test_extract_config_error_does_not_save(
    store: TutorSqliteStore, fake: FakeLearningItemExtractor
):
    source = _create_source(store)
    fake.error = ExtractionConfigError(
        "OPENAI_API_KEY が設定されていない", kind="missing_api_key"
    )
    service = build_candidate_service(store, ExtractionService(fake))
    with pytest.raises(ExtractionConfigError):
        service.extract_for_source(source.id)
    assert store.learning_item_candidates.list_by_source(source.id) == []
