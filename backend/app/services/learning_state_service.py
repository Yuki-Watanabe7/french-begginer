"""LearningEvent から LearnerState を更新するユースケース（Issue #110）。

LearningEvent が事実の履歴、LearnerState はその集約キャッシュ。
状態更新は domain の `apply_review_event` に任せ、このサービスは
存在確認・トランザクション・再構築を担う。`by_direction` も同じ
畳み込みで再計算する（Issue #161）。
"""

from app.domain.tutor import LearnerState, LearningEvent, apply_review_event
from app.repositories.protocols import (
    LearnerStateRepository,
    LearningEventRepository,
    LearningItemRepository,
    LearningProgressRepository,
)


class LearningStateService:
    def __init__(
        self,
        *,
        learning_items: LearningItemRepository,
        learning_events: LearningEventRepository,
        learner_states: LearnerStateRepository,
        progress: LearningProgressRepository,
    ) -> None:
        self._items = learning_items
        self._events = learning_events
        self._states = learner_states
        self._progress = progress

    def record_event(self, event: LearningEvent) -> LearnerState:
        """LearningEvent を記録し、対応する LearnerState を更新して返す。

        event 保存と state 更新は同一トランザクション。同じ event.id の
        再登録は DuplicateEntityError で拒否し、state も二重適用しない。
        """
        if self._items.get(event.learning_item_id) is None:
            raise ValueError(f"LearningItem が存在しない: id={event.learning_item_id}")
        current = self._states.get(event.learning_item_id)
        next_state = apply_review_event(current, event)
        self._progress.append_event_and_upsert_state(event, next_state)
        return next_state

    def recompute_learner_state(self, item_id: str) -> LearnerState | None:
        """LearningEvent 履歴から LearnerState を再構築して保存する。

        履歴が source of truth。トランザクション外で state だけ欠けた
        場合の回復に使う。イベントを `occurred_at, id` 順に replay し、
        全体集計と by_direction を同じ履歴から再構築する。
        イベントが無ければ None を返し、既存 state は触らない。
        """
        if self._items.get(item_id) is None:
            raise ValueError(f"LearningItem が存在しない: id={item_id}")
        events = self._events.list_by_item(item_id)
        if not events:
            return None
        state: LearnerState | None = None
        for event in events:
            state = apply_review_event(state, event)
        if state is None:
            return None
        return self._states.upsert(state)
