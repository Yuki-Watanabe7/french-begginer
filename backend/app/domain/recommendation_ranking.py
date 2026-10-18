"""説明可能な Tutor ranking policy と score decomposition（Issue #176 / Phase 5）。

`RecommendationSignalSnapshot` を入力に、「今日、何を優先するか」を
deterministic に順位付けする。LLM や学習済み ML には委ねず、
各 signal の寄与を説明できる weighted scoring を使う。

このモジュールが依存してよいのは Python 標準ライブラリ、Pydantic、
`domain.tutor`、`domain.recommendation_signal` のみ。
DB / FastAPI / OpenAI には依存しない。wall clock は呼ばない。

```text
RecommendationSignalSnapshot
  -> weighted / rule-based scoring
  -> RecommendationScore（total + component 寄与 + reason codes）
  -> ranked recommendation candidates
```

ranking 単位は `learning_item_id + skill_direction + activity_kind`。
同じ Item でも recognition と production の優先度は独立に決まり得る。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.domain.recommendation_signal import (
    CEFR_ORDER,
    NEUTRAL_IMPORTANCE_WEIGHT,
    NEUTRAL_INTEREST_WEIGHT,
    DirectionSignal,
    RecommendationSignalSnapshot,
)
from app.domain.tutor import SkillDirection
from app.domain.weakness_pattern import WeaknessPatternHint

# ---------------------------------------------------------------------------
# 定数（policy_version と weights を一元管理）
# ---------------------------------------------------------------------------

POLICY_VERSION = "ranking-v2"
"""このモジュールが書き込む policy_version。weights / 式の変更時は bump する。

ranking-v2 は pattern_weakness を独立 component として足す。hint が空のとき
寄与は 0 で、ranking-v1 の他 component と同じ式になる。
"""

ActivityKind = Literal["review", "new_practice"]
"""review = 期限到来の復習 / new_practice = 未学習の新規練習。"""

ACTIVITY_KIND_ORDER: tuple[ActivityKind, ...] = ("review", "new_practice")
"""tie-break: review を new_practice より先にする。"""

DIRECTION_ORDER: tuple[SkillDirection, ...] = ("recognition", "production")
"""tie-break: recognition を production より先にする。"""

ReasonCode = Literal[
    "OVERDUE_REVIEW",
    "RECENT_ERROR",
    "PRODUCTION_WEAKER",
    "RECOGNITION_WEAKER",
    "LOW_MASTERY",
    "LAPSE_RISK",
    "RECENT_SOURCE",
    "LEVEL_FIT",
    "HIGH_INTEREST",
    "HIGH_IMPORTANCE",
    "PATTERN_RECENT_ERRORS",
    "PRODUCTION_PATTERN_WEAKNESS",
]
"""ユーザー向け説明へ変換可能な reason code。内部 score 値そのものではない。"""

COMPONENT_NAMES: tuple[str, ...] = (
    "overdue",
    "low_mastery",
    "lapse_risk",
    "recent_error",
    "direction_imbalance",
    "level_fit",
    "source_recency",
    "interest",
    "importance",
    "pattern_weakness",
)
"""score component の安定した列挙順。"""

COMPONENT_WEIGHTS: dict[str, float] = {
    "overdue": 0.50,
    "low_mastery": 0.18,
    "lapse_risk": 0.12,
    "recent_error": 0.20,
    "direction_imbalance": 0.22,
    "level_fit": 0.05,
    "source_recency": 0.08,
    "interest": 0.06,
    "importance": 0.05,
    "pattern_weakness": 0.03,
}
"""各 component の weight。合計は 1 を超えてよい（絶対寄与）。

due review が新規候補に埋もれないよう、overdue を最大にする。
interest / recency / importance / level_fit / pattern_weakness の最大合計は
「ちょうど due」の overdue 寄与を超えない。pattern_weakness は補助 signal で、
苦手パターンがあっても due 優先は維持する。
"""

DUE_BASE = 0.80
"""due であることの下限 raw。overdue_days=0 でも強い優先を残す。"""

OVERDUE_SATURATION_DAYS = 7.0
"""overdue_days を 1.0 に飽和させる日数。"""

LAPSE_SATURATION = 3.0
"""lapse_count を 1.0 に飽和させる回数。"""

RECENT_ERROR_AGE_DAYS = 7.0
"""last_incorrect_age_days を 0 寄与にする日数。"""

RECENCY_SATURATION_DAYS = 30.0
"""source_recency_days を 0 寄与にする日数。"""

INTEREST_RANGE = 2.0
"""interest_weight が NEUTRAL+この値で raw=1.0。"""

IMPORTANCE_RANGE = 2.0
"""importance_weight が NEUTRAL+この値で raw=1.0。"""

MAX_LEVEL_DISTANCE = len(CEFR_ORDER) - 1
"""CEFR の最大距離（A1↔C2 = 5）。"""

UNKNOWN_LEVEL_RAW = 0.5
"""item_level 不明時の level_fit raw。0 にはせず、強く罰しない。"""

LEVEL_FIT_MAX_DISTANCE = 1
"""LEVEL_FIT reason を出す最大 level_distance（0 または 1）。"""

REASON_MIN_CONTRIBUTION = 0.02
"""reason code を出す最小 component 寄与。"""

SCORE_DECIMALS = 6
"""component / total の丸め桁。同一 snapshot で同一 score にするため。"""

REASON_TO_COMPONENT: dict[ReasonCode, str] = {
    "OVERDUE_REVIEW": "overdue",
    "LOW_MASTERY": "low_mastery",
    "LAPSE_RISK": "lapse_risk",
    "RECENT_ERROR": "recent_error",
    "PRODUCTION_WEAKER": "direction_imbalance",
    "RECOGNITION_WEAKER": "direction_imbalance",
    "LEVEL_FIT": "level_fit",
    "RECENT_SOURCE": "source_recency",
    "HIGH_INTEREST": "interest",
    "HIGH_IMPORTANCE": "importance",
    "PATTERN_RECENT_ERRORS": "pattern_weakness",
    "PRODUCTION_PATTERN_WEAKNESS": "pattern_weakness",
}
"""reason code → 対応する score component。説明と寄与の対応を固定する。"""


# ---------------------------------------------------------------------------
# 出力モデル
# ---------------------------------------------------------------------------


class RecommendationScore(BaseModel):
    """1 ranking 単位の score と decomposition。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    total_score: float
    """components の合計。これだけで順位の第一キーになる。"""
    components: dict[str, float]
    """component 名 → 寄与値。ゼロも含め COMPONENT_NAMES をすべて持つ。"""
    policy_version: str = POLICY_VERSION
    reason_codes: tuple[ReasonCode, ...] = ()
    """寄与の大きい順。UI はこれを説明文へ変換してよい。"""


class RankedRecommendation(BaseModel):
    """順位付けされた 1 候補。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    learning_item_id: str
    skill_direction: SkillDirection
    activity_kind: ActivityKind
    score: RecommendationScore


class MissingDirectionSignalError(ValueError):
    """snapshot に指定 SkillDirection の signal が無い。"""

    def __init__(self, learning_item_id: str, skill_direction: SkillDirection) -> None:
        self.learning_item_id = learning_item_id
        self.skill_direction = skill_direction
        super().__init__(
            "RecommendationSignalSnapshot に SkillDirection が無い: "
            f"item={learning_item_id}, direction={skill_direction}"
        )


# ---------------------------------------------------------------------------
# raw signal → [0, 1]
# ---------------------------------------------------------------------------


def _quantize(value: float) -> float:
    return round(value, SCORE_DECIMALS)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def infer_activity_kind(signal: DirectionSignal) -> ActivityKind | None:
    """今日の候補として扱う activity_kind。対象外なら None。

    - due → review（unseen でも due を優先）
    - unseen かつ not due → new_practice
    - seen かつ future / unscheduled → 今日の候補にしない
    """
    if signal.review_urgency == "due":
        return "review"
    if signal.is_unseen:
        return "new_practice"
    return None


def _overdue_raw(signal: DirectionSignal, activity_kind: ActivityKind) -> float:
    if activity_kind != "review" or signal.review_urgency != "due":
        return 0.0
    extra = _clamp01(signal.overdue_days / OVERDUE_SATURATION_DAYS)
    return DUE_BASE + (1.0 - DUE_BASE) * extra


def _low_mastery_raw(signal: DirectionSignal) -> float:
    """unseen は low mastery としない。"""
    if signal.is_unseen:
        return 0.0
    return _clamp01(1.0 - signal.mastery_score)


def _lapse_raw(signal: DirectionSignal) -> float:
    return _clamp01(signal.lapse_count / LAPSE_SATURATION)


def _recent_error_raw(signal: DirectionSignal) -> float:
    rate = signal.recent_error_rate
    if signal.last_incorrect_age_days is None:
        recency = 0.0
    else:
        recency = _clamp01(1.0 - signal.last_incorrect_age_days / RECENT_ERROR_AGE_DAYS)
    if rate == 0.0 and recency == 0.0:
        return 0.0
    return _clamp01(0.6 * rate + 0.4 * recency)


def _imbalance_raw(
    snapshot: RecommendationSignalSnapshot,
    direction: SkillDirection,
) -> float:
    """弱い方向だけを上げる一般式。

    production_gap = recognition_mastery - production_mastery。
    gap > 0 なら production を、gap < 0 なら recognition を上げる。
    片方が unseen で gap が None のときは 0（unseen を苦手と誤認しない）。
    """
    gap = snapshot.production_gap
    if gap is None:
        return 0.0
    if direction == "production":
        return _clamp01(gap)
    return _clamp01(-gap)


def _level_fit_raw(snapshot: RecommendationSignalSnapshot) -> float:
    if snapshot.level_distance is None:
        return UNKNOWN_LEVEL_RAW
    if MAX_LEVEL_DISTANCE <= 0:
        return 1.0
    return _clamp01(1.0 - snapshot.level_distance / MAX_LEVEL_DISTANCE)


def _source_recency_raw(snapshot: RecommendationSignalSnapshot) -> float:
    days = snapshot.source_recency_days
    if days is None:
        return 0.0
    return _clamp01(1.0 - days / RECENCY_SATURATION_DAYS)


def _interest_raw(snapshot: RecommendationSignalSnapshot) -> float:
    extra = snapshot.interest_weight - NEUTRAL_INTEREST_WEIGHT
    if extra <= 0:
        return 0.0
    return _clamp01(extra / INTEREST_RANGE)


def _importance_raw(snapshot: RecommendationSignalSnapshot) -> float:
    extra = snapshot.importance_weight - NEUTRAL_IMPORTANCE_WEIGHT
    if extra <= 0:
        return 0.0
    return _clamp01(extra / IMPORTANCE_RANGE)


def _pattern_hints(
    snapshot: RecommendationSignalSnapshot, direction: SkillDirection
) -> tuple[WeaknessPatternHint, ...]:
    return tuple(
        hint for hint in snapshot.weakness_patterns if hint.skill_direction == direction
    )


def _pattern_weakness_raw(
    snapshot: RecommendationSignalSnapshot, direction: SkillDirection
) -> float:
    """検出済み hint がある direction だけ 1。無いときは 0。重ねて加点しない。"""
    if _pattern_hints(snapshot, direction):
        return 1.0
    return 0.0


# ---------------------------------------------------------------------------
# reason codes
# ---------------------------------------------------------------------------


def _reason_codes(
    *,
    activity_kind: ActivityKind,
    direction: SkillDirection,
    snapshot: RecommendationSignalSnapshot,
    signal: DirectionSignal,
    components: Mapping[str, float],
) -> tuple[ReasonCode, ...]:
    """寄与が閾値以上の component から reason code を作る。寄与の大きい順。"""
    candidates: list[tuple[float, int, ReasonCode]] = []

    def _maybe(code: ReasonCode, extra_ok: bool = True) -> None:
        component = REASON_TO_COMPONENT[code]
        contribution = components[component]
        if extra_ok and contribution >= REASON_MIN_CONTRIBUTION:
            # 同一寄与時は REASON_TO_COMPONENT の定義順で安定させる
            order = list(REASON_TO_COMPONENT).index(code)
            candidates.append((-contribution, order, code))

    _maybe(
        "OVERDUE_REVIEW",
        extra_ok=activity_kind == "review" and signal.review_urgency == "due",
    )
    _maybe("LOW_MASTERY", extra_ok=not signal.is_unseen)
    _maybe("LAPSE_RISK")
    _maybe("RECENT_ERROR")
    if direction == "production":
        _maybe("PRODUCTION_WEAKER")
    else:
        _maybe("RECOGNITION_WEAKER")
    _maybe(
        "LEVEL_FIT",
        extra_ok=(
            snapshot.level_distance is not None
            and snapshot.level_distance <= LEVEL_FIT_MAX_DISTANCE
        ),
    )
    _maybe(
        "RECENT_SOURCE",
        extra_ok=snapshot.source_recency_days is not None,
    )
    _maybe(
        "HIGH_INTEREST",
        extra_ok=snapshot.interest_weight > NEUTRAL_INTEREST_WEIGHT,
    )
    _maybe(
        "HIGH_IMPORTANCE",
        extra_ok=snapshot.importance_weight > NEUTRAL_IMPORTANCE_WEIGHT,
    )
    pattern_hints = _pattern_hints(snapshot, direction)
    _maybe(
        "PATTERN_RECENT_ERRORS",
        extra_ok=direction == "recognition" and bool(pattern_hints),
    )
    _maybe(
        "PRODUCTION_PATTERN_WEAKNESS",
        extra_ok=direction == "production" and bool(pattern_hints),
    )

    candidates.sort()
    return tuple(code for _, __, code in candidates)


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------


def score_recommendation(
    snapshot: RecommendationSignalSnapshot,
    skill_direction: SkillDirection,
    activity_kind: ActivityKind,
) -> RecommendationScore:
    """1 ranking 単位の score と component 寄与を返す。

    同じ snapshot / direction / activity_kind なら常に同じ結果。
    """
    signal = snapshot.by_direction.get(skill_direction)
    if signal is None:
        raise MissingDirectionSignalError(snapshot.learning_item_id, skill_direction)

    raw_by_component = {
        "overdue": _overdue_raw(signal, activity_kind),
        "low_mastery": _low_mastery_raw(signal),
        "lapse_risk": _lapse_raw(signal),
        "recent_error": _recent_error_raw(signal),
        "direction_imbalance": _imbalance_raw(snapshot, skill_direction),
        "level_fit": _level_fit_raw(snapshot),
        "source_recency": _source_recency_raw(snapshot),
        "interest": _interest_raw(snapshot),
        "importance": _importance_raw(snapshot),
        "pattern_weakness": _pattern_weakness_raw(snapshot, skill_direction),
    }

    components: dict[str, float] = {}
    for name in COMPONENT_NAMES:
        weight = COMPONENT_WEIGHTS[name]
        components[name] = _quantize(weight * raw_by_component[name])

    total = _quantize(sum(components.values()))
    reasons = _reason_codes(
        activity_kind=activity_kind,
        direction=skill_direction,
        snapshot=snapshot,
        signal=signal,
        components=components,
    )
    return RecommendationScore(
        total_score=total,
        components=components,
        policy_version=POLICY_VERSION,
        reason_codes=reasons,
    )


# ---------------------------------------------------------------------------
# ranking / tie-break
# ---------------------------------------------------------------------------


def recommendation_sort_key(
    candidate: RankedRecommendation,
    snapshot: RecommendationSignalSnapshot,
) -> tuple:
    """同一 score 時も含め、順序を deterministic にするキー。

    1. total_score 降順
    2. review > new_practice
    3. review は overdue_days 降順、new_practice は source_recency_days 昇順
       （より新しい Source が先。Source なしは最後）
    4. learning_item_id 昇順
    5. skill_direction（recognition < production）
    """
    signal = snapshot.by_direction[candidate.skill_direction]
    activity_index = ACTIVITY_KIND_ORDER.index(candidate.activity_kind)
    if candidate.activity_kind == "review":
        recency_key = -signal.overdue_days
    elif snapshot.source_recency_days is None:
        recency_key = float("inf")
    else:
        recency_key = snapshot.source_recency_days
    direction_index = DIRECTION_ORDER.index(candidate.skill_direction)
    return (
        -candidate.score.total_score,
        activity_index,
        recency_key,
        candidate.learning_item_id,
        direction_index,
    )


def iter_ranking_units(
    snapshot: RecommendationSignalSnapshot,
) -> tuple[tuple[SkillDirection, ActivityKind], ...]:
    """snapshot から今日の ranking 単位を列挙する。"""
    units: list[tuple[SkillDirection, ActivityKind]] = []
    for direction in DIRECTION_ORDER:
        signal = snapshot.by_direction.get(direction)
        if signal is None:
            continue
        kind = infer_activity_kind(signal)
        if kind is None:
            continue
        units.append((direction, kind))
    return tuple(units)


def rank_recommendations(
    snapshots: Sequence[RecommendationSignalSnapshot],
) -> tuple[RankedRecommendation, ...]:
    """複数 snapshot を ranking 単位へ展開し、安定した順位で返す。

    同じ入力なら同じ score / 同じ順序。LearningEvent には version を書かない。
    """
    snapshots_by_id: dict[str, RecommendationSignalSnapshot] = {}
    candidates: list[RankedRecommendation] = []
    for snapshot in snapshots:
        snapshots_by_id[snapshot.learning_item_id] = snapshot
        for direction, activity_kind in iter_ranking_units(snapshot):
            score = score_recommendation(snapshot, direction, activity_kind)
            candidates.append(
                RankedRecommendation(
                    learning_item_id=snapshot.learning_item_id,
                    skill_direction=direction,
                    activity_kind=activity_kind,
                    score=score,
                )
            )

    candidates.sort(
        key=lambda c: recommendation_sort_key(c, snapshots_by_id[c.learning_item_id])
    )
    return tuple(candidates)


__all__ = [
    "ACTIVITY_KIND_ORDER",
    "COMPONENT_NAMES",
    "COMPONENT_WEIGHTS",
    "DIRECTION_ORDER",
    "POLICY_VERSION",
    "REASON_TO_COMPONENT",
    "ActivityKind",
    "MissingDirectionSignalError",
    "RankedRecommendation",
    "ReasonCode",
    "RecommendationScore",
    "infer_activity_kind",
    "iter_ranking_units",
    "rank_recommendations",
    "recommendation_sort_key",
    "score_recommendation",
]
