"""保存済み LearningEvent から苦手パターンを算出する（Issue #203）。

集計結果は保存しない。DB を開き直しても、同じ Event と now から同じ
WeaknessPattern を再計算できる。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from app.domain.tutor import utcnow
from app.domain.weakness_pattern import (
    WeaknessPatternReport,
    aggregate_weakness_patterns,
)
from app.repositories.protocols import LearningEventRepository, LearningItemRepository


class _PatternStore(Protocol):
    learning_items: LearningItemRepository
    learning_events: LearningEventRepository


def build_weakness_pattern_service(
    store: _PatternStore,
    *,
    clock: Callable[[], datetime] = utcnow,
) -> WeaknessPatternService:
    """repository から WeaknessPatternService を組み立てる。"""
    return WeaknessPatternService(
        items=store.learning_items,
        events=store.learning_events,
        clock=clock,
    )


class WeaknessPatternService:
    def __init__(
        self,
        *,
        items: LearningItemRepository,
        events: LearningEventRepository,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._items = items
        self._events = events
        self._clock = clock

    def detect(self, *, now: datetime | None = None) -> WeaknessPatternReport:
        """現在の Item と Event から pattern を算出する。永続化しない。"""
        when = now if now is not None else self._clock()
        items = self._items.list()
        events = [
            event for item in items for event in self._events.list_by_item(item.id)
        ]
        return aggregate_weakness_patterns(items, events, now=when)
