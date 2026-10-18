"""復習負債と直近の学習状態から、今日の件数を小さく調整する（Issue #204）。

Phase 5 の Daily Learning Plan は、渡された `total_count` / `max_new_count`
の中で due を優先する。このモジュールはその件数だけを決める。
順位、due 優先、admission の選別は変えない。

```text
due / overdue / deferred
+ recent error / sessions / imbalance / volume
+ admission budget
  -> AdaptivePlanConstraints
  -> PlanConstraints
  -> build_daily_learning_plan()
```

このモジュールが依存してよいのは Python 標準ライブラリ、Pydantic、
`domain.tutor`、`domain.recommendation_signal`、`domain.daily_learning_plan`
のみ。DB / FastAPI / OpenAI には依存しない。wall clock は呼ばない。

## 優先順位

1. 自動算出の total は 5〜10、max_new は 0〜3。この範囲を超えて増やさない。
2. 呼び出し側が `explicit_total_count` / `explicit_max_new_count` を渡した
   フィールドは、自動算出より優先する。範囲は Plan と同じ 1〜20 / 0〜20。
   範囲外はクランプせず拒否する。
3. 未指定のフィールドだけ自動算出を使う。
4. admission で入れなかった新規は、ここでの max_new を広げても Plan に戻らない。
5. 件数を決めたあとの due 優先と deferred は Phase 5 のまま。

欠測（履歴なし、session なし、admission budget 不明）は中立で、
デフォルトの 10 問・新規 3 件に戻す。1 件の誤答だけでは変えない。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.daily_learning_plan import (
    DEFAULT_MAX_NEW_COUNT,
    DEFAULT_PLAN_SIZE,
    MAX_PLAN_SIZE,
    MIN_PLAN_SIZE,
)
from app.domain.recommendation_signal import RecommendationSignalSnapshot
from app.domain.tutor import LearningEvent

# ---------------------------------------------------------------------------
# 定数（閾値はここだけを変えて調整する）
# ---------------------------------------------------------------------------

POLICY_VERSION = "adaptive-plan-v1"
"""このモジュールが書き込む policy_version。調整規則の変更時は bump する。"""

ADAPTIVE_DEFAULT_TOTAL = DEFAULT_PLAN_SIZE
"""自動算出の基準。Phase 5 のデフォルト問題数と揃える。"""

ADAPTIVE_DEFAULT_NEW = DEFAULT_MAX_NEW_COUNT
"""自動算出の基準。Phase 5 のデフォルト新規上限と揃える。"""

ADAPTIVE_MIN_TOTAL = 5
"""自動算出が短くできる下限。1 問までは落とさない。"""

ADAPTIVE_MAX_TOTAL = ADAPTIVE_DEFAULT_TOTAL
"""自動算出の上限。難しかった日に問題数を増やさない。"""

ADAPTIVE_MIN_NEW = 0
ADAPTIVE_MAX_NEW = ADAPTIVE_DEFAULT_NEW
"""自動算出の新規上限。デフォルト枠より増やさない。"""

TOTAL_REDUCTION_STEP = 2
"""1 回の調整で短くする問題数。"""

DUE_BACKLOG_SOFT = 8
"""due direction がこれ以上なら新規を 1 件まで。admission の soft と同じ。"""

DUE_BACKLOG_HARD = 16
"""due direction がこれ以上なら新規を 0。admission の hard と同じ。"""

OVERDUE_MIN_DAYS = 1.0
"""これ以上遅れている due を overdue として数える。"""

OVERDUE_SOFT = 4
OVERDUE_HARD = 8

DEFERRED_SOFT = 4
"""安全な 1 日分に入りきらない due がこれ以上なら soft backlog。"""

DEFERRED_HARD = 8

MIN_ATTEMPTS_FOR_SOFT_ERROR = 5
"""これ未満の誤答率は見ない。1 件の誤答では変えない。"""

MIN_ATTEMPTS_FOR_HARD_ERROR = 8
"""hard まで下げるのに必要な直近 attempt。"""

ERROR_RATE_SOFT = 0.5
ERROR_RATE_HARD = 0.75

SOFT_MAX_NEW = 2
"""soft 圧力のときの新規上限。デフォルトから 1 段だけ下げる。"""

HARD_MAX_NEW = 1
"""hard 圧力のときの新規上限。誤答だけでは 0 にしない。"""

SUPPRESSED_MAX_NEW = 0
"""hard backlog、または admission budget 0 のときの新規上限。"""

CONSECUTIVE_DIFFICULT_SOFT = 2
"""難しい session がこれだけ続いたら soft。1 回では数えない。"""

CONSECUTIVE_DIFFICULT_HARD = 3

SESSION_GAP = timedelta(minutes=45)
"""この間隔を超えたら別 session。同じ間隔までは 1 session。"""

RECENT_SESSION_WINDOW_DAYS = 14
STUDY_VOLUME_WINDOW_DAYS = 1

COMPLETE_SESSION_MIN_ATTEMPTS = 5
"""これ未満の session は途中で終わったものとして数える。"""

DIFFICULT_SESSION_MIN_ATTEMPTS = 4
"""これ未満の session は難しいとも易しいとも判定しない。"""

DIFFICULT_SESSION_ERROR_RATE = 0.5

MIN_SESSIONS_FOR_COMPLETION = 2
LOW_COMPLETION_RATE = 0.5
HIGH_STUDY_VOLUME = 20
"""直近 1 日の attempt がこれ以上なら、誤答圧力がある日だけ総量を 1 段下げる。"""

IMBALANCE_THRESHOLD = 0.4
MIN_IMBALANCE_SAMPLES = 2
"""両 direction を学習済みの Item がこれ未満なら、偏りでは調整しない。"""

AdaptivePlanReasonCode = Literal[
    "HIGH_REVIEW_BACKLOG",
    "RECENT_ERROR_RATE_HIGH",
    "STABLE_PROGRESS",
    "NEW_ADMISSION_LIMITED",
]

_REASON_ORDER: tuple[AdaptivePlanReasonCode, ...] = (
    "HIGH_REVIEW_BACKLOG",
    "RECENT_ERROR_RATE_HIGH",
    "NEW_ADMISSION_LIMITED",
    "STABLE_PROGRESS",
)


class InvalidAdaptivePlanInputError(ValueError):
    """明示件数や signal の組み合わせが不正。"""


# ---------------------------------------------------------------------------
# 入出力
# ---------------------------------------------------------------------------


class AdaptivePlanSignals(BaseModel):
    """負荷調整の入力。欠測は None または 0 で、苦手とは解釈しない。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    due_count: int = Field(default=0, ge=0)
    overdue_count: int = Field(default=0, ge=0)
    deferred_due_count: int = Field(default=0, ge=0)
    recent_error_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    recent_attempt_count: int = Field(default=0, ge=0)
    recent_session_completion_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    recent_session_count: int = Field(default=0, ge=0)
    recognition_production_imbalance: float | None = Field(
        default=None, ge=-1.0, le=1.0
    )
    """recognition mastery - production mastery の平均。不明は None。"""
    imbalance_sample_count: int = Field(default=0, ge=0)
    consecutive_difficult_sessions: int = Field(default=0, ge=0)
    recent_study_volume: int = Field(default=0, ge=0)
    admission_budget: int | None = Field(default=None, ge=0)
    """None は admission 未計算。0 は新規枠なし。通常枠より広い値は絞らない。"""

    @model_validator(mode="after")
    def _overdue_is_subset_of_due(self) -> AdaptivePlanSignals:
        if self.overdue_count > self.due_count:
            raise ValueError("overdue_count は due_count を超えない")
        return self


class AdaptivePlanConstraints(BaseModel):
    """今日の Plan に渡す件数と、その理由。永続化しない。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    total_count: int = Field(ge=MIN_PLAN_SIZE, le=MAX_PLAN_SIZE)
    max_new_count: int = Field(ge=0, le=MAX_PLAN_SIZE)
    reason_codes: tuple[AdaptivePlanReasonCode, ...]
    policy_version: str = POLICY_VERSION

    @model_validator(mode="after")
    def _reasons_are_ordered(self) -> AdaptivePlanConstraints:
        if not self.reason_codes:
            raise ValueError("reason_codes は 1 つ以上")
        if list(self.reason_codes) != sorted(
            self.reason_codes, key=_REASON_ORDER.index
        ):
            raise ValueError("reason_codes は固定順")
        if "STABLE_PROGRESS" in self.reason_codes and len(self.reason_codes) != 1:
            raise ValueError("STABLE_PROGRESS は他の理由と併記しない")
        return self


# ---------------------------------------------------------------------------
# 決定
# ---------------------------------------------------------------------------


def decide_adaptive_plan_constraints(
    signals: AdaptivePlanSignals,
    *,
    explicit_total_count: int | None = None,
    explicit_max_new_count: int | None = None,
) -> AdaptivePlanConstraints:
    """同じ signal なら同じ件数と reason を返す。

    明示されたフィールドだけ自動算出を置き換える。未指定は自動算出のまま。
    """
    total, max_new, reasons = _suggest(signals)
    if explicit_total_count is not None:
        _require_explicit_total(explicit_total_count)
        total = explicit_total_count
    if explicit_max_new_count is not None:
        _require_explicit_new(explicit_max_new_count)
        max_new = explicit_max_new_count
    return AdaptivePlanConstraints(
        total_count=total,
        max_new_count=max_new,
        reason_codes=reasons,
        policy_version=POLICY_VERSION,
    )


def describe_load_adjustment(
    constraints: AdaptivePlanConstraints,
    *,
    total_was_adaptive: bool,
    new_was_adaptive: bool,
) -> str:
    """自動調整をユーザー向けの文にする。明示指定だけなら空。

    STABLE_PROGRESS のときは Phase 5 の配分説明だけで足りる。
    """
    if constraints.reason_codes == ("STABLE_PROGRESS",):
        return ""
    reasons = set(constraints.reason_codes)
    clauses: list[str] = []
    if new_was_adaptive:
        if "HIGH_REVIEW_BACKLOG" in reasons:
            clauses.append("復習が溜まっている")
        if "RECENT_ERROR_RATE_HIGH" in reasons:
            clauses.append("最近の誤答が続いている")
        if "NEW_ADMISSION_LIMITED" in reasons:
            clauses.append("新しい項目を入れられる枠が狭い")
    parts: list[str] = []
    if clauses:
        parts.append(f"{'、'.join(clauses)}ため、新しい項目を減らしました")
    if total_was_adaptive and constraints.total_count < ADAPTIVE_DEFAULT_TOTAL:
        parts.append("今日の問題数も少し抑えました")
    if not parts:
        return ""
    return "。".join(parts) + "。"


def _suggest(
    signals: AdaptivePlanSignals,
) -> tuple[int, int, tuple[AdaptivePlanReasonCode, ...]]:
    backlog_level = _backlog_level(signals)
    error_level = _error_level(signals)
    max_new = ADAPTIVE_DEFAULT_NEW
    if backlog_level >= 2:
        max_new = SUPPRESSED_MAX_NEW
    elif backlog_level == 1:
        max_new = HARD_MAX_NEW
    if error_level >= 2:
        max_new = min(max_new, HARD_MAX_NEW)
    elif error_level == 1:
        max_new = min(max_new, SOFT_MAX_NEW)
    if backlog_level > 0 or error_level > 0:
        max_new = _tighten_for_imbalance(max_new, signals)

    reasons: list[AdaptivePlanReasonCode] = []
    if backlog_level > 0:
        reasons.append("HIGH_REVIEW_BACKLOG")
    if error_level > 0:
        reasons.append("RECENT_ERROR_RATE_HIGH")
    max_new = _apply_admission_budget(max_new, signals, reasons)

    total = ADAPTIVE_DEFAULT_TOTAL
    shorten = _should_shorten_day(
        signals, error_level=error_level, backlog_level=backlog_level
    )
    if shorten:
        total = max(ADAPTIVE_MIN_TOTAL, ADAPTIVE_DEFAULT_TOTAL - TOTAL_REDUCTION_STEP)
    if not reasons:
        reasons.append("STABLE_PROGRESS")

    total = _clamp(total, ADAPTIVE_MIN_TOTAL, ADAPTIVE_MAX_TOTAL)
    max_new = _clamp(max_new, ADAPTIVE_MIN_NEW, ADAPTIVE_MAX_NEW)
    return total, max_new, tuple(reasons)


def _backlog_level(signals: AdaptivePlanSignals) -> int:
    if (
        signals.due_count >= DUE_BACKLOG_HARD
        or signals.overdue_count >= OVERDUE_HARD
        or signals.deferred_due_count >= DEFERRED_HARD
    ):
        return 2
    if (
        signals.due_count >= DUE_BACKLOG_SOFT
        or signals.overdue_count >= OVERDUE_SOFT
        or signals.deferred_due_count >= DEFERRED_SOFT
    ):
        return 1
    return 0


def _error_level(signals: AdaptivePlanSignals) -> int:
    """attempt が足りない誤答率は中立。連続 session は 2 回目から数える。"""
    level = 0
    rate = signals.recent_error_rate
    attempts = signals.recent_attempt_count
    if rate is not None and attempts >= MIN_ATTEMPTS_FOR_HARD_ERROR:
        if rate >= ERROR_RATE_HARD:
            level = 2
    if (
        level < 2
        and rate is not None
        and attempts >= MIN_ATTEMPTS_FOR_SOFT_ERROR
        and rate >= ERROR_RATE_SOFT
    ):
        level = max(level, 1)
    streak = signals.consecutive_difficult_sessions
    if streak >= CONSECUTIVE_DIFFICULT_HARD:
        level = max(level, 2)
    elif streak >= CONSECUTIVE_DIFFICULT_SOFT:
        level = max(level, 1)
    return level


def _tighten_for_imbalance(max_new: int, signals: AdaptivePlanSignals) -> int:
    """既に新規を絞っているときだけ、偏りでさらに 1 段下げる。0 にはしない。"""
    gap = signals.recognition_production_imbalance
    if max_new < SOFT_MAX_NEW or gap is None:
        return max_new
    if signals.imbalance_sample_count < MIN_IMBALANCE_SAMPLES:
        return max_new
    if abs(gap) < IMBALANCE_THRESHOLD:
        return max_new
    return max_new - 1


def _apply_admission_budget(
    max_new: int,
    signals: AdaptivePlanSignals,
    reasons: list[AdaptivePlanReasonCode],
) -> int:
    """admission の在庫がデフォルト新規枠より狭いときだけ合わせる。"""
    budget = signals.admission_budget
    if budget is None or budget >= ADAPTIVE_DEFAULT_NEW:
        return max_new
    reasons.append("NEW_ADMISSION_LIMITED")
    return min(max_new, budget)


def _should_shorten_day(
    signals: AdaptivePlanSignals,
    *,
    error_level: int,
    backlog_level: int,
) -> bool:
    """backlog が大きい日は総量を維持し、overdue を枠の外に押し出さない。

    総量を 1 段下げるのは、誤答圧力に加えて session・量の裏付けがあるときだけ。
    """
    if backlog_level > 0 or error_level == 0:
        return False
    if signals.consecutive_difficult_sessions >= CONSECUTIVE_DIFFICULT_SOFT:
        return True
    if signals.recent_study_volume >= HIGH_STUDY_VOLUME:
        return True
    completion = signals.recent_session_completion_rate
    return (
        signals.recent_session_count >= MIN_SESSIONS_FOR_COMPLETION
        and completion is not None
        and completion < LOW_COMPLETION_RATE
    )


def _require_explicit_total(value: int) -> None:
    if not MIN_PLAN_SIZE <= value <= MAX_PLAN_SIZE:
        raise InvalidAdaptivePlanInputError(
            f"total_count は {MIN_PLAN_SIZE}〜{MAX_PLAN_SIZE}: {value}"
        )


def _require_explicit_new(value: int) -> None:
    if not 0 <= value <= MAX_PLAN_SIZE:
        raise InvalidAdaptivePlanInputError(
            f"max_new_count は 0〜{MAX_PLAN_SIZE}: {value}"
        )


def _clamp(value: int, lower: int, upper: int) -> int:
    return max(lower, min(upper, value))


# ---------------------------------------------------------------------------
# signal の収集
# ---------------------------------------------------------------------------


def collect_adaptive_plan_signals(
    snapshots: Sequence[RecommendationSignalSnapshot],
    events: Sequence[LearningEvent],
    *,
    admission_budget: int | None,
    now: datetime,
    deferred_due_count: int | None = None,
) -> AdaptivePlanSignals:
    """snapshot と event から負荷 signal を作る。now は呼び出し側が渡す。

    `deferred_due_count` を省略したときは、due が自動算出の上限に入りきらない
    件数を使う。Plan を先に組み立てないので、結果の件数には依存しない。
    """
    aware_now = _require_aware_utc(now)
    due_count = 0
    overdue_count = 0
    incorrect = 0
    attempts = 0
    gaps: list[float] = []
    for snapshot in snapshots:
        for signal in snapshot.by_direction.values():
            if signal.review_urgency == "due":
                due_count += 1
                if signal.overdue_days >= OVERDUE_MIN_DAYS:
                    overdue_count += 1
            incorrect += signal.recent_incorrect_count
            attempts += signal.recent_incorrect_count + signal.recent_correct_count
        if snapshot.production_gap is not None:
            gaps.append(snapshot.production_gap)

    if deferred_due_count is None:
        deferred = max(0, due_count - ADAPTIVE_MAX_TOTAL)
    else:
        deferred = deferred_due_count

    sessions = _recent_sessions(events, now=aware_now)
    completion_rate: float | None = None
    if sessions:
        completed = sum(
            1 for session in sessions if len(session) >= COMPLETE_SESSION_MIN_ATTEMPTS
        )
        completion_rate = completed / len(sessions)

    imbalance: float | None = None
    if gaps:
        imbalance = sum(gaps) / len(gaps)

    return AdaptivePlanSignals(
        due_count=due_count,
        overdue_count=overdue_count,
        deferred_due_count=deferred,
        recent_error_rate=(incorrect / attempts) if attempts else None,
        recent_attempt_count=attempts,
        recent_session_completion_rate=completion_rate,
        recent_session_count=len(sessions),
        recognition_production_imbalance=imbalance,
        imbalance_sample_count=len(gaps),
        consecutive_difficult_sessions=_consecutive_difficult_sessions(sessions),
        recent_study_volume=_study_volume(events, now=aware_now),
        admission_budget=admission_budget,
    )


def _recent_sessions(
    events: Sequence[LearningEvent],
    *,
    now: datetime,
) -> list[list[LearningEvent]]:
    window_start = now - timedelta(days=RECENT_SESSION_WINDOW_DAYS)
    usable = [
        event
        for event in events
        if window_start <= _require_aware_utc(event.occurred_at) <= now
    ]
    usable.sort(key=lambda event: (_require_aware_utc(event.occurred_at), event.id))
    sessions: list[list[LearningEvent]] = []
    current: list[LearningEvent] = []
    last: datetime | None = None
    for event in usable:
        occurred = _require_aware_utc(event.occurred_at)
        if last is not None and occurred - last > SESSION_GAP:
            sessions.append(current)
            current = []
        current.append(event)
        last = occurred
    if current:
        sessions.append(current)
    return sessions


def _consecutive_difficult_sessions(sessions: Sequence[Sequence[LearningEvent]]) -> int:
    """新しい session から数える。attempt 不足の session は挟まっても打ち切らない。"""
    streak = 0
    for session in reversed(sessions):
        judged = _session_is_difficult(session)
        if judged is None:
            continue
        if not judged:
            break
        streak += 1
    return streak


def _session_is_difficult(session: Sequence[LearningEvent]) -> bool | None:
    if len(session) < DIFFICULT_SESSION_MIN_ATTEMPTS:
        return None
    incorrect = sum(1 for event in session if event.result == "incorrect")
    return (incorrect / len(session)) >= DIFFICULT_SESSION_ERROR_RATE


def _study_volume(events: Sequence[LearningEvent], *, now: datetime) -> int:
    window_start = now - timedelta(days=STUDY_VOLUME_WINDOW_DAYS)
    return sum(
        1
        for event in events
        if window_start <= _require_aware_utc(event.occurred_at) <= now
    )


def _require_aware_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError("timezone-aware な datetime が必要")
    return dt.astimezone(UTC)


__all__ = [
    "ADAPTIVE_DEFAULT_NEW",
    "ADAPTIVE_DEFAULT_TOTAL",
    "ADAPTIVE_MAX_NEW",
    "ADAPTIVE_MAX_TOTAL",
    "ADAPTIVE_MIN_NEW",
    "ADAPTIVE_MIN_TOTAL",
    "POLICY_VERSION",
    "AdaptivePlanConstraints",
    "AdaptivePlanReasonCode",
    "AdaptivePlanSignals",
    "InvalidAdaptivePlanInputError",
    "collect_adaptive_plan_signals",
    "decide_adaptive_plan_constraints",
    "describe_load_adjustment",
]
