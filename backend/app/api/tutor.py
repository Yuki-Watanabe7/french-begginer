"""Tutor 最小 API（Issue #112）と Source 一覧（Issue #121）、
Candidate 抽出・採否（Issue #134）。

business rule は TutorService / CandidateService に任せ、このモジュールは
request/response schema と HTTP status 変換だけを持つ。
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import get_candidate_service, get_tutor_service
from app.domain.tutor import (
    AnswerOutcome,
    CandidateStatus,
    CefrLevel,
    EvidenceSpan,
    ExerciseType,
    LearnerState,
    LearningEvent,
    LearningItem,
    LearningItemStatus,
    LearningItemType,
    ReviewSchedule,
    SourceDocument,
    SourceRef,
    SourceType,
    UtcDatetime,
)
from app.services.candidate_service import CandidateService, CandidateView
from app.services.exceptions import (
    ExtractionConfigError,
    ExtractionInvalidResponseError,
    ExtractionTransientError,
    InvalidCandidateTransitionError,
    InvalidSourceRefError,
    TutorConflictError,
    TutorInvalidCandidateError,
    TutorNotFoundError,
    TutorServiceError,
)
from app.services.tutor_service import TutorService

router = APIRouter(prefix="/api/tutor", tags=["tutor"])

TutorServiceDep = Annotated[TutorService, Depends(get_tutor_service)]
CandidateServiceDep = Annotated[CandidateService, Depends(get_candidate_service)]

SOURCE_LIST_LIMIT_DEFAULT = 50
SOURCE_LIST_LIMIT_MAX = 100
SOURCE_CONTENT_PREVIEW_MAX_CHARS = 120


class CreateSourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    language: str = "fr"
    metadata: dict[str, Any] = Field(default_factory=dict)


class CreateLearningItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_type: LearningItemType
    canonical_form: str = Field(min_length=1)
    meaning_ja: str = Field(min_length=1)
    explanation_ja: str | None = None
    level: CefrLevel | None = None
    source_refs: list[SourceRef] = Field(default_factory=list)
    status: LearningItemStatus = "active"
    metadata: dict[str, Any] = Field(default_factory=dict)


class CreateReviewRequest(BaseModel):
    """occurred_at 未指定時はサーバー時刻（UTC）を使う。"""

    model_config = ConfigDict(extra="forbid")

    exercise_type: ExerciseType
    result: AnswerOutcome
    occurred_at: UtcDatetime | None = None
    response_time_ms: int | None = Field(default=None, ge=0)
    id: str | None = Field(default=None, min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LearningItemDetailResponse(BaseModel):
    item: LearningItem
    learner_state: LearnerState | None = None
    review_schedule: ReviewSchedule | None = None


class ReviewResponse(BaseModel):
    event: LearningEvent
    learner_state: LearnerState
    review_schedule: ReviewSchedule


class DueReviewResponse(BaseModel):
    item: LearningItem
    learner_state: LearnerState | None = None
    review_schedule: ReviewSchedule


class SourceSummary(BaseModel):
    """一覧用。全文は返さず、表示に必要な項目と先頭プレビューだけを持つ。"""

    id: str
    source_type: SourceType
    title: str
    language: str
    created_at: UtcDatetime
    content_preview: str


class CandidateResponse(BaseModel):
    """Frontend 向け Candidate。provider の生応答や metadata は載せない。"""

    id: str
    source_document_id: str
    item_type: LearningItemType
    canonical_form: str
    meaning_ja: str
    explanation_ja: str | None = None
    level: CefrLevel | None = None
    evidence_span: EvidenceSpan
    evidence_text: str
    confidence: float | None = None
    status: CandidateStatus
    extraction_version: str
    created_at: UtcDatetime


class ExtractCandidatesResponse(BaseModel):
    source_document_id: str
    extraction_version: str
    created: list[CandidateResponse]
    skipped: list[CandidateResponse]


class AcceptCandidateResponse(BaseModel):
    candidate: CandidateResponse
    item: LearningItem
    merged: bool


def _to_source_summary(document: SourceDocument) -> SourceSummary:
    return SourceSummary(
        id=document.id,
        source_type=document.source_type,
        title=document.title,
        language=document.language,
        created_at=document.created_at,
        content_preview=document.content[:SOURCE_CONTENT_PREVIEW_MAX_CHARS],
    )


def _to_candidate_response(view: CandidateView) -> CandidateResponse:
    candidate = view.candidate
    return CandidateResponse(
        id=candidate.id,
        source_document_id=candidate.source_document_id,
        item_type=candidate.item_type,
        canonical_form=candidate.canonical_form,
        meaning_ja=candidate.meaning_ja,
        explanation_ja=candidate.explanation_ja,
        level=candidate.level,
        evidence_span=candidate.evidence_span,
        evidence_text=view.evidence_text,
        confidence=candidate.confidence,
        status=candidate.status,
        extraction_version=candidate.extraction_version,
        created_at=candidate.created_at,
    )


def _to_http(exc: TutorServiceError) -> HTTPException:
    if isinstance(exc, TutorNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, TutorConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, InvalidCandidateTransitionError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, InvalidSourceRefError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, TutorInvalidCandidateError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, ExtractionConfigError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        )
    if isinstance(exc, ExtractionTransientError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        )
    if isinstance(exc, ExtractionInvalidResponseError):
        return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post(
    "/sources",
    response_model=SourceDocument,
    status_code=status.HTTP_201_CREATED,
)
def create_source(req: CreateSourceRequest, service: TutorServiceDep) -> SourceDocument:
    try:
        return service.create_source(
            title=req.title,
            content=req.content,
            language=req.language,
            metadata=req.metadata,
        )
    except TutorServiceError as exc:
        raise _to_http(exc) from exc


@router.get("/sources", response_model=list[SourceSummary])
def list_sources(
    service: TutorServiceDep,
    limit: int = Query(
        default=SOURCE_LIST_LIMIT_DEFAULT,
        ge=1,
        le=SOURCE_LIST_LIMIT_MAX,
    ),
) -> list[SourceSummary]:
    """保存済み Source を created_at 降順で返す。同一時刻は id 昇順。"""
    return [
        _to_source_summary(document) for document in service.list_sources(limit=limit)
    ]


@router.get("/sources/{source_id}", response_model=SourceDocument)
def get_source(source_id: str, service: TutorServiceDep) -> SourceDocument:
    try:
        return service.get_source(source_id)
    except TutorServiceError as exc:
        raise _to_http(exc) from exc


@router.post(
    "/sources/{source_id}/candidates/extract",
    response_model=ExtractCandidatesResponse,
)
def extract_candidates(
    source_id: str, service: CandidateServiceDep
) -> ExtractCandidatesResponse:
    try:
        result = service.extract_for_source(source_id)
    except TutorServiceError as exc:
        raise _to_http(exc) from exc
    return ExtractCandidatesResponse(
        source_document_id=result.source_document_id,
        extraction_version=result.extraction_version,
        created=[_to_candidate_response(view) for view in result.created],
        skipped=[_to_candidate_response(view) for view in result.skipped],
    )


@router.get(
    "/sources/{source_id}/candidates",
    response_model=list[CandidateResponse],
)
def list_candidates(
    source_id: str, service: CandidateServiceDep
) -> list[CandidateResponse]:
    try:
        views = service.list_for_source(source_id)
    except TutorServiceError as exc:
        raise _to_http(exc) from exc
    return [_to_candidate_response(view) for view in views]


@router.post(
    "/candidates/{candidate_id}/accept",
    response_model=AcceptCandidateResponse,
)
def accept_candidate(
    candidate_id: str, service: CandidateServiceDep
) -> AcceptCandidateResponse:
    try:
        result = service.accept(candidate_id)
    except TutorServiceError as exc:
        raise _to_http(exc) from exc
    return AcceptCandidateResponse(
        candidate=_to_candidate_response(result.candidate),
        item=result.item,
        merged=result.merged,
    )


@router.post(
    "/candidates/{candidate_id}/reject",
    response_model=CandidateResponse,
)
def reject_candidate(
    candidate_id: str, service: CandidateServiceDep
) -> CandidateResponse:
    try:
        view = service.reject(candidate_id)
    except TutorServiceError as exc:
        raise _to_http(exc) from exc
    return _to_candidate_response(view)


@router.post(
    "/items",
    response_model=LearningItemDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_item(
    req: CreateLearningItemRequest, service: TutorServiceDep
) -> LearningItemDetailResponse:
    try:
        item = service.create_item(
            item_type=req.item_type,
            canonical_form=req.canonical_form,
            meaning_ja=req.meaning_ja,
            explanation_ja=req.explanation_ja,
            level=req.level,
            source_refs=req.source_refs,
            status=req.status,
            metadata=req.metadata,
        )
        detail = service.get_item(item.id)
    except TutorServiceError as exc:
        raise _to_http(exc) from exc
    return LearningItemDetailResponse(
        item=detail.item,
        learner_state=detail.learner_state,
        review_schedule=detail.review_schedule,
    )


@router.get("/items/{item_id}", response_model=LearningItemDetailResponse)
def get_item(item_id: str, service: TutorServiceDep) -> LearningItemDetailResponse:
    try:
        detail = service.get_item(item_id)
    except TutorServiceError as exc:
        raise _to_http(exc) from exc
    return LearningItemDetailResponse(
        item=detail.item,
        learner_state=detail.learner_state,
        review_schedule=detail.review_schedule,
    )


@router.post(
    "/items/{item_id}/reviews",
    response_model=ReviewResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_review(
    item_id: str, req: CreateReviewRequest, service: TutorServiceDep
) -> ReviewResponse:
    try:
        record = service.record_review(
            item_id,
            exercise_type=req.exercise_type,
            result=req.result,
            occurred_at=req.occurred_at,
            response_time_ms=req.response_time_ms,
            event_id=req.id,
            metadata=req.metadata,
        )
    except TutorServiceError as exc:
        raise _to_http(exc) from exc
    return ReviewResponse(
        event=record.event,
        learner_state=record.learner_state,
        review_schedule=record.review_schedule,
    )


@router.get("/reviews/due", response_model=list[DueReviewResponse])
def list_due_reviews(service: TutorServiceDep) -> list[DueReviewResponse]:
    """現在 due の LearningItem を返す。任意時刻の query は持たない。"""
    due = service.list_due()
    return [
        DueReviewResponse(
            item=row.item,
            learner_state=row.learner_state,
            review_schedule=row.review_schedule,
        )
        for row in due
    ]
