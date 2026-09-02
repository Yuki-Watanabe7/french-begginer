"""Tutor 最小 API（Issue #112）と Source 一覧（Issue #121）、
Candidate 抽出・採否（Issue #134）、Exercise 取得・回答判定（Issue #149）、
Practice Session 組み立て（Issue #150）、due review queue（Issue #163）、
Review Practice Session（Issue #164）。

business rule は TutorService / CandidateService / ExerciseService /
PracticeSessionService / ReviewSessionService に任せ、このモジュールは
request/response schema と HTTP status 変換だけを持つ。
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.deps import (
    get_candidate_service,
    get_exercise_service,
    get_practice_session_service,
    get_review_session_service,
    get_tutor_service,
)
from app.domain.exercise import PublicExercise, to_public_exercise
from app.domain.practice_session import (
    DEFAULT_QUESTION_COUNT,
    MAX_QUESTION_COUNT,
    MIN_QUESTION_COUNT,
    SkippedPracticeItem,
)
from app.domain.review_queue import (
    DEFAULT_QUEUE_LIMIT,
    MAX_QUEUE_LIMIT,
    MIN_QUEUE_LIMIT,
    ReviewQueue,
)
from app.domain.review_session import SkippedReviewEntry
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
    InvalidPracticeFilterError,
    InvalidReviewSessionError,
    InvalidSourceRefError,
    TutorConflictError,
    TutorInconsistentStateError,
    TutorInvalidCandidateError,
    TutorMalformedAnswerError,
    TutorNotFoundError,
    TutorServiceError,
    TutorUnsupportedExerciseError,
)
from app.services.exercise_service import ExerciseService
from app.services.practice_session_service import PracticeSessionService
from app.services.review_session_service import ReviewSessionService
from app.services.tutor_service import TutorService

router = APIRouter(prefix="/api/tutor", tags=["tutor"])

TutorServiceDep = Annotated[TutorService, Depends(get_tutor_service)]
CandidateServiceDep = Annotated[CandidateService, Depends(get_candidate_service)]
ExerciseServiceDep = Annotated[ExerciseService, Depends(get_exercise_service)]
PracticeSessionServiceDep = Annotated[
    PracticeSessionService, Depends(get_practice_session_service)
]
ReviewSessionServiceDep = Annotated[
    ReviewSessionService, Depends(get_review_session_service)
]

SOURCE_LIST_LIMIT_DEFAULT = 50
SOURCE_LIST_LIMIT_MAX = 100
SOURCE_CONTENT_PREVIEW_MAX_CHARS = 120
ITEM_LIST_LIMIT_DEFAULT = 50
ITEM_LIST_LIMIT_MAX = 100


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


class SubmitExerciseAnswerRequest(BaseModel):
    """Exercise への回答。正解は含めない。occurred_at 未指定時はサーバー時刻。"""

    model_config = ConfigDict(extra="forbid")

    answer: str | list[str]
    occurred_at: UtcDatetime | None = None
    response_time_ms: int | None = Field(default=None, ge=0)
    id: str | None = Field(default=None, min_length=1)


class ExerciseAnswerResponse(BaseModel):
    """回答後 feedback。correct_answer は回答後のみ返す。"""

    correct: bool
    correct_answer: str
    given: str | list[str]
    explanation_ja: str | None = None
    source_context: str | None = None
    event: LearningEvent
    learner_state: LearnerState
    review_schedule: ReviewSchedule


class LearningItemDetailResponse(BaseModel):
    item: LearningItem
    learner_state: LearnerState | None = None
    review_schedule: ReviewSchedule | None = None
    review_schedules: list[ReviewSchedule] = Field(default_factory=list)


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


class CreatePracticeSessionRequest(BaseModel):
    """Practice Session の入力。source_id と item_ids は同時指定できない。"""

    model_config = ConfigDict(extra="forbid")

    source_id: str | None = Field(default=None, min_length=1)
    item_ids: list[str] | None = None
    question_count: int = Field(
        default=DEFAULT_QUESTION_COUNT,
        ge=MIN_QUESTION_COUNT,
        le=MAX_QUESTION_COUNT,
    )
    seed: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _check_filters(self) -> "CreatePracticeSessionRequest":
        if self.source_id is not None and self.item_ids is not None:
            raise ValueError("source_id と item_ids は同時に指定できない")
        if self.item_ids is not None:
            if any(not item_id.strip() for item_id in self.item_ids):
                raise ValueError("item_ids に空文字は使えない")
        return self


class PracticeSessionResponse(BaseModel):
    """組み立て済み Session。正解は含めない。永続化しない。"""

    session_id: str
    exercises: list[PublicExercise]
    skipped_items: list[SkippedPracticeItem]
    requested_count: int
    generated_count: int


class CreateReviewSessionRequest(BaseModel):
    """Review Practice Session の入力。due queue が source of truth。"""

    model_config = ConfigDict(extra="forbid")

    question_count: int = Field(
        default=DEFAULT_QUESTION_COUNT,
        ge=MIN_QUESTION_COUNT,
        le=MAX_QUESTION_COUNT,
    )
    seed: str | None = Field(default=None, min_length=1)


class ReviewPracticeSessionResponse(BaseModel):
    """due queue から組み立てた Session。正解は含めない。永続化しない。"""

    session_id: str
    exercises: list[PublicExercise]
    skipped_entries: list[SkippedReviewEntry]
    requested_count: int
    generated_count: int


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
    if isinstance(exc, TutorUnsupportedExerciseError):
        return HTTPException(
            status_code=422,
            detail={"skip_reason": exc.skip_reason, "detail": exc.detail},
        )
    if isinstance(exc, TutorMalformedAnswerError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, InvalidPracticeFilterError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, InvalidReviewSessionError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, TutorInconsistentStateError):
        return HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        )
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
        review_schedules=detail.review_schedules,
    )


@router.get("/items", response_model=list[LearningItem])
def list_items(
    service: TutorServiceDep,
    limit: int = Query(
        default=ITEM_LIST_LIMIT_DEFAULT,
        ge=1,
        le=ITEM_LIST_LIMIT_MAX,
    ),
) -> list[LearningItem]:
    """active な LearningItem を created_at 昇順で返す。管理検索はしない。"""
    return service.list_items(limit=limit)


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
        review_schedules=detail.review_schedules,
    )


@router.get(
    "/items/{item_id}/exercises/{exercise_type}",
    response_model=PublicExercise,
)
def get_item_exercise(
    item_id: str,
    exercise_type: ExerciseType,
    service: ExerciseServiceDep,
) -> PublicExercise:
    try:
        generated = service.get_exercise(item_id, exercise_type)
    except TutorServiceError as exc:
        raise _to_http(exc) from exc
    return to_public_exercise(generated.spec)


@router.post(
    "/items/{item_id}/exercises/{exercise_type}/answer",
    response_model=ExerciseAnswerResponse,
    status_code=status.HTTP_201_CREATED,
)
def submit_item_exercise_answer(
    item_id: str,
    exercise_type: ExerciseType,
    req: SubmitExerciseAnswerRequest,
    service: ExerciseServiceDep,
) -> ExerciseAnswerResponse:
    try:
        record = service.submit_answer(
            item_id,
            exercise_type,
            req.answer,
            event_id=req.id,
            occurred_at=req.occurred_at,
            response_time_ms=req.response_time_ms,
        )
    except TutorServiceError as exc:
        raise _to_http(exc) from exc
    given = record.evaluation.given
    return ExerciseAnswerResponse(
        correct=record.evaluation.correct,
        correct_answer=record.evaluation.correct_answer,
        given=list(given) if isinstance(given, tuple) else given,
        explanation_ja=record.explanation_ja,
        source_context=record.source_context,
        event=record.event,
        learner_state=record.learner_state,
        review_schedule=record.review_schedule,
    )


@router.post("/practice/sessions", response_model=PracticeSessionResponse)
def create_practice_session(
    req: CreatePracticeSessionRequest,
    service: PracticeSessionServiceDep,
) -> PracticeSessionResponse:
    """active LearningItem から Practice Session を組み立てる。永続化しない。"""
    try:
        session = service.create_session(
            source_id=req.source_id,
            item_ids=req.item_ids,
            question_count=req.question_count,
            seed=req.seed,
        )
    except TutorServiceError as exc:
        raise _to_http(exc) from exc
    return PracticeSessionResponse(
        session_id=session.session_id,
        exercises=list(session.to_public_exercises()),
        skipped_items=list(session.skipped_items),
        requested_count=session.requested_count,
        generated_count=session.generated_count,
    )


@router.post("/review/sessions", response_model=ReviewPracticeSessionResponse)
def create_review_session(
    req: CreateReviewSessionRequest,
    service: ReviewSessionServiceDep,
) -> ReviewPracticeSessionResponse:
    """due review queue から Review Practice Session を組み立てる。永続化しない。"""
    try:
        session = service.create_session(
            question_count=req.question_count,
            seed=req.seed,
        )
    except TutorServiceError as exc:
        raise _to_http(exc) from exc
    return ReviewPracticeSessionResponse(
        session_id=session.session_id,
        exercises=list(session.to_public_exercises()),
        skipped_entries=list(session.skipped_entries),
        requested_count=session.requested_count,
        generated_count=session.generated_count,
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


@router.get("/reviews/queue", response_model=ReviewQueue)
def list_review_queue(
    service: TutorServiceDep,
    limit: int = Query(
        default=DEFAULT_QUEUE_LIMIT,
        ge=MIN_QUEUE_LIMIT,
        le=MAX_QUEUE_LIMIT,
    ),
) -> ReviewQueue:
    """direction-aware な due review queue。任意時刻の query は持たない。"""
    try:
        return service.list_review_queue(limit=limit)
    except TutorServiceError as exc:
        raise _to_http(exc) from exc
