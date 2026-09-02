"""direction-aware な due review queue（Issue #163 / Phase 4）。

recognition / production 別の ReviewSchedule から、今この瞬間に
復習期限が来ている項目を安定した順序で並べる。Review Practice Session
生成は `review_session`（Issue #164）が担い、personalized ranking は
ここでは行わない。

このモジュールが依存してよいのは Python 標準ライブラリ、Pydantic、
`domain.tutor`、`domain.exercise`、`domain.review_scheduler` のみ。
DB / FastAPI / OpenAI には依存しない。wall clock は呼ばない。
`now` は呼び出し側が渡す。

```text
ReviewSchedule（due_at <= now, active Item）
  -> recognition / production を別 entry
  -> due_at / learning_item_id / skill_direction で安定ソート
  -> ReviewQueue（entries + summary）
```
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.exercise import eligible_exercise_types, skill_direction_for
from app.domain.review_scheduler import DUE_ITEM_STATUS
from app.domain.tutor import (
    ExerciseType,
    LearnerState,
    LearningItem,
    ReviewSchedule,
    SkillDirection,
)

SECONDS_PER_DAY = timedelta(days=1).total_seconds()
"""overdue_days の分母。1日 = 86400 秒。"""

DEFAULT_QUEUE_LIMIT = 20
MIN_QUEUE_LIMIT = 1
MAX_QUEUE_LIMIT = 100


class InvalidReviewQueueRequestError(ValueError):
    """limit など、queue 入力が不正。"""


class MissingReviewQueueItemError(ValueError):
    """queue 対象の ReviewSchedule に対応する LearningItem が無い。"""

    def __init__(self, item_id: str) -> None:
        self.item_id = item_id
        super().__init__(
            f"ReviewSchedule に対応する LearningItem が存在しない: id={item_id}"
        )


class ReviewQueueEntry(BaseModel):
    """復習セッションへ渡せる 1 件。Item × SkillDirection。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    item: LearningItem
    skill_direction: SkillDirection
    learner_state: LearnerState | None = None
    review_schedule: ReviewSchedule
    overdue_seconds: float
    overdue_days: float
    available_exercise_types: tuple[ExerciseType, ...] = ()

    @model_validator(mode="after")
    def _check_invariants(self) -> ReviewQueueEntry:
        if self.review_schedule.learning_item_id != self.item.id:
            raise ValueError(
                "ReviewQueueEntry の LearningItem と ReviewSchedule が一致しない: "
                f"item={self.item.id}, schedule={self.review_schedule.learning_item_id}"
            )
        if self.review_schedule.skill_direction != self.skill_direction:
            raise ValueError(
                "ReviewQueueEntry の skill_direction が ReviewSchedule と一致しない: "
                f"entry={self.skill_direction}, "
                f"schedule={self.review_schedule.skill_direction}"
            )
        if self.learner_state is not None:
            if self.learner_state.learning_item_id != self.item.id:
                raise ValueError(
                    "ReviewQueueEntry の LearnerState が LearningItem と一致しない: "
                    f"item={self.item.id}, "
                    f"state={self.learner_state.learning_item_id}"
                )
        return self


class ReviewQueueSummary(BaseModel):
    """件数表示用。limit 適用前の due 全体を数える。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    total_due: int = Field(ge=0)
    recognition_due: int = Field(ge=0)
    production_due: int = Field(ge=0)
    overdue_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _check_counts(self) -> ReviewQueueSummary:
        if self.recognition_due + self.production_due != self.total_due:
            raise ValueError(
                "recognition_due + production_due は total_due と一致する必要がある: "
                f"recognition={self.recognition_due}, "
                f"production={self.production_due}, "
                f"total={self.total_due}"
            )
        if self.overdue_count > self.total_due:
            raise ValueError(
                "overdue_count は total_due を超えない: "
                f"overdue={self.overdue_count}, total={self.total_due}"
            )
        return self


class ReviewQueue(BaseModel):
    """due review の説明可能な queue。正解情報は含めない。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entries: tuple[ReviewQueueEntry, ...] = ()
    summary: ReviewQueueSummary


def available_exercise_types_for(
    item: LearningItem, direction: SkillDirection
) -> tuple[ExerciseType, ...]:
    """当該 direction で安全に出せる ExerciseType。unsupported は含めない。"""
    return tuple(
        exercise_type
        for exercise_type in eligible_exercise_types(item)
        if skill_direction_for(exercise_type) == direction
    )


def compute_overdue(due_at: datetime, now: datetime) -> tuple[float, float]:
    """due_at から now までの遅れ。now == due_at なら (0, 0)。"""
    aware_due = _require_aware_utc(due_at)
    aware_now = _require_aware_utc(now)
    seconds = (aware_now - aware_due).total_seconds()
    return seconds, seconds / SECONDS_PER_DAY


def build_review_queue(
    schedules: Sequence[ReviewSchedule],
    *,
    items_by_id: Mapping[str, LearningItem],
    states_by_id: Mapping[str, LearnerState | None] | None = None,
    now: datetime,
    limit: int = DEFAULT_QUEUE_LIMIT,
) -> ReviewQueue:
    """due な ReviewSchedule から deterministic な queue を組み立てる。

    - `due_at <= now` かつ active な LearningItem のみ
    - ReviewSchedule が無い Item は due にしない
    - recognition / production は別 entry
    - 並びは due_at 昇順、同値なら learning_item_id、skill_direction
    - summary は limit 適用前の件数
    - schedule に対応する Item が無い場合は黙って落とさず例外にする
    """
    aware_now = _require_aware_utc(now)
    _require_limit(limit)
    states = states_by_id or {}

    due: list[ReviewSchedule] = []
    for schedule in schedules:
        item = items_by_id.get(schedule.learning_item_id)
        if item is None:
            raise MissingReviewQueueItemError(schedule.learning_item_id)
        if item.status != DUE_ITEM_STATUS:
            continue
        if _require_aware_utc(schedule.due_at) > aware_now:
            continue
        due.append(schedule)

    due.sort(key=_queue_sort_key)
    entries = tuple(
        _to_entry(
            schedule,
            item=items_by_id[schedule.learning_item_id],
            learner_state=states.get(schedule.learning_item_id),
            now=aware_now,
        )
        for schedule in due
    )
    return ReviewQueue(entries=entries[:limit], summary=_summarize(entries, aware_now))


def _to_entry(
    schedule: ReviewSchedule,
    *,
    item: LearningItem,
    learner_state: LearnerState | None,
    now: datetime,
) -> ReviewQueueEntry:
    overdue_seconds, overdue_days = compute_overdue(schedule.due_at, now)
    return ReviewQueueEntry(
        item=item,
        skill_direction=schedule.skill_direction,
        learner_state=learner_state,
        review_schedule=schedule,
        overdue_seconds=overdue_seconds,
        overdue_days=overdue_days,
        available_exercise_types=available_exercise_types_for(
            item, schedule.skill_direction
        ),
    )


def _summarize(
    entries: Sequence[ReviewQueueEntry], now: datetime
) -> ReviewQueueSummary:
    recognition_due = sum(1 for row in entries if row.skill_direction == "recognition")
    production_due = sum(1 for row in entries if row.skill_direction == "production")
    overdue_count = sum(
        1 for row in entries if _require_aware_utc(row.review_schedule.due_at) < now
    )
    return ReviewQueueSummary(
        total_due=len(entries),
        recognition_due=recognition_due,
        production_due=production_due,
        overdue_count=overdue_count,
    )


def _queue_sort_key(schedule: ReviewSchedule) -> tuple[datetime, str, SkillDirection]:
    return (
        _require_aware_utc(schedule.due_at),
        schedule.learning_item_id,
        schedule.skill_direction,
    )


def _require_limit(limit: int) -> None:
    if not MIN_QUEUE_LIMIT <= limit <= MAX_QUEUE_LIMIT:
        raise InvalidReviewQueueRequestError(
            f"limit は {MIN_QUEUE_LIMIT}〜{MAX_QUEUE_LIMIT} の整数: {limit}"
        )


def _require_aware_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError("timezone-aware な datetime が必要")
    return dt.astimezone(UTC)
