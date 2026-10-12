"""Tutor 最小 API（Issue #112）と Source 一覧（Issue #121）、
Candidate 抽出・採否（Issue #134）、Exercise 取得・回答判定（Issue #149）、
Practice Session 組み立て（Issue #150）、due review queue（Issue #163）、
Review Practice Session（Issue #164）、今日の学習 Plan / Session（Issue #178）、
Web URL からの Source 取り込み（Issue #190）、
テキスト PDF からの Source 取り込み（Issue #191）、
YouTube transcript と SRT / VTT からの Source 取り込み（Issue #192）、
音声の文字起こしからの Source 取り込み（Issue #193）、
テキスト / Markdown と会話 JSON からの Source 取り込み（Issue #194）。

business rule は TutorService / CandidateService / ExerciseService /
PracticeSessionService / ReviewSessionService / TodayLearningService /
WebUrlIngestionService / PdfIngestionService / YoutubeIngestionService /
SubtitleIngestionService / AudioIngestionService / TextFileIngestionService /
ConversationIngestionService に任せ、このモジュールは
request/response schema と HTTP status 変換だけを持つ。
"""

from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.api.deps import (
    get_audio_ingestion_service,
    get_candidate_service,
    get_conversation_ingestion_service,
    get_exercise_service,
    get_pdf_ingestion_service,
    get_practice_session_service,
    get_review_session_service,
    get_subtitle_ingestion_service,
    get_text_file_ingestion_service,
    get_today_learning_service,
    get_tutor_service,
    get_web_url_ingestion_service,
    get_youtube_ingestion_service,
)
from app.domain.daily_learning_plan import (
    DEFAULT_MAX_NEW_COUNT,
    DEFAULT_PLAN_SIZE,
    MAX_PLAN_SIZE,
    MIN_PLAN_SIZE,
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
from app.domain.source_ingestion import (
    MAX_LOCATOR_CHARS,
    MAX_SHORT_FIELD_CHARS,
    IngestAction,
    IngestionFailureKind,
    SourceIngestionError,
)
from app.domain.today_session import (
    SkippedTodayEntry,
    TodayLearningPlanView,
    TodayPlanEntryView,
)
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
from app.ingestion.audio_errors import AudioIngestErrorCode, AudioIngestionError
from app.ingestion.conversation_errors import (
    ConversationIngestErrorCode,
    ConversationIngestionError,
)
from app.ingestion.errors import WebFetchErrorCode, WebUrlIngestionError
from app.ingestion.pdf_errors import PdfIngestErrorCode, PdfIngestionError
from app.ingestion.subtitle_errors import (
    SubtitleIngestErrorCode,
    SubtitleIngestionError,
)
from app.ingestion.text_file_errors import (
    TextFileIngestErrorCode,
    TextFileIngestionError,
)
from app.ingestion.youtube_errors import YoutubeIngestErrorCode, YoutubeIngestionError
from app.services.audio_ingestion import AudioIngestionService
from app.services.candidate_service import CandidateService, CandidateView
from app.services.conversation_ingestion import ConversationIngestionService
from app.services.exceptions import (
    ExtractionConfigError,
    ExtractionInvalidResponseError,
    ExtractionTransientError,
    InvalidCandidateTransitionError,
    InvalidPracticeFilterError,
    InvalidReviewSessionError,
    InvalidSourceRefError,
    InvalidTodayLearningError,
    TutorConflictError,
    TutorInconsistentStateError,
    TutorInvalidCandidateError,
    TutorMalformedAnswerError,
    TutorNotFoundError,
    TutorServiceError,
    TutorUnsupportedExerciseError,
)
from app.services.exercise_service import ExerciseService
from app.services.pdf_ingestion import PdfIngestionService
from app.services.practice_session_service import PracticeSessionService
from app.services.review_session_service import ReviewSessionService
from app.services.subtitle_ingestion import SubtitleIngestionService
from app.services.text_file_ingestion import TextFileIngestionService
from app.services.today_learning_service import TodayLearningService
from app.services.tutor_service import TutorService
from app.services.web_url_ingestion import WebUrlIngestionService
from app.services.youtube_ingestion import YoutubeIngestionService

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
TodayLearningServiceDep = Annotated[
    TodayLearningService, Depends(get_today_learning_service)
]
WebUrlIngestionServiceDep = Annotated[
    WebUrlIngestionService, Depends(get_web_url_ingestion_service)
]
PdfIngestionServiceDep = Annotated[
    PdfIngestionService, Depends(get_pdf_ingestion_service)
]
YoutubeIngestionServiceDep = Annotated[
    YoutubeIngestionService, Depends(get_youtube_ingestion_service)
]
SubtitleIngestionServiceDep = Annotated[
    SubtitleIngestionService, Depends(get_subtitle_ingestion_service)
]
AudioIngestionServiceDep = Annotated[
    AudioIngestionService, Depends(get_audio_ingestion_service)
]
TextFileIngestionServiceDep = Annotated[
    TextFileIngestionService, Depends(get_text_file_ingestion_service)
]
ConversationIngestionServiceDep = Annotated[
    ConversationIngestionService, Depends(get_conversation_ingestion_service)
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


class IngestUrlRequest(BaseModel):
    """Web URL の取り込み。title と note は省略できる。"""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=MAX_LOCATOR_CHARS)
    title: str | None = Field(
        default=None, min_length=1, max_length=MAX_SHORT_FIELD_CHARS
    )
    note: str | None = Field(default=None, min_length=1, max_length=2_000)
    language: str = Field(default="fr", min_length=1, max_length=32)

    @field_validator("url", "title", "note", "language")
    @classmethod
    def _reject_blank(cls, value: str | None) -> str | None:
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                raise ValueError("空文字は指定できない")
            return stripped
        return value


class IngestYoutubeRequest(BaseModel):
    """YouTube の URL または 11 文字の video ID。playlist は受け取らない。"""

    model_config = ConfigDict(extra="forbid")

    video: str = Field(min_length=1, max_length=MAX_LOCATOR_CHARS)
    title: str | None = Field(
        default=None, min_length=1, max_length=MAX_SHORT_FIELD_CHARS
    )
    note: str | None = Field(default=None, min_length=1, max_length=2_000)
    language: str = Field(default="fr", min_length=1, max_length=32)

    @field_validator("video", "title", "note", "language")
    @classmethod
    def _reject_blank(cls, value: str | None) -> str | None:
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                raise ValueError("空文字は指定できない")
            return stripped
        return value


class IngestUrlResponse(BaseModel):
    """保存した、または再利用した SourceDocument と、再投入の扱い。

    Web URL、PDF、YouTube transcript、字幕ファイルで同じ形を返す。
    """

    action: IngestAction
    created: bool
    source: SourceDocument


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


class CreateTodaySessionRequest(BaseModel):
    """今日の学習 Session の入力。plan は予約保持せず、開始時に再計算する。"""

    model_config = ConfigDict(extra="forbid")

    question_count: int = Field(
        default=DEFAULT_PLAN_SIZE,
        ge=MIN_PLAN_SIZE,
        le=MAX_PLAN_SIZE,
    )
    max_new_count: int = Field(
        default=DEFAULT_MAX_NEW_COUNT,
        ge=0,
        le=MAX_PLAN_SIZE,
    )
    seed: str | None = Field(default=None, min_length=1)


class TodayLearningSessionResponse(BaseModel):
    """Plan から組み立てた今日の学習 Session。正解は含めない。永続化しない。"""

    session_id: str
    exercises: list[PublicExercise]
    entries: list[TodayPlanEntryView]
    skipped_entries: list[SkippedTodayEntry]
    requested_count: int
    generated_count: int
    review_count: int
    new_count: int
    deferred_due_count: int
    explanation_summary: str
    policy_version: str
    generated_at: UtcDatetime
    summary_reason_codes: list[str]


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
    if isinstance(exc, InvalidTodayLearningError):
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


_INGESTION_KIND_HTTP: dict[IngestionFailureKind, tuple[str, int]] = {
    IngestionFailureKind.validation: ("invalid_url", status.HTTP_400_BAD_REQUEST),
    IngestionFailureKind.unsupported_media: (
        "unsupported_content_type",
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    ),
    IngestionFailureKind.input_too_large: (
        "response_too_large",
        status.HTTP_413_CONTENT_TOO_LARGE,
    ),
    IngestionFailureKind.timeout: ("fetch_timeout", status.HTTP_504_GATEWAY_TIMEOUT),
    IngestionFailureKind.provider: ("upstream_error", status.HTTP_502_BAD_GATEWAY),
    IngestionFailureKind.not_implemented: (
        "not_implemented",
        status.HTTP_501_NOT_IMPLEMENTED,
    ),
}

_PDF_CODE_HTTP: dict[PdfIngestErrorCode, int] = {
    PdfIngestErrorCode.invalid_pdf: status.HTTP_400_BAD_REQUEST,
    PdfIngestErrorCode.malformed_pdf: status.HTTP_400_BAD_REQUEST,
    PdfIngestErrorCode.encrypted_pdf: status.HTTP_422_UNPROCESSABLE_CONTENT,
    PdfIngestErrorCode.unsupported_media: status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    PdfIngestErrorCode.file_too_large: status.HTTP_413_CONTENT_TOO_LARGE,
    PdfIngestErrorCode.too_many_pages: status.HTTP_413_CONTENT_TOO_LARGE,
    PdfIngestErrorCode.text_too_large: status.HTTP_413_CONTENT_TOO_LARGE,
    PdfIngestErrorCode.ocr_required: status.HTTP_422_UNPROCESSABLE_CONTENT,
    PdfIngestErrorCode.parser_timeout: status.HTTP_504_GATEWAY_TIMEOUT,
}

_YOUTUBE_CODE_HTTP: dict[YoutubeIngestErrorCode, int] = {
    YoutubeIngestErrorCode.invalid_video: status.HTTP_400_BAD_REQUEST,
    YoutubeIngestErrorCode.transcript_unavailable: (
        status.HTTP_422_UNPROCESSABLE_CONTENT
    ),
    YoutubeIngestErrorCode.transcript_disabled: status.HTTP_422_UNPROCESSABLE_CONTENT,
    YoutubeIngestErrorCode.video_unavailable: status.HTTP_422_UNPROCESSABLE_CONTENT,
    YoutubeIngestErrorCode.malformed_transcript: status.HTTP_422_UNPROCESSABLE_CONTENT,
    YoutubeIngestErrorCode.transcript_empty: status.HTTP_422_UNPROCESSABLE_CONTENT,
    YoutubeIngestErrorCode.text_too_large: status.HTTP_413_CONTENT_TOO_LARGE,
    YoutubeIngestErrorCode.transcript_timeout: status.HTTP_504_GATEWAY_TIMEOUT,
    YoutubeIngestErrorCode.transcript_provider_error: status.HTTP_502_BAD_GATEWAY,
}

_AUDIO_CODE_HTTP: dict[AudioIngestErrorCode, int] = {
    AudioIngestErrorCode.invalid_audio: status.HTTP_400_BAD_REQUEST,
    AudioIngestErrorCode.malformed_audio: status.HTTP_400_BAD_REQUEST,
    AudioIngestErrorCode.unsupported_media: status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    AudioIngestErrorCode.file_too_large: status.HTTP_413_CONTENT_TOO_LARGE,
    AudioIngestErrorCode.audio_too_long: status.HTTP_413_CONTENT_TOO_LARGE,
    AudioIngestErrorCode.text_too_large: status.HTTP_413_CONTENT_TOO_LARGE,
    AudioIngestErrorCode.transcript_empty: status.HTTP_422_UNPROCESSABLE_CONTENT,
    AudioIngestErrorCode.invalid_transcript: status.HTTP_422_UNPROCESSABLE_CONTENT,
    AudioIngestErrorCode.translated_transcript: status.HTTP_422_UNPROCESSABLE_CONTENT,
    AudioIngestErrorCode.transcription_not_configured: (
        status.HTTP_503_SERVICE_UNAVAILABLE
    ),
    AudioIngestErrorCode.transcription_timeout: status.HTTP_504_GATEWAY_TIMEOUT,
    AudioIngestErrorCode.transcription_provider_error: status.HTTP_502_BAD_GATEWAY,
}

_SUBTITLE_CODE_HTTP: dict[SubtitleIngestErrorCode, int] = {
    SubtitleIngestErrorCode.invalid_subtitle: status.HTTP_400_BAD_REQUEST,
    SubtitleIngestErrorCode.malformed_subtitle: status.HTTP_400_BAD_REQUEST,
    SubtitleIngestErrorCode.unsupported_media: status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    SubtitleIngestErrorCode.file_too_large: status.HTTP_413_CONTENT_TOO_LARGE,
    SubtitleIngestErrorCode.text_too_large: status.HTTP_413_CONTENT_TOO_LARGE,
    SubtitleIngestErrorCode.subtitle_empty: status.HTTP_422_UNPROCESSABLE_CONTENT,
}

_TEXT_FILE_CODE_HTTP: dict[TextFileIngestErrorCode, int] = {
    TextFileIngestErrorCode.invalid_text_file: status.HTTP_400_BAD_REQUEST,
    TextFileIngestErrorCode.malformed_text: status.HTTP_400_BAD_REQUEST,
    TextFileIngestErrorCode.unsupported_media: status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    TextFileIngestErrorCode.file_too_large: status.HTTP_413_CONTENT_TOO_LARGE,
    TextFileIngestErrorCode.text_too_large: status.HTTP_413_CONTENT_TOO_LARGE,
    TextFileIngestErrorCode.text_empty: status.HTTP_422_UNPROCESSABLE_CONTENT,
}

_CONVERSATION_CODE_HTTP: dict[ConversationIngestErrorCode, int] = {
    ConversationIngestErrorCode.invalid_conversation: status.HTTP_400_BAD_REQUEST,
    ConversationIngestErrorCode.malformed_conversation: status.HTTP_400_BAD_REQUEST,
    ConversationIngestErrorCode.unsupported_media: (
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    ),
    ConversationIngestErrorCode.file_too_large: status.HTTP_413_CONTENT_TOO_LARGE,
    ConversationIngestErrorCode.text_too_large: status.HTTP_413_CONTENT_TOO_LARGE,
    ConversationIngestErrorCode.conversation_empty: (
        status.HTTP_422_UNPROCESSABLE_CONTENT
    ),
}

_WEB_URL_CODE_HTTP: dict[WebFetchErrorCode, int] = {
    WebFetchErrorCode.invalid_url: status.HTTP_400_BAD_REQUEST,
    WebFetchErrorCode.blocked_url: status.HTTP_400_BAD_REQUEST,
    WebFetchErrorCode.fetch_timeout: status.HTTP_504_GATEWAY_TIMEOUT,
    WebFetchErrorCode.unsupported_content_type: status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    WebFetchErrorCode.response_too_large: status.HTTP_413_CONTENT_TOO_LARGE,
    WebFetchErrorCode.extraction_empty: status.HTTP_422_UNPROCESSABLE_CONTENT,
    WebFetchErrorCode.upstream_error: status.HTTP_502_BAD_GATEWAY,
    WebFetchErrorCode.too_many_redirects: status.HTTP_502_BAD_GATEWAY,
}


def _ingestion_http(exc: SourceIngestionError) -> HTTPException:
    """取得失敗を、内部 IP や応答本文を足さずに利用者向けコードへ分ける。"""

    if isinstance(exc, WebUrlIngestionError):
        detail: dict[str, object] = {"code": exc.code.value, "message": str(exc)}
        if exc.upstream_status is not None:
            detail["upstream_status"] = exc.upstream_status
        return HTTPException(status_code=_WEB_URL_CODE_HTTP[exc.code], detail=detail)
    if isinstance(exc, PdfIngestionError):
        return HTTPException(
            status_code=_PDF_CODE_HTTP[exc.code],
            detail={"code": exc.code.value, "message": str(exc)},
        )
    if isinstance(exc, YoutubeIngestionError):
        detail = {"code": exc.code.value, "message": str(exc)}
        if exc.available_languages:
            detail["available_languages"] = list(exc.available_languages)
        return HTTPException(status_code=_YOUTUBE_CODE_HTTP[exc.code], detail=detail)
    if isinstance(exc, SubtitleIngestionError):
        return HTTPException(
            status_code=_SUBTITLE_CODE_HTTP[exc.code],
            detail={"code": exc.code.value, "message": str(exc)},
        )
    if isinstance(exc, AudioIngestionError):
        return HTTPException(
            status_code=_AUDIO_CODE_HTTP[exc.code],
            detail={"code": exc.code.value, "message": str(exc)},
        )
    if isinstance(exc, TextFileIngestionError):
        return HTTPException(
            status_code=_TEXT_FILE_CODE_HTTP[exc.code],
            detail={"code": exc.code.value, "message": str(exc)},
        )
    if isinstance(exc, ConversationIngestionError):
        return HTTPException(
            status_code=_CONVERSATION_CODE_HTTP[exc.code],
            detail={"code": exc.code.value, "message": str(exc)},
        )
    code, http_status = _INGESTION_KIND_HTTP[exc.kind]
    return HTTPException(
        status_code=http_status, detail={"code": code, "message": str(exc)}
    )


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


@router.post(
    "/sources/ingest/url",
    response_model=IngestUrlResponse,
    responses={
        200: {"description": "同じ URL と本文の再取り込み。既存 Source を返す"},
        201: {"description": "新しい Source、または本文が変わった版を追加する"},
        400: {"description": "invalid_url または blocked_url"},
        413: {"description": "response_too_large"},
        415: {"description": "unsupported_content_type"},
        422: {"description": "extraction_empty"},
        502: {"description": "upstream_error または too_many_redirects"},
        504: {"description": "fetch_timeout"},
    },
)
def ingest_url_source(
    req: IngestUrlRequest,
    service: WebUrlIngestionServiceDep,
    response: Response,
) -> IngestUrlResponse:
    """URL の本文を SourceDocument にする。既存の本文は上書きしない。"""

    try:
        committed = service.ingest_url(
            url=req.url,
            title=req.title,
            note=req.note,
            language=req.language,
        )
    except SourceIngestionError as exc:
        raise _ingestion_http(exc) from exc
    response.status_code = (
        status.HTTP_201_CREATED if committed.created else status.HTTP_200_OK
    )
    return IngestUrlResponse(
        action=committed.action,
        created=committed.created,
        source=committed.document,
    )


@router.post(
    "/sources/ingest/pdf",
    response_model=IngestUrlResponse,
    responses={
        200: {"description": "同じ PDF と本文の再取り込み。既存 Source を返す"},
        201: {"description": "新しい Source、または本文が変わった版を追加する"},
        400: {"description": "invalid_pdf または malformed_pdf"},
        413: {"description": "file_too_large、too_many_pages、または text_too_large"},
        415: {"description": "unsupported_media"},
        422: {"description": "encrypted_pdf または ocr_required"},
        504: {"description": "parser_timeout"},
    },
)
def ingest_pdf_source(
    service: PdfIngestionServiceDep,
    response: Response,
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form()] = None,
    note: Annotated[str | None, Form()] = None,
    language: Annotated[str, Form()] = "fr",
) -> IngestUrlResponse:
    """テキスト PDF を SourceDocument にする。画像 PDF は OCR せず拒否する。"""

    try:
        committed = service.ingest_pdf(
            source=file.file,
            filename=file.filename,
            declared_media_type=file.content_type,
            title=title,
            note=note,
            language=language,
        )
    except SourceIngestionError as exc:
        raise _ingestion_http(exc) from exc
    response.status_code = (
        status.HTTP_201_CREATED if committed.created else status.HTTP_200_OK
    )
    return IngestUrlResponse(
        action=committed.action,
        created=committed.created,
        source=committed.document,
    )


@router.post(
    "/sources/ingest/youtube",
    response_model=IngestUrlResponse,
    responses={
        200: {"description": "同じ動画と字幕本文の再取り込み。既存 Source を返す"},
        201: {"description": "新しい Source、または字幕本文が変わった版を追加する"},
        400: {"description": "invalid_video"},
        413: {"description": "text_too_large"},
        422: {
            "description": (
                "transcript_unavailable、transcript_disabled、video_unavailable、"
                "malformed_transcript、または transcript_empty"
            )
        },
        502: {"description": "transcript_provider_error"},
        504: {"description": "transcript_timeout"},
    },
)
def ingest_youtube_source(
    req: IngestYoutubeRequest,
    service: YoutubeIngestionServiceDep,
    response: Response,
) -> IngestUrlResponse:
    """公開字幕を SourceDocument にする。動画の音声は取得しない。"""

    try:
        committed = service.ingest_youtube(
            video=req.video,
            title=req.title,
            note=req.note,
            language=req.language,
        )
    except SourceIngestionError as exc:
        raise _ingestion_http(exc) from exc
    response.status_code = (
        status.HTTP_201_CREATED if committed.created else status.HTTP_200_OK
    )
    return IngestUrlResponse(
        action=committed.action,
        created=committed.created,
        source=committed.document,
    )


@router.post(
    "/sources/ingest/subtitle",
    response_model=IngestUrlResponse,
    responses={
        200: {"description": "同じ字幕ファイルと本文の再取り込み。既存 Source を返す"},
        201: {"description": "新しい Source、または本文が変わった版を追加する"},
        400: {"description": "invalid_subtitle または malformed_subtitle"},
        413: {"description": "file_too_large または text_too_large"},
        415: {"description": "unsupported_media"},
        422: {"description": "subtitle_empty"},
    },
)
def ingest_subtitle_source(
    service: SubtitleIngestionServiceDep,
    response: Response,
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form()] = None,
    note: Annotated[str | None, Form()] = None,
    language: Annotated[str, Form()] = "fr",
) -> IngestUrlResponse:
    """SRT / VTT を時刻付き SourceDocument にする。"""

    try:
        committed = service.ingest_subtitle(
            source=file.file,
            filename=file.filename,
            declared_media_type=file.content_type,
            title=title,
            note=note,
            language=language,
        )
    except SourceIngestionError as exc:
        raise _ingestion_http(exc) from exc
    response.status_code = (
        status.HTTP_201_CREATED if committed.created else status.HTTP_200_OK
    )
    return IngestUrlResponse(
        action=committed.action,
        created=committed.created,
        source=committed.document,
    )


@router.post(
    "/sources/ingest/audio",
    response_model=IngestUrlResponse,
    responses={
        200: {"description": "同じ音声と本文の再取り込み。既存 Source を返す"},
        201: {"description": "新しい Source、または本文が変わった版を追加する"},
        400: {"description": "invalid_audio または malformed_audio"},
        413: {"description": "file_too_large、audio_too_long、または text_too_large"},
        415: {"description": "unsupported_media"},
        422: {
            "description": (
                "transcript_empty、invalid_transcript、または translated_transcript"
            )
        },
        502: {"description": "transcription_provider_error"},
        503: {"description": "transcription_not_configured"},
        504: {"description": "transcription_timeout"},
    },
)
def ingest_audio_source(
    service: AudioIngestionServiceDep,
    response: Response,
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form()] = None,
    note: Annotated[str | None, Form()] = None,
    language: Annotated[str, Form()] = "fr",
) -> IngestUrlResponse:
    """音声を文字起こしして SourceDocument にする。raw audio は保存しない。"""

    try:
        committed = service.ingest_audio(
            source=file.file,
            filename=file.filename,
            declared_media_type=file.content_type,
            title=title,
            note=note,
            language=language,
        )
    except SourceIngestionError as exc:
        raise _ingestion_http(exc) from exc
    response.status_code = (
        status.HTTP_201_CREATED if committed.created else status.HTTP_200_OK
    )
    return IngestUrlResponse(
        action=committed.action,
        created=committed.created,
        source=committed.document,
    )


@router.post(
    "/sources/ingest/text-file",
    response_model=IngestUrlResponse,
    responses={
        200: {"description": "同じテキストと本文の再取り込み。既存 Source を返す"},
        201: {"description": "新しい Source、または本文が変わった版を追加する"},
        400: {"description": "invalid_text_file または malformed_text"},
        413: {"description": "file_too_large または text_too_large"},
        415: {"description": "unsupported_media"},
        422: {"description": "text_empty"},
    },
)
def ingest_text_file_source(
    service: TextFileIngestionServiceDep,
    response: Response,
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form()] = None,
    note: Annotated[str | None, Form()] = None,
    language: Annotated[str, Form()] = "fr",
) -> IngestUrlResponse:
    """テキスト / Markdown を provenance 付き SourceDocument にする。"""

    try:
        committed = service.ingest_text_file(
            source=file.file,
            filename=file.filename,
            declared_media_type=file.content_type,
            title=title,
            note=note,
            language=language,
        )
    except SourceIngestionError as exc:
        raise _ingestion_http(exc) from exc
    response.status_code = (
        status.HTTP_201_CREATED if committed.created else status.HTTP_200_OK
    )
    return IngestUrlResponse(
        action=committed.action,
        created=committed.created,
        source=committed.document,
    )


@router.post(
    "/sources/ingest/conversation",
    response_model=IngestUrlResponse,
    responses={
        200: {"description": "同じ会話ログと本文の再取り込み。既存 Source を返す"},
        201: {"description": "新しい Source、または本文が変わった版を追加する"},
        400: {"description": "invalid_conversation または malformed_conversation"},
        413: {"description": "file_too_large または text_too_large"},
        415: {"description": "unsupported_media"},
        422: {"description": "conversation_empty"},
    },
)
def ingest_conversation_source(
    service: ConversationIngestionServiceDep,
    response: Response,
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form()] = None,
    note: Annotated[str | None, Form()] = None,
    language: Annotated[str, Form()] = "fr",
) -> IngestUrlResponse:
    """structured conversation JSON を話者付き SourceDocument にする。"""

    try:
        committed = service.ingest_conversation(
            source=file.file,
            filename=file.filename,
            declared_media_type=file.content_type,
            title=title,
            note=note,
            language=language,
        )
    except SourceIngestionError as exc:
        raise _ingestion_http(exc) from exc
    response.status_code = (
        status.HTTP_201_CREATED if committed.created else status.HTTP_200_OK
    )
    return IngestUrlResponse(
        action=committed.action,
        created=committed.created,
        source=committed.document,
    )


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


@router.get("/today", response_model=TodayLearningPlanView)
def get_today_plan(
    service: TodayLearningServiceDep,
    question_count: int = Query(
        default=DEFAULT_PLAN_SIZE,
        ge=MIN_PLAN_SIZE,
        le=MAX_PLAN_SIZE,
    ),
    max_new_count: int = Query(
        default=DEFAULT_MAX_NEW_COUNT,
        ge=0,
        le=MAX_PLAN_SIZE,
    ),
) -> TodayLearningPlanView:
    """今日の学習 Plan を返す。Session は開始しない。永続化しない。"""
    try:
        return service.get_plan(
            question_count=question_count,
            max_new_count=max_new_count,
        )
    except TutorServiceError as exc:
        raise _to_http(exc) from exc


@router.post("/today/sessions", response_model=TodayLearningSessionResponse)
def create_today_session(
    req: CreateTodaySessionRequest,
    service: TodayLearningServiceDep,
) -> TodayLearningSessionResponse:
    """現在の DB 状態から今日の学習 Session を組み立てる。永続化しない。"""
    try:
        session = service.create_session(
            question_count=req.question_count,
            max_new_count=req.max_new_count,
            seed=req.seed,
        )
    except TutorServiceError as exc:
        raise _to_http(exc) from exc
    return TodayLearningSessionResponse(
        session_id=session.session_id,
        exercises=list(session.to_public_exercises()),
        entries=list(session.entries),
        skipped_entries=list(session.skipped_entries),
        requested_count=session.requested_count,
        generated_count=session.generated_count,
        review_count=session.review_count,
        new_count=session.new_count,
        deferred_due_count=session.deferred_due_count,
        explanation_summary=session.explanation_summary,
        policy_version=session.policy_version,
        generated_at=session.generated_at,
        summary_reason_codes=list(session.summary_reason_codes),
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
