"""Tutor 最小 API（Issue #112）。

business rule は TutorService に任せ、このモジュールは request/response
schema と HTTP status 変換だけを持つ。
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import get_tutor_service
from app.domain.tutor import (
    AnswerOutcome,
    CefrLevel,
    ExerciseType,
    LearnerState,
    LearningEvent,
    LearningItem,
    LearningItemStatus,
    LearningItemType,
    ReviewSchedule,
    SourceDocument,
    SourceRef,
    UtcDatetime,
)
from app.services.exceptions import (
    InvalidSourceRefError,
    TutorConflictError,
    TutorNotFoundError,
    TutorServiceError,
)
from app.services.tutor_service import TutorService

router = APIRouter(prefix="/api/tutor", tags=["tutor"])

TutorServiceDep = Annotated[TutorService, Depends(get_tutor_service)]


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


def _to_http(exc: TutorServiceError) -> HTTPException:
    if isinstance(exc, TutorNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, TutorConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, InvalidSourceRefError):
        return HTTPException(status_code=422, detail=str(exc))
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


@router.get("/sources/{source_id}", response_model=SourceDocument)
def get_source(source_id: str, service: TutorServiceDep) -> SourceDocument:
    try:
        return service.get_source(source_id)
    except TutorServiceError as exc:
        raise _to_http(exc) from exc


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
