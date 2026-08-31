"""復習予定の更新と due 取得（Issue #111 / #162）。

間隔計算は domain の `schedule_next_review` に任せ、このサービスは
存在確認・永続化・due query を担う。`now` は呼び出し側が渡す。
direction 別の previous schedule だけを入力にし、他方向は触らない。
"""

from datetime import datetime

from app.domain.review_scheduler import schedule_next_review
from app.domain.tutor import (
    LearnerState,
    LearningEvent,
    ReviewSchedule,
    SkillDirection,
    skill_direction_for_event,
)
from app.repositories.protocols import (
    LearningItemRepository,
    ReviewScheduleRepository,
)


class ReviewService:
    def __init__(
        self,
        *,
        learning_items: LearningItemRepository,
        review_schedules: ReviewScheduleRepository,
    ) -> None:
        self._items = learning_items
        self._schedules = review_schedules

    def schedule_after_review(
        self, state: LearnerState, event: LearningEvent
    ) -> ReviewSchedule:
        """学習後の次回復習予定を算出して保存する。

        `state` は当該 event を反映済みの LearnerState を渡す。
        該当 direction の previous schedule だけを使い、他方向は更新しない。
        """
        if self._items.get(event.learning_item_id) is None:
            raise ValueError(f"LearningItem が存在しない: id={event.learning_item_id}")
        direction = skill_direction_for_event(event)
        if direction is None:
            raise ValueError(
                "SkillDirection を決定できない LearningEvent からは "
                "ReviewSchedule を更新できない"
            )
        previous = self._schedules.get(event.learning_item_id, direction)
        schedule = schedule_next_review(state, event, previous)
        return self._schedules.upsert(schedule)

    def list_due(
        self, now: datetime, direction: SkillDirection | None = None
    ) -> list[ReviewSchedule]:
        """`due_at <= now` の active LearningItem の予定を返す。

        direction を指定するとその方向だけ。未指定なら両方向。
        返却順は `due_at` 昇順、同値なら `learning_item_id`、`skill_direction` 昇順。
        suspended / mastered は予定が残っていても含めない。
        """
        return self._schedules.list_due(now, direction)
