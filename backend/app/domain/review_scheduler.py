"""説明可能な初期 Review Scheduler（Issue #111 / #162）。

LearnerState と直近 LearningEvent から次回復習予定を決める。
Phase 0 では SM-2 / FSRS は導入せず、単純・deterministic な baseline にする。
日数の最適性は狙わない。後からアルゴリズムを差し替えられる境界を作ることが目的。

Issue #162 では同じ baseline を recognition / production 別に適用する。
全体 LearnerState は維持するが、間隔・lapse の算出は
`LearnerState.by_direction[direction]` を基準にする。

このモジュールが依存してよいのは Python 標準ライブラリと domain.tutor のみ。
datetime.now() は呼ばない。due_at は event.occurred_at を基準に算出する。
"""

from collections.abc import Sequence
from datetime import timedelta

from app.domain.tutor import (
    AnswerOutcome,
    LearnerState,
    LearningEvent,
    LearningItemStatus,
    ReviewSchedule,
    SkillDirection,
    apply_review_event,
    skill_direction_for_event,
)

SCHEDULER_VERSION = "v1-directional"
"""このモジュールが書き込む scheduler_version。direction 別 baseline の版。"""

DUE_ITEM_STATUS: LearningItemStatus = "active"
"""due 取得の対象。suspended / mastered は予定が残っていても出題しない。"""

INTERVAL_DAYS_ON_LAPSE = 1.0
"""誤答時の間隔。連続正解で伸びた間隔をリセットする。"""

DIRECTION_ORDER: tuple[SkillDirection, ...] = ("recognition", "production")
"""同一 Item の schedule を並べるときの安定順。"""

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
    間隔は全体集計ではなく、当該 event の SkillDirection の
    `by_direction` 連続正解を使う。recognition の正答は production の
    interval / review_count を進めず、その逆も同様。

    direction を復元できない event からは算出しない（推測しない）。
    同じ (state, event, previous_schedule) からは常に同じ結果になる。
    """
    if event.event_type != "review":
        raise ValueError(f"未対応の event_type: {event.event_type}")
    if state.learning_item_id != event.learning_item_id:
        raise ValueError(
            "LearnerState と LearningEvent の learning_item_id が一致しない: "
            f"state={state.learning_item_id}, event={event.learning_item_id}"
        )
    direction = skill_direction_for_event(event)
    if direction is None:
        raise ValueError(
            "SkillDirection を決定できない LearningEvent からは "
            "ReviewSchedule を算出できない"
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
    if previous_schedule is not None and previous_schedule.skill_direction != direction:
        raise ValueError(
            "ReviewSchedule と LearningEvent の skill_direction が一致しない: "
            f"schedule={previous_schedule.skill_direction}, event={direction}"
        )

    direction_stats = state.by_direction.get(direction)
    if direction_stats is None:
        raise ValueError(
            "LearnerState.by_direction に該当 SkillDirection が無い: "
            f"direction={direction}。"
            "apply_review_event 適用後の state を渡す必要がある"
        )

    interval_days = interval_days_after_review(
        result=event.result, consecutive_correct=direction_stats.consecutive_correct
    )
    review_count = (
        previous_schedule.review_count + 1 if previous_schedule is not None else 1
    )
    lapse_count = previous_schedule.lapse_count if previous_schedule is not None else 0
    if event.result == "incorrect":
        lapse_count += 1

    return ReviewSchedule(
        learning_item_id=event.learning_item_id,
        skill_direction=direction,
        due_at=event.occurred_at + timedelta(days=interval_days),
        interval_days=interval_days,
        review_count=review_count,
        lapse_count=lapse_count,
        scheduler_version=SCHEDULER_VERSION,
        metadata=previous_schedule.metadata if previous_schedule is not None else {},
    )


def rebuild_directional_schedules(
    events: Sequence[LearningEvent],
) -> dict[SkillDirection, ReviewSchedule]:
    """LearningEvent 履歴から direction 別 ReviewSchedule を再構築する。

    履歴が source of truth。旧 schedule は入力に使わない。
    `exercise_type` から direction を決められない event は推測せず飛ばす。
    同じ event 列からは常に同じ結果になる。
    """
    if not events:
        return {}
    item_ids = {event.learning_item_id for event in events}
    if len(item_ids) != 1:
        raise ValueError(
            "rebuild_directional_schedules は同一 LearningItem の "
            f"event だけを受け取る: item_ids={sorted(item_ids)}"
        )

    state: LearnerState | None = None
    schedules: dict[SkillDirection, ReviewSchedule] = {}
    for event in events:
        state = apply_review_event(state, event)
        direction = skill_direction_for_event(event)
        if direction is None:
            continue
        schedules[direction] = schedule_next_review(
            state, event, schedules.get(direction)
        )
    return schedules
