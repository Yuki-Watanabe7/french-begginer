"""説明可能な初期 Review Scheduler（Issue #111）。

LearnerState と直近 LearningEvent から次回復習予定を決める。
Phase 0 では SM-2 / FSRS は導入せず、単純・deterministic な baseline にする。
日数の最適性は狙わない。後からアルゴリズムを差し替えられる境界を作ることが目的。

このモジュールが依存してよいのは Python 標準ライブラリと domain.tutor のみ。
datetime.now() は呼ばない。due_at は event.occurred_at を基準に算出する。
"""

from datetime import timedelta

from app.domain.tutor import (
    AnswerOutcome,
    LearnerState,
    LearningEvent,
    LearningItemStatus,
    ReviewSchedule,
)

SCHEDULER_VERSION = "v0"
"""このモジュールが書き込む scheduler_version。将来 SM-2 / FSRS と比較する鍵。"""

DUE_ITEM_STATUS: LearningItemStatus = "active"
"""due 取得の対象。suspended / mastered は予定が残っていても出題しない。"""

INTERVAL_DAYS_ON_LAPSE = 1.0
"""誤答時の間隔。連続正解で伸びた間隔をリセットする。"""

# consecutive_correct 1, 2, 3, 4+ に対応する間隔（日）。
# 4以上は 14 日で打ち切る。指数的な延長は Phase 0 では最適化しない。
_CORRECT_INTERVAL_DAYS = (1.0, 3.0, 7.0, 14.0)


def interval_days_after_review(
    *, result: AnswerOutcome, consecutive_correct: int
) -> float:
    """直近結果と連続正解数から次の間隔を返す。

    - incorrect: 1日
    - 連続1回正解: 1日（初回学習後も翌日）
    - 連続2回正解: 3日
    - 連続3回正解: 7日
    - 連続4回以上: 14日（上限）

    連続正解が増えるほど間隔は短くならない。
    """
    if result == "incorrect":
        return INTERVAL_DAYS_ON_LAPSE
    if consecutive_correct <= 0:
        return INTERVAL_DAYS_ON_LAPSE
    index = min(consecutive_correct, len(_CORRECT_INTERVAL_DAYS)) - 1
    return _CORRECT_INTERVAL_DAYS[index]


def schedule_next_review(
    state: LearnerState,
    event: LearningEvent,
    previous_schedule: ReviewSchedule | None = None,
) -> ReviewSchedule:
    """学習後の次回復習予定を返す。現在の schedule は変更しない。

    `state` は `apply_review_event` 適用後の LearnerState を渡す。
    同じ (state, event, previous_schedule) からは常に同じ結果になる。
    過去の schedule を履歴として残さず、現行予定だけを置き換える。
    """
    if event.event_type != "review":
        raise ValueError(f"未対応の event_type: {event.event_type}")
    if state.learning_item_id != event.learning_item_id:
        raise ValueError(
            "LearnerState と LearningEvent の learning_item_id が一致しない: "
            f"state={state.learning_item_id}, event={event.learning_item_id}"
        )
    if (
        previous_schedule is not None
        and previous_schedule.learning_item_id != event.learning_item_id
    ):
        raise ValueError(
            "ReviewSchedule と LearningEvent の learning_item_id が一致しない: "
            f"schedule={previous_schedule.learning_item_id}, "
            f"event={event.learning_item_id}"
        )

    interval_days = interval_days_after_review(
        result=event.result, consecutive_correct=state.consecutive_correct
    )
    review_count = (
        previous_schedule.review_count + 1 if previous_schedule is not None else 1
    )
    lapse_count = previous_schedule.lapse_count if previous_schedule is not None else 0
    if event.result == "incorrect":
        lapse_count += 1

    return ReviewSchedule(
        learning_item_id=event.learning_item_id,
        due_at=event.occurred_at + timedelta(days=interval_days),
        interval_days=interval_days,
        review_count=review_count,
        lapse_count=lapse_count,
        scheduler_version=SCHEDULER_VERSION,
        metadata=previous_schedule.metadata if previous_schedule is not None else {},
    )
