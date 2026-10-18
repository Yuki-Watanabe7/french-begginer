"""「今日の学習」Plan と Tutor Today Session の組み立て（Issue #178）。

repository から Item / State / Schedule / Event / Source を読み、
signal → known-item policy → admission → ranking → Daily Learning Plan
を組み立てる。explicit known と auto-skip は new_practice だけを外し、
due review は残す（Issue #201）。未学習の新規は admission policy（Issue #200）
を通過したものだけを new_practice として Plan に渡す。
復習の順位と max_new_count の配分は変えない。
Session 自体は保存しない。router は HTTP 変換だけ行う。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from pydantic import ValidationError

from app.domain.admission_policy import (
    UnseenBacklogItem,
    build_unseen_backlog_item,
    count_due_review_units,
    count_recent_introductions,
    decide_new_admissions,
    filter_ranked_new_practice,
)
from app.domain.context_selection import context_usages_from_events
from app.domain.daily_learning_plan import (
    DEFAULT_MAX_NEW_COUNT,
    DEFAULT_PLAN_SEED,
    DEFAULT_PLAN_SIZE,
    DailyLearningPlan,
    InvalidPlanConstraintsError,
    PlanConstraints,
    build_daily_learning_plan,
)
from app.domain.known_item_policy import (
    decide_auto_skip,
    should_drop_today_candidate,
)
from app.domain.recommendation_ranking import (
    RankedRecommendation,
    infer_activity_kind,
    rank_recommendations,
)
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
    LearningEvent,
    LearningItem,
    SkillDirection,
    SourceDocument,
    skill_direction_for_event,
    utcnow,
)
from app.domain.weakness_pattern import (
    aggregate_weakness_patterns,
    weakness_hints_for_item,
)
from app.repositories.protocols import (
    KnownItemRepository,
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
    known_items: KnownItemRepository


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
        known=store.known_items,
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
        known: KnownItemRepository,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._sources = sources
        self._items = items
        self._events = events
        self._states = states
        self._schedules = schedules
        self._known = known
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
            snapshots_by_id=context.snapshots_by_id,
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
        item_ids = dict.fromkeys(entry.learning_item_id for entry in plan.entries)
        usages = {
            item_id: context_usages_from_events(self._events.list_by_item(item_id))
            for item_id in item_ids
        }
        return build_today_learning_session(
            plan,
            items_by_id=context.items_by_id,
            snapshots_by_id=context.snapshots_by_id,
            sources=context.sources_by_id,
            seed=session_seed,
            context_usages_by_item=usages,
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
        events_by_item = {
            item.id: self._events.list_by_item(item.id) for item in all_items
        }
        weakness_report = aggregate_weakness_patterns(
            all_items,
            [event for events in events_by_item.values() for event in events],
            now=when,
        )
        snapshots: list[RecommendationSignalSnapshot] = []
        snapshots_by_id: dict[str, RecommendationSignalSnapshot] = {}
        unseen: list[UnseenBacklogItem] = []
        first_learned_at: dict[str, datetime] = {}
        explicit_known_ids = self._known.list_active_ids()
        auto_skipped: set[tuple[str, SkillDirection]] = set()
        for item in all_items:
            if item.status != "active":
                continue
            events_by_direction: dict[SkillDirection, list[LearningEvent]] = {
                direction: [] for direction in SKILL_DIRECTIONS
            }
            for event in events_by_item[item.id]:
                direction = skill_direction_for_event(event)
                if direction is None:
                    continue
                events_by_direction[direction].append(event)
            for direction, events in events_by_direction.items():
                decision = decide_auto_skip(
                    skill_direction=direction,
                    events=events,
                    now=when,
                )
                if decision.skip_new:
                    auto_skipped.add((item.id, direction))
            learned_at = [
                event.occurred_at
                for events in events_by_direction.values()
                for event in events
            ]
            if learned_at:
                first_learned_at[item.id] = min(learned_at)
            snapshot = extract_recommendation_signal(
                item,
                learner_state=self._states.get(item.id),
                schedules_by_direction={
                    row.skill_direction: row
                    for row in self._schedules.list_for_item(item.id)
                },
                events_by_direction=events_by_direction,
                sources_by_id=sources_by_id,
                weakness_patterns=weakness_hints_for_item(item.id, weakness_report),
                now=when,
            )
            snapshots.append(snapshot)
            snapshots_by_id[item.id] = snapshot
            if item.id in explicit_known_ids:
                continue
            backlog_item = build_unseen_backlog_item(
                item,
                snapshot,
                sources_by_id=sources_by_id,
            )
            if backlog_item is None:
                continue
            if _has_offerable_new_direction(snapshot, auto_skipped):
                unseen.append(backlog_item)
        admission = decide_new_admissions(
            unseen,
            due_review_count=count_due_review_units(snapshots),
            recent_introduced_count=count_recent_introductions(
                first_learned_at,
                now=when,
            ),
            now=when,
        )
        ranked = _drop_blocked_new_practice(
            filter_ranked_new_practice(rank_recommendations(snapshots), admission),
            explicit_known_ids=explicit_known_ids,
            auto_skipped=auto_skipped,
        )
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


def _drop_blocked_new_practice(
    ranked: tuple[RankedRecommendation, ...],
    *,
    explicit_known_ids: set[str],
    auto_skipped: set[tuple[str, SkillDirection]],
) -> tuple[RankedRecommendation, ...]:
    """review は残し、known / auto-skip の new_practice だけを外す。"""

    return tuple(
        row
        for row in ranked
        if not should_drop_today_candidate(
            activity_kind=row.activity_kind,
            explicit_known=row.learning_item_id in explicit_known_ids,
            auto_skip_new=(row.learning_item_id, row.skill_direction) in auto_skipped,
        )
    )


def _has_offerable_new_direction(
    snapshot: RecommendationSignalSnapshot,
    auto_skipped: set[tuple[str, SkillDirection]],
) -> bool:
    """admission 在庫に残してよい新規 direction が残っているか。"""

    for direction, signal in snapshot.by_direction.items():
        if infer_activity_kind(signal) != "new_practice":
            continue
        if (snapshot.learning_item_id, direction) in auto_skipped:
            continue
        return True
    return False
