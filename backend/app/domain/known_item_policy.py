"""既知項目を新規学習から外す known-item policy（Issue #201 / Phase 7）。

3つの責務を混ぜない。

- ``mastered``（``LearningItem.status``）: 既存の定着状態。due review からも外れる。
  このモジュールは status を変えない。
- explicit known: ユーザーが「知っている」と宣言した事実。新規学習から外す。
  due review は消さない。undo できる。操作のたびに履歴と更新時刻を残す。
- auto-skip: その direction の履歴が十分で、最近の誤答がないときだけ、
  その direction の新規学習を不要と判断する。永続 status にはしない。

「知っている」は新規導入を skip する情報であり、将来の再確認を禁止しない。
1回の正解では auto-skip しない。recognition が高いだけでは production を
skip しない。

このモジュールが依存してよいのは Python 標準ライブラリ、Pydantic、
``domain.tutor``、``domain.recommendation_ranking`` のみ。
DB / FastAPI / OpenAI には依存しない。wall clock は呼ばない。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.recommendation_ranking import ActivityKind
from app.domain.tutor import (
    LearningEvent,
    SkillDirection,
    skill_direction_for_event,
)

POLICY_VERSION = "known-item-v1"
"""explicit known の応答に載せる policy 版。判定規則の変更時は bump する。"""

MIN_CORRECT_COUNT = 3
"""auto-skip に必要な、その direction の正解回数。1回では足りない。"""

MIN_MASTERY_SCORE = 0.8
"""auto-skip に必要な正答率。比較は 4/5 以上として分数で行う。"""

MIN_CONFIRMATION_SPAN_DAYS = 2
"""最初の正解から最後の正解までの最短日数。同一セッションの連打では足りない。"""

RECENT_INCORRECT_DAYS = 14
"""この日数以内の誤答があると、その direction は auto-skip しない。"""

EXPLICIT_KNOWN_REMOVES_DUE_REVIEWS = False
"""explicit known は due review を消さない。新規学習だけを外す。"""

KnownItemAction = Literal["mark_known", "clear_known"]

AutoSkipReasonCode = Literal[
    "AUTO_SKIP",
    "INSUFFICIENT_HISTORY",
    "RECENT_INCORRECT",
]


class InvalidKnownItemInputError(ValueError):
    """known-item policy の入力が不正。"""


class KnownItemEvent(BaseModel):
    """explicit known の操作履歴。append-only。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    learning_item_id: str = Field(min_length=1)
    action: KnownItemAction
    occurred_at: datetime


class KnownItemOverride(BaseModel):
    """explicit known の現在値。履歴を畳んだ結果であり、mastered ではない。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    learning_item_id: str = Field(min_length=1)
    active: bool
    updated_at: datetime


class AutoSkipDecision(BaseModel):
    """1 direction の auto-skip。永続化しない。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    skill_direction: SkillDirection
    skip_new: bool
    reason_code: AutoSkipReasonCode


def next_explicit_known(
    current: KnownItemOverride | None,
    *,
    learning_item_id: str,
    action: KnownItemAction,
    occurred_at: datetime,
    event_id: str,
) -> tuple[KnownItemEvent | None, KnownItemOverride | None]:
    """明示的 known の次の状態を返す。変化がなければ event は None。

    同じ状態への mark / clear は履歴を足さない。現在の override は変更しない。
    """

    if not learning_item_id.strip() or not event_id.strip():
        raise InvalidKnownItemInputError("learning_item_id と event_id が必要")
    aware = _require_aware_utc(occurred_at)
    if current is not None and current.learning_item_id != learning_item_id:
        raise InvalidKnownItemInputError(
            "KnownItemOverride の learning_item_id が一致しない: "
            f"current={current.learning_item_id}, requested={learning_item_id}"
        )
    active = current is not None and current.active
    if action == "mark_known":
        if active:
            return None, current
        return _known_change(
            learning_item_id,
            action="mark_known",
            active=True,
            occurred_at=aware,
            event_id=event_id,
        )
    if not active:
        return None, current
    return _known_change(
        learning_item_id,
        action="clear_known",
        active=False,
        occurred_at=aware,
        event_id=event_id,
    )


def decide_auto_skip(
    *,
    skill_direction: SkillDirection,
    events: Sequence[LearningEvent],
    now: datetime,
) -> AutoSkipDecision:
    """その direction の新規学習を auto-skip するか。

    正解回数、正答率、確認の期間、最近の誤答をすべて満たすときだけ skip する。
    他 direction の履歴は見ない。
    """

    aware_now = _require_aware_utc(now)
    _require_direction_events(skill_direction, events)
    sufficient = _history_is_sufficient(events)
    if _has_recent_incorrect(events, aware_now) and sufficient:
        return _auto_skip_decision(skill_direction, False, "RECENT_INCORRECT")
    if not sufficient:
        return _auto_skip_decision(skill_direction, False, "INSUFFICIENT_HISTORY")
    return _auto_skip_decision(skill_direction, True, "AUTO_SKIP")


def should_drop_today_candidate(
    *,
    activity_kind: ActivityKind,
    explicit_known: bool,
    auto_skip_new: bool,
) -> bool:
    """今日の候補から外すか。

    review は、``EXPLICIT_KNOWN_REMOVES_DUE_REVIEWS`` が False のあいだ外さない。
    auto-skip は review を消さない。new_practice だけを、明示的 known または
    その direction の auto-skip で外す。
    """

    if activity_kind == "review":
        return EXPLICIT_KNOWN_REMOVES_DUE_REVIEWS and explicit_known
    if activity_kind != "new_practice":
        return False
    return explicit_known or auto_skip_new


def _known_change(
    learning_item_id: str,
    *,
    action: KnownItemAction,
    active: bool,
    occurred_at: datetime,
    event_id: str,
) -> tuple[KnownItemEvent, KnownItemOverride]:
    event = KnownItemEvent(
        id=event_id,
        learning_item_id=learning_item_id,
        action=action,
        occurred_at=occurred_at,
    )
    override = KnownItemOverride(
        learning_item_id=learning_item_id,
        active=active,
        updated_at=occurred_at,
    )
    return event, override


def _auto_skip_decision(
    skill_direction: SkillDirection,
    skip_new: bool,
    reason_code: AutoSkipReasonCode,
) -> AutoSkipDecision:
    return AutoSkipDecision(
        skill_direction=skill_direction,
        skip_new=skip_new,
        reason_code=reason_code,
    )


def _require_direction_events(
    skill_direction: SkillDirection,
    events: Sequence[LearningEvent],
) -> None:
    item_ids = {event.learning_item_id for event in events}
    if len(item_ids) > 1:
        raise InvalidKnownItemInputError(
            "auto-skip は同一 LearningItem の event だけを受け取る: "
            f"item_ids={sorted(item_ids)}"
        )
    for event in events:
        mapped = skill_direction_for_event(event)
        if mapped != skill_direction:
            raise InvalidKnownItemInputError(
                "auto-skip の event が SkillDirection と一致しない: "
                f"direction={skill_direction}, exercise_type={event.exercise_type}"
            )


def _history_is_sufficient(events: Sequence[LearningEvent]) -> bool:
    correct = [event for event in events if event.result == "correct"]
    if len(correct) < MIN_CORRECT_COUNT:
        return False
    score = len(correct) / len(events)
    if score + 1e-12 < MIN_MASTERY_SCORE:
        return False
    times = sorted(_occurred(event) for event in correct)
    span = times[-1] - times[0]
    return span >= timedelta(days=MIN_CONFIRMATION_SPAN_DAYS)


def _has_recent_incorrect(events: Sequence[LearningEvent], now: datetime) -> bool:
    window_start = now - timedelta(days=RECENT_INCORRECT_DAYS)
    return any(
        event.result == "incorrect" and _occurred(event) >= window_start
        for event in events
    )


def _occurred(event: LearningEvent) -> datetime:
    return _require_aware_utc(event.occurred_at)


def _require_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise InvalidKnownItemInputError("timezone-aware な datetime が必要")
    return value.astimezone(UTC)
