"""Tutor 最小 API のユースケース（Issue #112 / #163）。

Source / LearningItem の登録と、review 1回で LearningEvent・
LearnerState・ReviewSchedule を更新する。router は HTTP 変換だけ行い、
このサービスが repository / 既存 service を組み合わせる。

`datetime.now()` は呼ばない。発生時刻の省略時と due 取得の基準は
コンストラクタに渡す `clock`（デフォルトは `utcnow`）。
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from app.domain.review_queue import (
    DEFAULT_QUEUE_LIMIT,
    MissingReviewQueueItemError,
    ReviewQueue,
    build_review_queue,
)
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
    utcnow,
)
from app.repositories.exceptions import DuplicateEntityError
from app.repositories.protocols import (
    LearnerStateRepository,
    LearningEventRepository,
    LearningItemRepository,
    LearningProgressRepository,
    ReviewScheduleRepository,
    SourceDocumentRepository,
)
from app.services.exceptions import (
    InvalidSourceRefError,
    TutorConflictError,
    TutorInconsistentStateError,
    TutorNotFoundError,
)
from app.services.learning_state_service import LearningStateService
from app.services.review_service import ReviewService


@dataclass(frozen=True)
class LearningItemDetail:
    item: LearningItem
    learner_state: LearnerState | None
    review_schedule: ReviewSchedule | None
    review_schedules: list[ReviewSchedule]


@dataclass(frozen=True)
class ReviewRecord:
    event: LearningEvent
    learner_state: LearnerState
    review_schedule: ReviewSchedule


@dataclass(frozen=True)
class DueReview:
    item: LearningItem
    learner_state: LearnerState | None
    review_schedule: ReviewSchedule


class _TutorStore(Protocol):
    source_documents: SourceDocumentRepository
    learning_items: LearningItemRepository
    learning_events: LearningEventRepository
    learner_states: LearnerStateRepository
    learning_progress: LearningProgressRepository
    review_schedules: ReviewScheduleRepository


def build_tutor_service(
    store: _TutorStore,
    *,
    clock: Callable[[], datetime] = utcnow,
) -> "TutorService":
    """repository 一式から TutorService を組み立てる。"""
    return TutorService(
        sources=store.source_documents,
        items=store.learning_items,
        states=store.learner_states,
        schedules=store.review_schedules,
        learning_state=LearningStateService(
            learning_items=store.learning_items,
            learning_events=store.learning_events,
            learner_states=store.learner_states,
            progress=store.learning_progress,
        ),
        reviews=ReviewService(
            learning_items=store.learning_items,
            review_schedules=store.review_schedules,
        ),
        clock=clock,
    )


class TutorService:
    def __init__(
        self,
        *,
        sources: SourceDocumentRepository,
        items: LearningItemRepository,
        states: LearnerStateRepository,
        schedules: ReviewScheduleRepository,
        learning_state: LearningStateService,
        reviews: ReviewService,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._sources = sources
        self._items = items
        self._states = states
        self._schedules = schedules
        self._learning_state = learning_state
        self._reviews = reviews
        self._clock = clock

    def create_source(
        self,
        *,
        title: str,
        content: str,
        language: str = "fr",
        metadata: dict[str, Any] | None = None,
    ) -> SourceDocument:
        document = SourceDocument(
            title=title,
            content=content,
            language=language,
            metadata=metadata or {},
        )
        try:
            return self._sources.create(document)
        except DuplicateEntityError as exc:
            raise TutorConflictError(exc.entity_type, exc.entity_id) from exc

    def get_source(self, source_id: str) -> SourceDocument:
        document = self._sources.get(source_id)
        if document is None:
            raise TutorNotFoundError("SourceDocument", source_id)
        return document

    def list_sources(self, *, limit: int | None = None) -> list[SourceDocument]:
        """保存済み Source を created_at 降順で返す。limit 未指定なら全件。"""
        return self._sources.list(limit=limit)

    def create_item(
        self,
        *,
        item_type: LearningItemType,
        canonical_form: str,
        meaning_ja: str,
        explanation_ja: str | None = None,
        level: CefrLevel | None = None,
        source_refs: list[SourceRef] | None = None,
        status: LearningItemStatus = "active",
        metadata: dict[str, Any] | None = None,
    ) -> LearningItem:
        refs = source_refs or []
        self._require_existing_sources(refs)
        item = LearningItem(
            item_type=item_type,
            canonical_form=canonical_form,
            meaning_ja=meaning_ja,
            explanation_ja=explanation_ja,
            level=level,
            source_refs=refs,
            status=status,
            metadata=metadata or {},
        )
        try:
            return self._items.create(item)
        except DuplicateEntityError as exc:
            raise TutorConflictError(exc.entity_type, exc.entity_id) from exc

    def get_item(self, item_id: str) -> LearningItemDetail:
        item = self._items.get(item_id)
        if item is None:
            raise TutorNotFoundError("LearningItem", item_id)
        schedules = self._schedules.list_for_item(item_id)
        return LearningItemDetail(
            item=item,
            learner_state=self._states.get(item_id),
            review_schedule=schedules[0] if schedules else None,
            review_schedules=schedules,
        )

    def list_items(self, *, limit: int | None = None) -> list[LearningItem]:
        """active な LearningItem を created_at 昇順（同一時刻は id 昇順）で返す。"""
        items = [item for item in self._items.list() if item.status == "active"]
        if limit is not None:
            return items[:limit]
        return items

    def record_review(
        self,
        item_id: str,
        *,
        exercise_type: ExerciseType,
        result: AnswerOutcome,
        occurred_at: datetime | None = None,
        response_time_ms: int | None = None,
        event_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ReviewRecord:
        """LearningEvent を記録し、LearnerState と ReviewSchedule を更新する。

        `occurred_at` が未指定なら `clock()` を使う。
        """
        if self._items.get(item_id) is None:
            raise TutorNotFoundError("LearningItem", item_id)

        event_kwargs: dict[str, Any] = {
            "learning_item_id": item_id,
            "exercise_type": exercise_type,
            "result": result,
            "occurred_at": occurred_at if occurred_at is not None else self._clock(),
            "response_time_ms": response_time_ms,
            "metadata": metadata or {},
        }
        if event_id is not None:
            event_kwargs["id"] = event_id
        event = LearningEvent(**event_kwargs)

        try:
            state = self._learning_state.record_event(event)
        except DuplicateEntityError as exc:
            raise TutorConflictError(exc.entity_type, exc.entity_id) from exc

        schedule = self._reviews.schedule_after_review(state, event)
        return ReviewRecord(event=event, learner_state=state, review_schedule=schedule)

    def list_due(self, now: datetime | None = None) -> list[DueReview]:
        """`due_at <= now` の active LearningItem を返す。

        `now` 未指定時は `clock()`。HTTP から任意時刻を受け取らない。
        """
        when = now if now is not None else self._clock()
        due: list[DueReview] = []
        for schedule in self._reviews.list_due(when):
            item = self._items.get(schedule.learning_item_id)
            if item is None:
                continue
            due.append(
                DueReview(
                    item=item,
                    learner_state=self._states.get(schedule.learning_item_id),
                    review_schedule=schedule,
                )
            )
        return due

    def list_review_queue(
        self,
        now: datetime | None = None,
        *,
        limit: int = DEFAULT_QUEUE_LIMIT,
    ) -> ReviewQueue:
        """direction-aware な due review queue を返す。

        `now` 未指定時は `clock()`。HTTP から任意時刻を受け取らない。
        recognition / production は別 entry。未スケジュール Item は含めない。
        """
        when = now if now is not None else self._clock()
        schedules = self._reviews.list_due(when)
        items_by_id: dict[str, LearningItem] = {}
        states_by_id: dict[str, LearnerState | None] = {}
        for schedule in schedules:
            item_id = schedule.learning_item_id
            if item_id in items_by_id:
                continue
            item = self._items.get(item_id)
            if item is None:
                raise TutorInconsistentStateError(
                    "LearningItem",
                    item_id,
                    "ReviewSchedule に対応する LearningItem が存在しない",
                )
            items_by_id[item_id] = item
            states_by_id[item_id] = self._states.get(item_id)
        try:
            return build_review_queue(
                schedules,
                items_by_id=items_by_id,
                states_by_id=states_by_id,
                now=when,
                limit=limit,
            )
        except MissingReviewQueueItemError as exc:
            raise TutorInconsistentStateError(
                "LearningItem",
                exc.item_id,
                "ReviewSchedule に対応する LearningItem が存在しない",
            ) from exc

    def _require_existing_sources(self, source_refs: list[SourceRef]) -> None:
        for ref in source_refs:
            if self._sources.get(ref.source_document_id) is None:
                raise InvalidSourceRefError(ref.source_document_id)
