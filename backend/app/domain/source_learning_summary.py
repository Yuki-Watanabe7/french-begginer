"""Source 単位の学習成果サマリー（Issue #205 / Phase 7）。

この Source に関連する LearningItem の、いまの状態を数える。
「この Source のおかげで習得した」とは読まない。

関連の定義:
  - LearningItem は、SourceRef の source_document_id がこの Source と
    一致するとき、その Source の関連 item である。
  - 同じ item が複数 Source に紐づく場合、各 Source のサマリーに現れる。
  - 1つの Source の中では item を1回だけ数える。SourceRef が重複しても、
    採用候補が複数でも、LearningEvent / LearnerState は足し直さない。
  - Source ごとのサマリーを足すと、複数 Source にまたがる item の
    成果が重複する。横断合計はこの契約に含めない。

件数:
  - candidate_count: この Source の Candidate 全件。
  - pending_candidate_count: status が candidate のもの。
  - accepted_candidate_count: status が accepted のもの。
  - rejected_item_count: status が rejected の Candidate 件数。
    LearningItem にはならない。名前は Issue の契約に合わせる。
  - accepted_item_count: 関連 LearningItem のユニーク件数。
    手入力で SourceRef を付けた item も含む。
  - unseen_item_count: 関連 item のうち、未回答で、mastered でも
    explicit known でも suspended でもないもの。
  - active_item_count: status が active、explicit known ではなく、
    回答が1件以上あるもの。
  - suspended_item_count: explicit known と mastered を除いた suspended。
  - mastered_or_known_count: status が mastered、または explicit known。
    両方でも1件。known は status を変えない。
  - started_item_count: 回答が1件以上ある関連 item。
  - due_direction_count: status が active の関連 item について、
    due_at <= now の direction 数。item ごとに direction は最大1。
    explicit known でも due は残す。mastered / suspended は数えない。

正答率と direction 集計の source of truth は LearnerState。
Event を SourceRef の数だけ replay しない。
by_direction に無い legacy event は全体の attempts にだけ残る。
correct_rate は未回答なら None。0 件を 0% とは扱わない。
recent_activity_at は関連 item の last_reviewed_at の最大値。
known の更新時刻は学習活動にしない。

SourceType では分岐しない。壁時計は呼ばない。now は呼び出し側が渡す。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence, Set
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.tutor import (
    CandidateStatus,
    LearnerState,
    LearningItem,
    LearningItemCandidate,
    ReviewSchedule,
    SkillDirection,
    UtcDatetime,
)

POLICY_VERSION = "source-learning-summary-v1"
"""集計規則の版。件数の意味を変えるときは bump する。"""

ATTRIBUTION = "related_item_current_state"
"""成果の読み方。因果帰属ではなく、関連 item の現在状態。"""

DUE_ITEM_STATUS = "active"
"""due に数える LearningItem.status。review queue の active と同じ。"""

_DIRECTIONS: tuple[SkillDirection, ...] = ("recognition", "production")

_ItemBucket = Literal["unseen", "active", "suspended", "mastered_or_known"]


class InvalidSourceLearningInputError(ValueError):
    """Source 学習サマリーの入力が不正。"""


class DirectionLearningSummary(BaseModel):
    """1つの SkillDirection に閉じた、関連 item の現在状態。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    skill_direction: SkillDirection
    attempt_count: int = Field(ge=0)
    correct_count: int = Field(ge=0)
    correct_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    due_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _check_rate(self) -> DirectionLearningSummary:
        if self.correct_count > self.attempt_count:
            raise ValueError("correct_count が attempt_count を超えている")
        expected = _correct_rate(self.correct_count, self.attempt_count)
        if self.correct_rate != expected:
            raise ValueError(
                "correct_rate が correct_count / attempt_count と一致しない"
            )
        return self


class SourceLearningSummary(BaseModel):
    """1つの Source に関連する学習の、いまの状態。

    attribution は常に related_item_current_state。
    複数 Source の summary を合計して全体成果にしてはならない。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    attribution: Literal["related_item_current_state"] = ATTRIBUTION
    candidate_count: int = Field(ge=0)
    pending_candidate_count: int = Field(ge=0)
    accepted_candidate_count: int = Field(ge=0)
    accepted_item_count: int = Field(ge=0)
    rejected_item_count: int = Field(ge=0)
    unseen_item_count: int = Field(ge=0)
    active_item_count: int = Field(ge=0)
    suspended_item_count: int = Field(ge=0)
    mastered_or_known_count: int = Field(ge=0)
    started_item_count: int = Field(ge=0)
    due_direction_count: int = Field(ge=0)
    attempts: int = Field(ge=0)
    correct_count: int = Field(ge=0)
    correct_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    recognition: DirectionLearningSummary
    production: DirectionLearningSummary
    recent_activity_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _check_totals(self) -> SourceLearningSummary:
        if self.policy_version != POLICY_VERSION:
            raise ValueError(
                "policy_version が source learning summary の版と一致しない"
            )
        if self.attribution != ATTRIBUTION:
            raise ValueError("attribution は関連 item の現在状態で固定")
        candidate_total = (
            self.pending_candidate_count
            + self.accepted_candidate_count
            + self.rejected_item_count
        )
        if self.candidate_count != candidate_total:
            raise ValueError("candidate_count が status 別の合計と一致しない")
        item_total = (
            self.unseen_item_count
            + self.active_item_count
            + self.suspended_item_count
            + self.mastered_or_known_count
        )
        if self.accepted_item_count != item_total:
            raise ValueError("accepted_item_count が状態別の合計と一致しない")
        if self.active_item_count > self.started_item_count:
            raise ValueError("active_item_count が学習開始済みを超えている")
        if self.started_item_count > self.accepted_item_count:
            raise ValueError("started_item_count が関連 item を超えている")
        if self.attempts < self.started_item_count:
            raise ValueError("attempts が学習開始済み item 数より少ない")
        if self.correct_count > self.attempts:
            raise ValueError("correct_count が attempts を超えている")
        if self.correct_rate != _correct_rate(self.correct_count, self.attempts):
            raise ValueError("correct_rate が correct_count / attempts と一致しない")
        if self.attempts == 0 and self.recent_activity_at is not None:
            raise ValueError("未回答の Source に recent_activity_at は置けない")
        if self.attempts > 0 and self.recent_activity_at is None:
            raise ValueError("回答済みの Source には recent_activity_at が必要")
        if self.recognition.skill_direction != "recognition":
            raise ValueError("recognition の skill_direction が一致しない")
        if self.production.skill_direction != "production":
            raise ValueError("production の skill_direction が一致しない")
        direction_due = self.recognition.due_count + self.production.due_count
        if self.due_direction_count != direction_due:
            raise ValueError(
                "due_direction_count が direction 別 due の合計と一致しない"
            )
        if self.due_direction_count > self.accepted_item_count * len(_DIRECTIONS):
            raise ValueError(
                "due_direction_count が関連 item の direction 数を超えている"
            )
        direction_attempts = (
            self.recognition.attempt_count + self.production.attempt_count
        )
        if direction_attempts > self.attempts:
            raise ValueError("direction 別の回答数が全体の attempts を超えている")
        return self


def summarize_source_learning(
    source_id: str,
    *,
    candidates: Sequence[LearningItemCandidate],
    items: Sequence[LearningItem],
    states: Mapping[str, LearnerState | None],
    schedules: Mapping[str, Sequence[ReviewSchedule]],
    known_item_ids: Set[str],
    now: datetime,
) -> SourceLearningSummary:
    """関連 item の現在状態を1つの SourceLearningSummary にする。

    入力の item / candidate は変更しない。同じ入力と now から同じ結果になる。
    """

    if not source_id.strip():
        raise InvalidSourceLearningInputError("source_id が必要")
    aware_now = _as_utc(now)
    candidate_counts = _count_candidates(source_id, candidates)
    related = _related_items(source_id, items)
    buckets: dict[_ItemBucket, int] = {
        "unseen": 0,
        "active": 0,
        "suspended": 0,
        "mastered_or_known": 0,
    }
    started = 0
    attempts = 0
    correct_count = 0
    direction_attempts = {direction: 0 for direction in _DIRECTIONS}
    direction_correct = {direction: 0 for direction in _DIRECTIONS}
    direction_due = {direction: 0 for direction in _DIRECTIONS}
    activity_at: list[datetime] = []

    for item in related:
        state = _state_for(item, states)
        item_attempts = 0 if state is None else state.attempt_count
        item_correct = 0 if state is None else state.correct_count
        attempts += item_attempts
        correct_count += item_correct
        if item_attempts > 0:
            started += 1
        if state is not None and state.last_reviewed_at is not None:
            activity_at.append(state.last_reviewed_at)
        _add_direction_stats(state, direction_attempts, direction_correct)
        due = _due_directions(item, schedules.get(item.id, ()), aware_now)
        for direction in due:
            direction_due[direction] += 1
        buckets[_bucket(item, item_attempts, item.id in known_item_ids)] += 1

    recent = max(activity_at) if activity_at else None
    return SourceLearningSummary(
        source_id=source_id,
        policy_version=POLICY_VERSION,
        attribution=ATTRIBUTION,
        candidate_count=candidate_counts["all"],
        pending_candidate_count=candidate_counts["candidate"],
        accepted_candidate_count=candidate_counts["accepted"],
        accepted_item_count=len(related),
        rejected_item_count=candidate_counts["rejected"],
        unseen_item_count=buckets["unseen"],
        active_item_count=buckets["active"],
        suspended_item_count=buckets["suspended"],
        mastered_or_known_count=buckets["mastered_or_known"],
        started_item_count=started,
        due_direction_count=sum(direction_due.values()),
        attempts=attempts,
        correct_count=correct_count,
        correct_rate=_correct_rate(correct_count, attempts),
        recognition=_direction_summary(
            "recognition",
            direction_attempts["recognition"],
            direction_correct["recognition"],
            direction_due["recognition"],
        ),
        production=_direction_summary(
            "production",
            direction_attempts["production"],
            direction_correct["production"],
            direction_due["production"],
        ),
        recent_activity_at=recent,
    )


def _count_candidates(
    source_id: str, candidates: Sequence[LearningItemCandidate]
) -> dict[str, int]:
    counts: dict[str, int] = {
        "all": 0,
        "candidate": 0,
        "accepted": 0,
        "rejected": 0,
    }
    seen: set[str] = set()
    for candidate in candidates:
        if candidate.source_document_id != source_id:
            raise InvalidSourceLearningInputError(
                "別 Source の Candidate は集計できない: "
                f"candidate={candidate.id}, source={candidate.source_document_id}"
            )
        if candidate.id in seen:
            raise InvalidSourceLearningInputError(
                f"LearningItemCandidate が重複している: id={candidate.id}"
            )
        seen.add(candidate.id)
        status: CandidateStatus = candidate.status
        counts["all"] += 1
        counts[status] += 1
    return counts


def _related_items(source_id: str, items: Sequence[LearningItem]) -> list[LearningItem]:
    related: list[LearningItem] = []
    seen: set[str] = set()
    for item in items:
        if item.id in seen:
            raise InvalidSourceLearningInputError(
                f"LearningItem が重複している: id={item.id}"
            )
        seen.add(item.id)
        if any(ref.source_document_id == source_id for ref in item.source_refs):
            related.append(item)
    return related


def _state_for(
    item: LearningItem, states: Mapping[str, LearnerState | None]
) -> LearnerState | None:
    state = states.get(item.id)
    if state is not None and state.learning_item_id != item.id:
        raise InvalidSourceLearningInputError(
            "LearnerState の learning_item_id が一致しない: "
            f"state={state.learning_item_id}, item={item.id}"
        )
    if state is not None:
        direction_attempts = sum(
            stats.attempt_count for stats in state.by_direction.values()
        )
        if direction_attempts > state.attempt_count:
            raise InvalidSourceLearningInputError(
                f"by_direction の回答数が LearnerState 全体を超えている: item={item.id}"
            )
    return state


def _add_direction_stats(
    state: LearnerState | None,
    attempts: dict[SkillDirection, int],
    correct: dict[SkillDirection, int],
) -> None:
    if state is None:
        return
    for direction in _DIRECTIONS:
        stats = state.by_direction.get(direction)
        if stats is None:
            continue
        attempts[direction] += stats.attempt_count
        correct[direction] += stats.correct_count


def _due_directions(
    item: LearningItem,
    schedules: Sequence[ReviewSchedule],
    now: datetime,
) -> set[SkillDirection]:
    seen: set[SkillDirection] = set()
    due: set[SkillDirection] = set()
    for schedule in schedules:
        if schedule.learning_item_id != item.id:
            raise InvalidSourceLearningInputError(
                "ReviewSchedule の learning_item_id が一致しない: "
                f"schedule={schedule.learning_item_id}, item={item.id}"
            )
        if schedule.skill_direction in seen:
            raise InvalidSourceLearningInputError(
                "ReviewSchedule の direction が重複している: "
                f"item={item.id}, direction={schedule.skill_direction}"
            )
        seen.add(schedule.skill_direction)
        if item.status == DUE_ITEM_STATUS and schedule.due_at <= now:
            due.add(schedule.skill_direction)
    return due


def _bucket(item: LearningItem, attempts: int, known: bool) -> _ItemBucket:
    if known or item.status == "mastered":
        return "mastered_or_known"
    if item.status == "suspended":
        return "suspended"
    if attempts == 0:
        return "unseen"
    return "active"


def _direction_summary(
    direction: SkillDirection,
    attempt_count: int,
    correct_count: int,
    due_count: int,
) -> DirectionLearningSummary:
    return DirectionLearningSummary(
        skill_direction=direction,
        attempt_count=attempt_count,
        correct_count=correct_count,
        correct_rate=_correct_rate(correct_count, attempt_count),
        due_count=due_count,
    )


def _correct_rate(correct_count: int, attempt_count: int) -> float | None:
    if attempt_count == 0:
        return None
    return correct_count / attempt_count


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise InvalidSourceLearningInputError("now は timezone-aware である必要がある")
    return value.astimezone(UTC)
