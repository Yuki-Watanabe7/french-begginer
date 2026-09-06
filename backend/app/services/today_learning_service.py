"""「今日の学習」Plan と Tutor Today Session の組み立て（Issue #178）。

repository から Item / State / Schedule / Event / Source を読み、
signal → ranking → Daily Learning Plan を組み立てる。
Session 自体は保存しない。router は HTTP 変換だけ行う。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from pydantic import ValidationError

from app.domain.daily_learning_plan import (
    DEFAULT_MAX_NEW_COUNT,
    DEFAULT_PLAN_SEED,
    DEFAULT_PLAN_SIZE,
    DailyLearningPlan,
    InvalidPlanConstraintsError,
    PlanConstraints,
    build_daily_learning_plan,
)
from app.domain.recommendation_ranking import rank_recommendations
from app.domain.recommendation_signal import (
    SKILL_DIRECTIONS,
    RecommendationSignalSnapshot,
    extract_recommendation_signal,
)
from app.domain.today_session import (
    DEFAULT_TODAY_SESSION_SEED,
    TodayLearningPlanView,
    TodayLearningSession,
    build_today_learning_session,
    to_public_plan,
)
from app.domain.tutor import (
    LearningItem,
    SourceDocument,
    utcnow,
)
from app.repositories.protocols import (
    LearnerStateRepository,
    LearningEventRepository,
    LearningItemRepository,
    ReviewScheduleRepository,
    SourceDocumentRepository,
)
from app.services.exceptions import InvalidTodayLearningError


class _TodayStore(Protocol):
    source_documents: SourceDocumentRepository
    learning_items: LearningItemRepository
    learning_events: LearningEventRepository
    learner_states: LearnerStateRepository
    review_schedules: ReviewScheduleRepository


def build_today_learning_service(
    store: _TodayStore,
    *,
    clock: Callable[[], datetime] = utcnow,
) -> TodayLearningService:
    """repository から TodayLearningService を組み立てる。"""
    return TodayLearningService(
        sources=store.source_documents,
        items=store.learning_items,
        events=store.learning_events,
        states=store.learner_states,
        schedules=store.review_schedules,
        clock=clock,
    )


class TodayLearningService:
    def __init__(
        self,
        *,
        sources: SourceDocumentRepository,
        items: LearningItemRepository,
        events: LearningEventRepository,
        states: LearnerStateRepository,
        schedules: ReviewScheduleRepository,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._sources = sources
        self._items = items
        self._events = events
        self._states = states
        self._schedules = schedules
        self._clock = clock

    def get_plan(
        self,
        *,
        question_count: int = DEFAULT_PLAN_SIZE,
        max_new_count: int = DEFAULT_MAX_NEW_COUNT,
        seed: str | int | None = None,
        now: datetime | None = None,
    ) -> TodayLearningPlanView:
        """今日の学習 Plan を公開 DTO として返す。永続化しない。"""
        plan, context = self._build_plan(
            question_count=question_count,
            max_new_count=max_new_count,
            seed=seed,
            now=now,
        )
        return to_public_plan(
            plan,
            items_by_id=context.items_by_id,
            sources_by_id=context.sources_by_id,
        )

    def create_session(
        self,
        *,
        question_count: int = DEFAULT_PLAN_SIZE,
        max_new_count: int = DEFAULT_MAX_NEW_COUNT,
        seed: str | int | None = None,
        now: datetime | None = None,
    ) -> TodayLearningSession:
        """現在の DB 状態から Plan を再計算し、Today Session を組み立てる。

        長時間 plan を予約保持しない。直前に消化済みの due や inactive は
        再計算で自然に落ち、残った entry も stale skip する。
        Session は保存しない。LearningEvent は作らない。
        `now` 未指定時は clock。HTTP から任意時刻は受け取らない。
        """
        session_seed = DEFAULT_TODAY_SESSION_SEED if seed is None else seed
        plan, context = self._build_plan(
            question_count=question_count,
            max_new_count=max_new_count,
            seed=session_seed,
            now=now,
        )
        return build_today_learning_session(
            plan,
            items_by_id=context.items_by_id,
            snapshots_by_id=context.snapshots_by_id,
            sources=context.sources_by_id,
            seed=session_seed,
        )

    def _build_plan(
        self,
        *,
        question_count: int,
        max_new_count: int,
        seed: str | int | None,
        now: datetime | None,
    ) -> tuple[DailyLearningPlan, _PlanContext]:
        when = now if now is not None else self._clock()
        constraints = _plan_constraints(question_count, max_new_count)
        all_items = self._items.list()
        items_by_id = {item.id: item for item in all_items}
        sources_by_id = {row.id: row for row in self._sources.list()}
        snapshots: list[RecommendationSignalSnapshot] = []
        snapshots_by_id: dict[str, RecommendationSignalSnapshot] = {}
        for item in all_items:
            if item.status != "active":
                continue
            snapshot = extract_recommendation_signal(
                item,
                learner_state=self._states.get(item.id),
                schedules_by_direction={
                    row.skill_direction: row
                    for row in self._schedules.list_for_item(item.id)
                },
                events_by_direction={
                    direction: self._events.list_by_item_and_direction(
                        item.id, direction
                    )
                    for direction in SKILL_DIRECTIONS
                },
                sources_by_id=sources_by_id,
                now=when,
            )
            snapshots.append(snapshot)
            snapshots_by_id[item.id] = snapshot
        ranked = rank_recommendations(snapshots)
        plan = build_daily_learning_plan(
            ranked,
            items_by_id=items_by_id,
            snapshots_by_id=snapshots_by_id,
            constraints=constraints,
            generated_at=when,
            seed=DEFAULT_PLAN_SEED if seed is None else seed,
        )
        return plan, _PlanContext(
            items_by_id=items_by_id,
            sources_by_id=sources_by_id,
            snapshots_by_id=snapshots_by_id,
        )


@dataclass(frozen=True)
class _PlanContext:
    items_by_id: dict[str, LearningItem]
    sources_by_id: dict[str, SourceDocument]
    snapshots_by_id: dict[str, RecommendationSignalSnapshot]


def _plan_constraints(question_count: int, max_new_count: int) -> PlanConstraints:
    try:
        return PlanConstraints(
            total_count=question_count,
            max_new_count=max_new_count,
        )
    except (ValidationError, InvalidPlanConstraintsError) as exc:
        raise InvalidTodayLearningError(str(exc)) from exc
