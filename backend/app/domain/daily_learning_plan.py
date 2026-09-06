"""新規学習と復習の配分を決める Daily Learning Plan policy（Issue #177 / Phase 5）。

ranking 済み candidate を入力に、1日の学習量の中で復習と新規を
何件ずつ入れるかを deterministic に決める。順位付けそのものは
`recommendation_ranking`（Issue #176）が担い、このモジュールは
件数 mix と説明可能な plan 組み立てだけを担う。

このモジュールが依存してよいのは Python 標準ライブラリ、Pydantic、
`domain.tutor`、`domain.exercise`、`domain.recommendation_ranking`、
`domain.recommendation_signal` のみ。
DB / FastAPI / OpenAI / `review_session` には依存しない。
wall clock は呼ばない。Phase 4 の純 review session は書き換えない。

```text
ranked review candidates
+ ranked new candidates
+ plan constraints
  -> DailyLearningPlan
```
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.exercise import (
    ExerciseSkipReason,
    eligible_exercise_types,
    evaluate_exercise_eligibility,
    skill_direction_for,
)
from app.domain.recommendation_ranking import (
    DIRECTION_ORDER,
    ActivityKind,
    RankedRecommendation,
    ReasonCode,
    infer_activity_kind,
)
from app.domain.recommendation_signal import (
    DirectionSignal,
    RecommendationSignalSnapshot,
)
from app.domain.tutor import ExerciseType, LearningItem, SkillDirection

# ---------------------------------------------------------------------------
# 定数（policy_version と配分上限を一元管理）
# ---------------------------------------------------------------------------

POLICY_VERSION = "plan-v1"
"""このモジュールが書き込む policy_version。配分規則の変更時は bump する。"""

DEFAULT_PLAN_SIZE = 10
"""1 plan のデフォルト問題数。"""

DEFAULT_MAX_NEW_COUNT = 3
"""1 plan に入れる新規 LearningItem のデフォルト上限。"""

MIN_PLAN_SIZE = 1
MAX_PLAN_SIZE = 20

DEFAULT_PLAN_SEED = "daily-plan-v1"
"""未指定時の seed。配分は RNG を使わないが、同一入力の契約として記録する。"""

PLAN_EXERCISE_PRIORITY: dict[SkillDirection, tuple[ExerciseType, ...]] = {
    "recognition": ("meaning_recognition",),
    "production": (
        "cloze",
        "expression_reconstruction",
        "verb_conjugation",
        "ja_to_fr",
    ),
}
"""同一 direction で複数 eligible なときの固定優先順。

Phase 4 の `review_session.REVIEW_EXERCISE_PRIORITY` と同じ順にする。
plan は Exercise 本文を生成せず、後続 session が同じ優先順で再構成できるように
selection hint だけを残す。
"""

PlanSkipReason = Literal[
    "unsupported_exercise",
    "missing_item",
    "inactive_item",
    "seen_unscheduled",
]
"""plan に入れなかった candidate の理由。内部 score ではない。"""


# ---------------------------------------------------------------------------
# 入力 / 出力モデル
# ---------------------------------------------------------------------------


class InvalidPlanConstraintsError(ValueError):
    """total_count / max_new_count など、plan 入力が不正。"""


class PlanConstraints(BaseModel):
    """1日の学習量に対する件数制約。将来 minutes 等を足せるが初期は問題数。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    total_count: int = Field(
        default=DEFAULT_PLAN_SIZE, ge=MIN_PLAN_SIZE, le=MAX_PLAN_SIZE
    )
    max_new_count: int = Field(default=DEFAULT_MAX_NEW_COUNT, ge=0, le=MAX_PLAN_SIZE)


class SourceProvenanceSummary(BaseModel):
    """LearningItem の出典の要約。任意。正解情報は持たない。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_ref_count: int = Field(ge=0)
    source_document_ids: tuple[str, ...] = ()


class DailyLearningPlanEntry(BaseModel):
    """plan に採用した 1 件。ranking 単位を 1 slot に落とす。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    learning_item_id: str = Field(min_length=1)
    skill_direction: SkillDirection
    activity_kind: ActivityKind
    selected_exercise_type: ExerciseType
    rank_score: float
    reason_codes: tuple[ReasonCode, ...] = ()
    source_provenance: SourceProvenanceSummary | None = None


class SkippedPlanCandidate(BaseModel):
    """plan に入れられなかった ranking 単位。plan 全体は失敗させない。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    learning_item_id: str = Field(min_length=1)
    skill_direction: SkillDirection
    activity_kind: ActivityKind
    skip_reason: PlanSkipReason
    detail: str | None = None
    exercise_skip_reason: ExerciseSkipReason | None = None


class DailyLearningPlan(BaseModel):
    """説明可能な 1 日分の学習計画。永続化しない。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    generated_at: datetime
    requested_count: int = Field(ge=MIN_PLAN_SIZE, le=MAX_PLAN_SIZE)
    review_count: int = Field(ge=0)
    new_count: int = Field(ge=0)
    entries: tuple[DailyLearningPlanEntry, ...] = ()
    deferred_due_count: int = Field(ge=0)
    skipped: tuple[SkippedPlanCandidate, ...] = ()
    policy_version: str = POLICY_VERSION
    explanation_summary: str = Field(min_length=1)
    seed: str = Field(min_length=1, default=DEFAULT_PLAN_SEED)

    @model_validator(mode="after")
    def _check_invariants(self) -> DailyLearningPlan:
        if self.review_count + self.new_count != len(self.entries):
            raise ValueError(
                "review_count + new_count は entries 件数と一致する必要がある: "
                f"review={self.review_count}, new={self.new_count}, "
                f"entries={len(self.entries)}"
            )
        if self.review_count != sum(
            1 for row in self.entries if row.activity_kind == "review"
        ):
            raise ValueError("review_count は activity_kind=review の件数と一致する")
        if self.new_count != sum(
            1 for row in self.entries if row.activity_kind == "new_practice"
        ):
            raise ValueError("new_count は activity_kind=new_practice の件数と一致する")
        if len(self.entries) > self.requested_count:
            raise ValueError("entries は requested_count を超えない")
        new_item_ids = [
            row.learning_item_id
            for row in self.entries
            if row.activity_kind == "new_practice"
        ]
        if len(new_item_ids) != len(set(new_item_ids)):
            raise ValueError("1 plan 内で同じ新規 LearningItem を水増しできない")
        return self


# ---------------------------------------------------------------------------
# new / review 判定
# ---------------------------------------------------------------------------


def is_new_practice_candidate(signal: DirectionSignal) -> bool:
    """当該 direction を新規練習として扱ってよいか。

    Phase 5 初期の定義:
    - direction state が unseen
    - due ではない（due なら復習を優先）

    seen なのに ReviewSchedule が欠けている不整合は新規にしない。
    履歴 / rebuild（Phase 4）を source of truth とし、schedule 欠損を
    「まだ学んでいない」と誤認しない。
    """
    return infer_activity_kind(signal) == "new_practice"


def is_review_candidate(signal: DirectionSignal) -> bool:
    """当該 direction を due review として扱うか。"""
    return infer_activity_kind(signal) == "review"


def select_exercise_type_for(
    item: LearningItem,
    skill_direction: SkillDirection,
) -> tuple[ExerciseType | None, ExerciseSkipReason | None, str | None]:
    """direction に合う eligible ExerciseType を固定優先順で 1 件返す。

    生成不能なら (None, skip_reason, detail)。plan 全体は失敗させない。
    """
    first_reason: ExerciseSkipReason | None = None
    first_detail: str | None = None
    for exercise_type in PLAN_EXERCISE_PRIORITY[skill_direction]:
        if skill_direction_for(exercise_type) != skill_direction:
            continue
        eligibility = evaluate_exercise_eligibility(item, exercise_type)
        if eligibility.eligible:
            return exercise_type, None, None
        if first_reason is None:
            first_reason = eligibility.skip_reason or "unsupported_combination"
            first_detail = eligibility.detail
    if first_reason is None:
        available = eligible_exercise_types(item)
        first_reason = "unsupported_combination"
        first_detail = (
            f"{item.item_type} の {skill_direction} から Exercise を選べない"
            + (f"（eligible={available}）" if available else "")
        )
    return None, first_reason, first_detail


# ---------------------------------------------------------------------------
# plan 組み立て
# ---------------------------------------------------------------------------


def build_daily_learning_plan(
    ranked: Sequence[RankedRecommendation],
    *,
    items_by_id: Mapping[str, LearningItem],
    snapshots_by_id: Mapping[str, RecommendationSignalSnapshot] | None = None,
    constraints: PlanConstraints | None = None,
    generated_at: datetime,
    seed: str | int = DEFAULT_PLAN_SEED,
) -> DailyLearningPlan:
    """ranking 済み candidate から Daily Learning Plan を組み立てる。

    配分規則:
    1. due review を capacity 内で優先する
    2. 残枠に new を入れるが max_new_count を超えない
    3. 新規 Item は 1 plan に 1 件。direction は recognition を優先し、
       recognition が出せないときだけ production に落とす
    4. 入れられなかった due は deferred_due_count に残す
    5. unsupported は理由付き skip し、次順位で補充する
    6. 同じ ranked + 同じ constraints + 同じ seed なら同じ plan
    """
    plan_constraints = constraints or PlanConstraints()
    _require_constraints(plan_constraints)
    aware_at = _require_aware_utc(generated_at)
    snapshots = snapshots_by_id or {}

    skipped: list[SkippedPlanCandidate] = []
    reviews: list[RankedRecommendation] = []
    news: list[RankedRecommendation] = []

    for candidate in ranked:
        classified = _classified_activity(candidate, snapshots)
        if classified is None:
            skipped.append(
                SkippedPlanCandidate(
                    learning_item_id=candidate.learning_item_id,
                    skill_direction=candidate.skill_direction,
                    activity_kind=candidate.activity_kind,
                    skip_reason="seen_unscheduled",
                    detail=("seen かつ due ではない direction を新規として扱わない"),
                )
            )
            continue
        if classified == "review":
            reviews.append(candidate)
        else:
            news.append(candidate)

    selected: list[DailyLearningPlanEntry] = []
    selected_review_keys: set[tuple[str, SkillDirection]] = set()

    for candidate in reviews:
        if len(selected) >= plan_constraints.total_count:
            break
        entry, skip = _try_entry(candidate, items_by_id, activity_kind="review")
        if skip is not None:
            skipped.append(skip)
            continue
        if entry is None:
            continue
        selected.append(entry)
        selected_review_keys.add((entry.learning_item_id, entry.skill_direction))

    remaining = plan_constraints.total_count - len(selected)
    new_budget = min(remaining, plan_constraints.max_new_count)
    new_chosen = _choose_new_candidates(news, items_by_id, skipped)

    for candidate in new_chosen:
        placed_new = sum(1 for row in selected if row.activity_kind == "new_practice")
        if placed_new >= new_budget:
            break
        entry, skip = _try_entry(candidate, items_by_id, activity_kind="new_practice")
        if skip is not None:
            skipped.append(skip)
            continue
        if entry is None:
            continue
        selected.append(entry)

    deferred_due_count = _count_deferred_due(reviews, selected_review_keys)
    review_count = sum(1 for row in selected if row.activity_kind == "review")
    new_count = sum(1 for row in selected if row.activity_kind == "new_practice")
    explanation = _explanation_summary(
        requested_count=plan_constraints.total_count,
        review_count=review_count,
        new_count=new_count,
        deferred_due_count=deferred_due_count,
        has_entries=bool(selected),
    )
    return DailyLearningPlan(
        generated_at=aware_at,
        requested_count=plan_constraints.total_count,
        review_count=review_count,
        new_count=new_count,
        entries=tuple(selected),
        deferred_due_count=deferred_due_count,
        skipped=tuple(skipped),
        policy_version=POLICY_VERSION,
        explanation_summary=explanation,
        seed=str(seed),
    )


def _classified_activity(
    candidate: RankedRecommendation,
    snapshots: Mapping[str, RecommendationSignalSnapshot],
) -> ActivityKind | None:
    """snapshot があれば unseen/due を再確認する。無ければ ranking を信じる。

    ranking が new_practice としていても、seen + unscheduled なら除外する。
    """
    snapshot = snapshots.get(candidate.learning_item_id)
    if snapshot is None:
        return candidate.activity_kind
    signal = snapshot.by_direction.get(candidate.skill_direction)
    if signal is None:
        return None
    inferred = infer_activity_kind(signal)
    if inferred is None:
        return None
    return inferred


def _choose_new_candidates(
    news: Sequence[RankedRecommendation],
    items_by_id: Mapping[str, LearningItem],
    skipped: list[SkippedPlanCandidate],
) -> list[RankedRecommendation]:
    """新規 Item は 1 件に畳む。recognition を優先し、出せないときだけ production。

    並びは元の ranking 順（最初に現れた Item の順位）を維持する。
    """
    by_item: dict[str, dict[SkillDirection, RankedRecommendation]] = {}
    order: list[str] = []
    for candidate in news:
        if candidate.learning_item_id not in by_item:
            by_item[candidate.learning_item_id] = {}
            order.append(candidate.learning_item_id)
        by_item[candidate.learning_item_id][candidate.skill_direction] = candidate

    chosen: list[RankedRecommendation] = []
    for item_id in order:
        by_direction = by_item[item_id]
        picked: RankedRecommendation | None = None
        last_skip: SkippedPlanCandidate | None = None
        for direction in DIRECTION_ORDER:
            candidate = by_direction.get(direction)
            if candidate is None:
                continue
            entry, skip = _try_entry(
                candidate, items_by_id, activity_kind="new_practice"
            )
            if entry is not None:
                picked = candidate
                break
            last_skip = skip
        if picked is not None:
            chosen.append(picked)
        elif last_skip is not None:
            skipped.append(last_skip)
    return chosen


def _try_entry(
    candidate: RankedRecommendation,
    items_by_id: Mapping[str, LearningItem],
    *,
    activity_kind: ActivityKind,
) -> tuple[DailyLearningPlanEntry | None, SkippedPlanCandidate | None]:
    item = items_by_id.get(candidate.learning_item_id)
    if item is None:
        return None, SkippedPlanCandidate(
            learning_item_id=candidate.learning_item_id,
            skill_direction=candidate.skill_direction,
            activity_kind=activity_kind,
            skip_reason="missing_item",
            detail=f"LearningItem が見つからない: id={candidate.learning_item_id}",
        )
    if item.status != "active":
        return None, SkippedPlanCandidate(
            learning_item_id=item.id,
            skill_direction=candidate.skill_direction,
            activity_kind=activity_kind,
            skip_reason="inactive_item",
            detail=f"inactive な LearningItem は plan に入れない: status={item.status}",
            exercise_skip_reason="inactive_item",
        )
    exercise_type, exercise_reason, detail = select_exercise_type_for(
        item, candidate.skill_direction
    )
    if exercise_type is None:
        return None, SkippedPlanCandidate(
            learning_item_id=item.id,
            skill_direction=candidate.skill_direction,
            activity_kind=activity_kind,
            skip_reason="unsupported_exercise",
            detail=detail,
            exercise_skip_reason=exercise_reason,
        )
    return (
        DailyLearningPlanEntry(
            learning_item_id=item.id,
            skill_direction=candidate.skill_direction,
            activity_kind=activity_kind,
            selected_exercise_type=exercise_type,
            rank_score=candidate.score.total_score,
            reason_codes=candidate.score.reason_codes,
            source_provenance=_provenance(item),
        ),
        None,
    )


def _provenance(item: LearningItem) -> SourceProvenanceSummary | None:
    if not item.source_refs:
        return None
    ids: list[str] = []
    seen: set[str] = set()
    for ref in item.source_refs:
        if ref.source_document_id in seen:
            continue
        seen.add(ref.source_document_id)
        ids.append(ref.source_document_id)
    return SourceProvenanceSummary(
        source_ref_count=len(item.source_refs),
        source_document_ids=tuple(ids),
    )


def _count_deferred_due(
    reviews: Sequence[RankedRecommendation],
    selected_keys: set[tuple[str, SkillDirection]],
) -> int:
    """capacity 不足・unsupported skip で入れられなかった due 件数。"""
    deferred = 0
    seen: set[tuple[str, SkillDirection]] = set()
    for candidate in reviews:
        key = (candidate.learning_item_id, candidate.skill_direction)
        if key in seen:
            continue
        seen.add(key)
        if key not in selected_keys:
            deferred += 1
    return deferred


def _explanation_summary(
    *,
    requested_count: int,
    review_count: int,
    new_count: int,
    deferred_due_count: int,
    has_entries: bool,
) -> str:
    """ユーザー向けの短い配分説明。内部 score は出さない。"""
    if not has_entries:
        if deferred_due_count > 0:
            return (
                f"出題可能な候補がなく、期限到来 {deferred_due_count} 件を繰り越した。"
            )
        return "候補がないため空の学習計画にした。"

    parts: list[str] = []
    if review_count > 0:
        if review_count >= requested_count:
            parts.append(f"容量 {requested_count} 件を復習だけで埋めた")
        else:
            parts.append(f"復習 {review_count} 件を優先した")
    else:
        parts.append("期限到来の復習はなかった")

    if new_count > 0:
        parts.append(f"新規 {new_count} 件を入れた")
    elif review_count < requested_count:
        parts.append("新規は入れなかった")

    if deferred_due_count > 0:
        parts.append(f"期限到来のうち {deferred_due_count} 件を繰り越した")

    return "。".join(parts) + "。"


def _require_constraints(constraints: PlanConstraints) -> None:
    if not MIN_PLAN_SIZE <= constraints.total_count <= MAX_PLAN_SIZE:
        raise InvalidPlanConstraintsError(
            f"total_count は {MIN_PLAN_SIZE}〜{MAX_PLAN_SIZE}: "
            f"{constraints.total_count}"
        )
    if constraints.max_new_count < 0 or constraints.max_new_count > MAX_PLAN_SIZE:
        raise InvalidPlanConstraintsError(
            f"max_new_count は 0〜{MAX_PLAN_SIZE}: {constraints.max_new_count}"
        )


def _require_aware_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError("timezone-aware な datetime が必要")
    return dt.astimezone(UTC)


__all__ = [
    "DEFAULT_MAX_NEW_COUNT",
    "DEFAULT_PLAN_SEED",
    "DEFAULT_PLAN_SIZE",
    "MAX_PLAN_SIZE",
    "MIN_PLAN_SIZE",
    "PLAN_EXERCISE_PRIORITY",
    "POLICY_VERSION",
    "DailyLearningPlan",
    "DailyLearningPlanEntry",
    "InvalidPlanConstraintsError",
    "PlanConstraints",
    "PlanSkipReason",
    "SkippedPlanCandidate",
    "SourceProvenanceSummary",
    "build_daily_learning_plan",
    "is_new_practice_candidate",
    "is_review_candidate",
    "select_exercise_type_for",
]
