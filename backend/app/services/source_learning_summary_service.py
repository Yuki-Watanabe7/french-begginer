"""保存済み Candidate / Item / State から Source 学習サマリーを作る（Issue #205）。

集計結果は保存しない。DB を開き直しても、同じデータと now から同じ
SourceLearningSummary を再計算できる。SourceType では分岐しない。
LearningEvent は読み直さない。LearnerState を item ごとに1回だけ使う。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from app.domain.source_learning_summary import (
    SourceLearningSummary,
    summarize_source_learning,
)
from app.domain.tutor import utcnow
from app.repositories.protocols import (
    KnownItemRepository,
    LearnerStateRepository,
    LearningItemCandidateRepository,
    LearningItemRepository,
    ReviewScheduleRepository,
    SourceDocumentRepository,
)
from app.services.exceptions import TutorNotFoundError


class _SummaryStore(Protocol):
    source_documents: SourceDocumentRepository
    learning_items: LearningItemRepository
    learning_item_candidates: LearningItemCandidateRepository
    learner_states: LearnerStateRepository
    review_schedules: ReviewScheduleRepository
    known_items: KnownItemRepository


def build_source_learning_summary_service(
    store: _SummaryStore,
    *,
    clock: Callable[[], datetime] = utcnow,
) -> SourceLearningSummaryService:
    """repository から SourceLearningSummaryService を組み立てる。"""

    return SourceLearningSummaryService(
        sources=store.source_documents,
        items=store.learning_items,
        candidates=store.learning_item_candidates,
        states=store.learner_states,
        schedules=store.review_schedules,
        known=store.known_items,
        clock=clock,
    )


class SourceLearningSummaryService:
    def __init__(
        self,
        *,
        sources: SourceDocumentRepository,
        items: LearningItemRepository,
        candidates: LearningItemCandidateRepository,
        states: LearnerStateRepository,
        schedules: ReviewScheduleRepository,
        known: KnownItemRepository,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._sources = sources
        self._items = items
        self._candidates = candidates
        self._states = states
        self._schedules = schedules
        self._known = known
        self._clock = clock

    def summarize(
        self, source_id: str, *, now: datetime | None = None
    ) -> SourceLearningSummary:
        """Source に関連する学習の現在状態を返す。永続化しない。"""

        if self._sources.get(source_id) is None:
            raise TutorNotFoundError("SourceDocument", source_id)
        when = now if now is not None else self._clock()
        items = self._items.list()
        return summarize_source_learning(
            source_id,
            candidates=self._candidates.list_by_source(source_id),
            items=items,
            states={item.id: self._states.get(item.id) for item in items},
            schedules={
                item.id: self._schedules.list_for_item(item.id) for item in items
            },
            known_item_ids=self._known.list_active_ids(),
            now=when,
        )
