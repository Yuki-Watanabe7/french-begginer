"""推薦入力の型付き signal snapshot（Issue #175 / Phase 5）。

「今日、何を優先して学ぶか」の推薦判断に使う特徴量を RecommendationSignalSnapshot
として正規化する。ranking ロジックそのものはここに含めない。

このモジュールが依存してよいのは Python 標準ライブラリ、Pydantic、
`domain.tutor` のみ。DB / FastAPI / OpenAI には依存しない。

```text
Source / LearningItem / LearnerState / ReviewSchedule / LearningEvent
  -> extract_recommendation_signal()
  -> RecommendationSignalSnapshot
  -> rank_recommendations()（Issue #176）
```

## 設計原則

- `now` を注入可能にし、wall clock を呼ばない。
- missing data を根拠なく「苦手」や「得意」と推測しない。
  - unseen（未学習）と low mastery は区別する
  - level 不明は neutral
  - interest 未設定は neutral (1.0)
  - importance 未設定は neutral (1.0)
  - SourceRef なしは recency neutral
- 同じ DB 状態 + 同じ now → 同じ snapshot（deterministic）
- feature_version で snapshot のスキーマ版を追跡する。

## Signal 一覧

1. review urgency: due / future / unscheduled × overdue_days × direction 別
2. mastery: direction 別 mastery_score / attempt_count / consecutive_correct
3. lapse / recent error: direction 別 lapse_count / recent N 件正誤 /
   last_incorrect_age_days
4. direction imbalance: recognition_mastery - production_mastery
5. CEFR level fit: item_level / learner_level / level_distance
6. Source recency / interest: source_recency_days / source_ref_count / interest_weight
7. item importance: importance_weight
8. weakness pattern: 呼び出し側が渡す横断苦手 hint。未指定は空で、苦手と推測しない
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.tutor import (
    CefrLevel,
    LearnerState,
    LearningEvent,
    LearningItem,
    MasteryStats,
    ReviewSchedule,
    SkillDirection,
    SourceDocument,
    SourceRef,
)
from app.domain.weakness_pattern import WeaknessPatternHint

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------

FEATURE_VERSION = "signal-v2"
"""このモジュールが書き込む feature_version。スキーマ変更時は bump する。

signal-v2 は横断苦手パターンの補助 hint（空なら signal-v1 と同じ特徴量）を足す。
"""

RECENT_EVENT_WINDOW = 10
"""recent error rate 算出に使う直近 N 件。"""

CEFR_ORDER: tuple[CefrLevel, ...] = ("A1", "A2", "B1", "B2", "C1", "C2")
"""CEFR レベルの昇順。level_distance 算出に使う。"""

DEFAULT_LEARNER_LEVEL: CefrLevel = "B1"
"""learner_level 未設定時のデフォルト。neutral 扱いを明示する。"""

NEUTRAL_INTEREST_WEIGHT = 1.0
"""interest 未設定時の weight。0 にしない（排除ではなく中立）。"""

NEUTRAL_IMPORTANCE_WEIGHT = 1.0
"""importance 未設定時の weight。0 にしない（排除ではなく中立）。"""

ReviewUrgency = Literal["due", "future", "unscheduled"]
"""due = 期限到来 / future = 未来予定あり / unscheduled = 予定なし"""


# ---------------------------------------------------------------------------
# direction 別 signal
# ---------------------------------------------------------------------------


class DirectionSignal(BaseModel):
    """認識 or 産出 の方向別 signal。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    skill_direction: SkillDirection

    # mastery
    mastery_score: float = Field(ge=0.0, le=1.0)
    """正答率（未学習 = 0.0）。unseen と混同しないために attempt_count を確認する。"""
    attempt_count: int = Field(ge=0)
    consecutive_correct: int = Field(ge=0)
    is_unseen: bool
    """attempt_count == 0 のとき True。low mastery との明示的な区別。"""

    # review urgency
    review_urgency: ReviewUrgency
    overdue_days: float = Field(ge=0.0)
    """due でない場合は 0.0。"""

    # lapse / recent error
    lapse_count: int = Field(ge=0)
    """ReviewSchedule.lapse_count。missing schedule は 0。"""
    recent_error_rate: float = Field(ge=0.0, le=1.0)
    """直近 RECENT_EVENT_WINDOW 件中の誤答率。イベントがなければ 0.0。"""
    recent_incorrect_count: int = Field(ge=0)
    recent_correct_count: int = Field(ge=0)
    last_incorrect_age_days: float | None = None
    """直近の誤答からの経過日数。誤答履歴なし → None。"""


# ---------------------------------------------------------------------------
# RecommendationSignalSnapshot
# ---------------------------------------------------------------------------


class RecommendationSignalSnapshot(BaseModel):
    """推薦エンジンへの入力を型付きで格納する snapshot。

    公開 API に全フィールドを露出する必要はないが、
    ranking の説明生成（なぜこの項目を推薦したか）に使える。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # 識別
    learning_item_id: str
    computed_at: datetime
    """snapshot 生成時刻（= 渡した now）。"""
    feature_version: str = FEATURE_VERSION

    # direction 別 signal
    by_direction: dict[SkillDirection, DirectionSignal] = Field(default_factory=dict)
    """recognition / production それぞれの signal。予定・学習履歴がなければ空。"""

    # direction imbalance
    production_gap: float | None = None
    """recognition_mastery - production_mastery。片方でも unseen なら None。"""

    # CEFR level fit
    item_level: CefrLevel | None = None
    learner_level: CefrLevel
    """未設定でも DEFAULT_LEARNER_LEVEL を入れ、None にしない。"""
    level_distance: int | None = None
    """abs(CEFR_ORDER.index(item_level) - CEFR_ORDER.index(learner_level))。
    item_level が None なら None（neutral）。"""

    # Source recency / interest
    source_recency_days: float | None = None
    """最も新しい SourceDocument.created_at から now までの日数。
    SourceRef なしは None（recency neutral）。"""
    source_ref_count: int = Field(ge=0)
    """何件の Source から参照されているか。"""
    interest_weight: float = Field(ge=0.0)
    """明示的 interest signal。未設定は NEUTRAL_INTEREST_WEIGHT（1.0）。"""

    # item importance
    importance_weight: float = Field(ge=0.0)
    """LearningItem.metadata['importance'] があれば使う。なければ neutral（1.0）。"""

    weakness_patterns: tuple[WeaknessPatternHint, ...] = ()
    """検出済みの横断苦手パターン。空は「パターンなし」であり、未計算の推測ではない。

    複数 Item の集計が必要なため extract 自身は計算しない。呼び出し側が
    `aggregate_weakness_patterns` の結果から渡す。
    """


# ---------------------------------------------------------------------------
# extraction helpers
# ---------------------------------------------------------------------------


def _compute_direction_signal(
    direction: SkillDirection,
    *,
    stats: MasteryStats | None,
    schedule: ReviewSchedule | None,
    recent_events: Sequence[LearningEvent],
    now: datetime,
) -> DirectionSignal:
    """direction 別の signal を計算する。"""
    aware_now = _require_aware_utc(now)

    # mastery
    if stats is None or stats.attempt_count == 0:
        mastery_score = 0.0
        attempt_count = 0
        consecutive_correct = 0
        is_unseen = True
    else:
        mastery_score = stats.mastery_score
        attempt_count = stats.attempt_count
        consecutive_correct = stats.consecutive_correct
        is_unseen = False

    # review urgency
    if schedule is None:
        review_urgency: ReviewUrgency = "unscheduled"
        overdue_days = 0.0
        lapse_count = 0
    else:
        aware_due = _require_aware_utc(schedule.due_at)
        lapse_count = schedule.lapse_count
        if aware_due <= aware_now:
            review_urgency = "due"
            overdue_days = (aware_now - aware_due).total_seconds() / _SECONDS_PER_DAY
        else:
            review_urgency = "future"
            overdue_days = 0.0

    # recent error
    recent = list(recent_events)[-RECENT_EVENT_WINDOW:]
    recent_incorrect = sum(1 for e in recent if e.result == "incorrect")
    recent_correct = sum(1 for e in recent if e.result == "correct")
    recent_total = len(recent)
    recent_error_rate = (recent_incorrect / recent_total) if recent_total > 0 else 0.0

    # last incorrect age
    last_incorrect_age_days: float | None = None
    for event in reversed(list(recent_events)):
        if event.result == "incorrect":
            aware_occurred = _require_aware_utc(event.occurred_at)
            last_incorrect_age_days = (
                aware_now - aware_occurred
            ).total_seconds() / _SECONDS_PER_DAY
            break

    return DirectionSignal(
        skill_direction=direction,
        mastery_score=mastery_score,
        attempt_count=attempt_count,
        consecutive_correct=consecutive_correct,
        is_unseen=is_unseen,
        review_urgency=review_urgency,
        overdue_days=overdue_days,
        lapse_count=lapse_count,
        recent_error_rate=recent_error_rate,
        recent_incorrect_count=recent_incorrect,
        recent_correct_count=recent_correct,
        last_incorrect_age_days=last_incorrect_age_days,
    )


def _compute_production_gap(
    by_direction: dict[SkillDirection, DirectionSignal],
) -> float | None:
    """recognition と production の mastery 差。片方が unseen なら None。"""
    rec = by_direction.get("recognition")
    prod = by_direction.get("production")
    if rec is None or prod is None:
        return None
    if rec.is_unseen or prod.is_unseen:
        return None
    return rec.mastery_score - prod.mastery_score


def _compute_level_distance(
    item_level: CefrLevel | None,
    learner_level: CefrLevel,
) -> int | None:
    """item と learner の CEFR 距離。item_level が None なら None（neutral）。"""
    if item_level is None:
        return None
    return abs(CEFR_ORDER.index(item_level) - CEFR_ORDER.index(learner_level))


def _compute_source_recency(
    source_refs: Sequence[SourceRef],
    sources_by_id: dict[str, SourceDocument],
    now: datetime,
) -> float | None:
    """最も新しい SourceDocument から now までの日数。SourceRef なしは None。"""
    if not source_refs:
        return None
    aware_now = _require_aware_utc(now)
    latest: datetime | None = None
    for ref in source_refs:
        source = sources_by_id.get(ref.source_document_id)
        if source is None:
            continue
        aware_created = _require_aware_utc(source.created_at)
        if latest is None or aware_created > latest:
            latest = aware_created
    if latest is None:
        return None
    return (aware_now - latest).total_seconds() / _SECONDS_PER_DAY


_SECONDS_PER_DAY = timedelta(days=1).total_seconds()


def _require_aware_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError("timezone-aware な datetime が必要")
    return dt.astimezone(UTC)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

SKILL_DIRECTIONS: tuple[SkillDirection, ...] = ("recognition", "production")
"""方向一覧。extract_recommendation_signal がループに使う。"""


def extract_recommendation_signal(
    item: LearningItem,
    *,
    learner_state: LearnerState | None = None,
    schedules_by_direction: dict[SkillDirection, ReviewSchedule] | None = None,
    events_by_direction: dict[SkillDirection, Sequence[LearningEvent]] | None = None,
    sources_by_id: dict[str, SourceDocument] | None = None,
    learner_level: CefrLevel | None = None,
    weakness_patterns: Sequence[WeaknessPatternHint] = (),
    now: datetime,
) -> RecommendationSignalSnapshot:
    """LearningItem の推薦特徴量を RecommendationSignalSnapshot として返す。

    Parameters
    ----------
    item:
        特徴量を計算する LearningItem。
    learner_state:
        当該 Item の現在の LearnerState（by_direction を使う）。None = 未学習。
    schedules_by_direction:
        direction → ReviewSchedule。None = 予定なし（unscheduled 扱い）。
    events_by_direction:
        direction → LearningEvent のリスト（発生時刻昇順）。
        recent error rate / last_incorrect_age の算出に使う。
        None = イベントなし。
    sources_by_id:
        Source recency 算出に使う id → SourceDocument の辞書。
        None = SourceRef があっても recency neutral。
    learner_level:
        学習者の CEFR レベル設定。None なら DEFAULT_LEARNER_LEVEL を使う。
    weakness_patterns:
        この Item が根拠になっている検出済みパターン。未指定は空。
        渡された hint を並べるだけで、ここでは苦手判定をしない。
    now:
        snapshot 生成時刻（due 判定・overdue 算出の基準）。wall clock を呼ばない。
    """
    aware_now = _require_aware_utc(now)
    _schedules = schedules_by_direction or {}
    _events = events_by_direction or {}
    _sources = sources_by_id or {}
    _learner_level = learner_level or DEFAULT_LEARNER_LEVEL

    by_direction: dict[SkillDirection, DirectionSignal] = {}
    for direction in SKILL_DIRECTIONS:
        direction_stats: MasteryStats | None = None
        if learner_state is not None:
            direction_stats = learner_state.by_direction.get(direction)

        by_direction[direction] = _compute_direction_signal(
            direction,
            stats=direction_stats,
            schedule=_schedules.get(direction),
            recent_events=_events.get(direction, []),
            now=aware_now,
        )

    production_gap = _compute_production_gap(by_direction)
    level_distance = _compute_level_distance(item.level, _learner_level)
    source_recency_days = _compute_source_recency(item.source_refs, _sources, aware_now)
    interest_weight = float(
        item.metadata.get("interest_weight", NEUTRAL_INTEREST_WEIGHT)
    )
    importance_weight = float(
        item.metadata.get("importance_weight", NEUTRAL_IMPORTANCE_WEIGHT)
    )
    ordered_patterns = tuple(
        sorted(
            {
                (hint.pattern_key, hint.skill_direction): hint
                for hint in weakness_patterns
            }.values(),
            key=lambda hint: (hint.pattern_key, hint.skill_direction),
        )
    )

    return RecommendationSignalSnapshot(
        learning_item_id=item.id,
        computed_at=aware_now,
        feature_version=FEATURE_VERSION,
        by_direction=by_direction,
        production_gap=production_gap,
        item_level=item.level,
        learner_level=_learner_level,
        level_distance=level_distance,
        source_recency_days=source_recency_days,
        source_ref_count=len(item.source_refs),
        interest_weight=interest_weight,
        importance_weight=importance_weight,
        weakness_patterns=ordered_patterns,
    )
