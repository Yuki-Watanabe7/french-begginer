"""LearningEvent 履歴から ReviewSchedule を再構築する（Issue #166）。

due queue は保存済み ReviewSchedule を参照する。このサービスは欠損や
旧 scheduler_version を修復する maintenance 操作であり、通常の回答記録
や queue 取得では呼ばない。
"""

from app.domain.review_scheduler import (
    DIRECTION_ORDER,
    ScheduleInconsistency,
    detect_schedule_inconsistencies,
    rebuild_directional_schedules,
)
from app.domain.tutor import ReviewSchedule
from app.repositories.protocols import (
    LearningEventRepository,
    LearningItemRepository,
    ReviewScheduleRepository,
)


def build_review_schedule_rebuilder(
    *,
    learning_items: LearningItemRepository,
    learning_events: LearningEventRepository,
    review_schedules: ReviewScheduleRepository,
) -> "ReviewScheduleRebuilder":
    return ReviewScheduleRebuilder(
        learning_items=learning_items,
        learning_events=learning_events,
        review_schedules=review_schedules,
    )


class ReviewScheduleRebuilder:
    def __init__(
        self,
        *,
        learning_items: LearningItemRepository,
        learning_events: LearningEventRepository,
        review_schedules: ReviewScheduleRepository,
    ) -> None:
        self._items = learning_items
        self._events = learning_events
        self._schedules = review_schedules

    def rebuild_for_item(self, item_id: str) -> list[ReviewSchedule]:
        """当該 Item の Event 履歴から direction 別 schedule を再構築して保存する。

        履歴が source of truth。旧 schedule は入力に使わない。
        置換は Item 単位の同一トランザクションなので、失敗時に
        中途半端な schedule は残さない。
        """
        if self._items.get(item_id) is None:
            raise ValueError(f"LearningItem が存在しない: id={item_id}")
        events = self._events.list_by_item(item_id)
        rebuilt = rebuild_directional_schedules(events)
        schedules = [
            rebuilt[direction] for direction in DIRECTION_ORDER if direction in rebuilt
        ]
        return self._schedules.replace_for_item(item_id, schedules)

    def rebuild_all(self) -> dict[str, list[ReviewSchedule]]:
        """全 LearningItem の schedule を Item 単位で再構築する。"""
        rebuilt: dict[str, list[ReviewSchedule]] = {}
        for item in self._items.list():
            rebuilt[item.id] = self.rebuild_for_item(item.id)
        return rebuilt

    def detect_inconsistencies(
        self, item_id: str | None = None
    ) -> list[ScheduleInconsistency]:
        """欠損 / review_count 不一致 / 旧 scheduler_version を検出する。

        item_id 未指定なら全 Item を点検する。自動修復はしない。
        """
        if item_id is not None:
            return self._detect_for_item(item_id)
        found: list[ScheduleInconsistency] = []
        for item in self._items.list():
            found.extend(self._detect_for_item(item.id))
        return found

    def _detect_for_item(self, item_id: str) -> list[ScheduleInconsistency]:
        if self._items.get(item_id) is None:
            raise ValueError(f"LearningItem が存在しない: id={item_id}")
        return detect_schedule_inconsistencies(
            self._events.list_by_item(item_id),
            self._schedules.list_for_item(item_id),
        )
