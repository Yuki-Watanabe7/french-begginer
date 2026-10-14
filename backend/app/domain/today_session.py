"""「今日の学習」Plan の公開表現と Tutor Today Session 生成（Issue #178 / Phase 5）。

ranking と Daily Learning Plan は #175〜#177 が担う。このモジュールは
reason code からの説明文、Frontend 向け plan DTO（内部 score を載せない）、
plan entry から既存 Exercise 基盤への解決を担う。

このモジュールが依存してよいのは Python 標準ライブラリ、Pydantic、
`domain.tutor`、`domain.exercise`、`domain.exercise_generation`、
`domain.daily_learning_plan`、`domain.recommendation_ranking`、
`domain.recommendation_signal`、`domain.context_selection` のみ。
DB / FastAPI / OpenAI には依存しない。wall clock は呼ばない。
Phase 3 の Practice Session / Phase 4 の純 Review Session は書き換えない。

```text
DailyLearningPlan
  -> reason explanation / public plan
  -> TodayLearningSession（既存 Exercise renderer/evaluator へ落とす）
```

Session 生成時は渡された plan を盲信せず、現在の Item / snapshot で
stale を skip する。予約保持はしない。LearningEvent は作らない。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.context_selection import ContextUsage
from app.domain.daily_learning_plan import (
    PLAN_EXERCISE_PRIORITY,
    POLICY_VERSION,
    DailyLearningPlan,
    DailyLearningPlanEntry,
)
from app.domain.exercise import (
    ExerciseSkipReason,
    PublicExercise,
    skill_direction_for,
    to_public_exercise,
)
from app.domain.exercise_generation import (
    DEFAULT_GENERATION_SEED,
    GeneratedExercise,
    generate_exercise,
)
from app.domain.recommendation_ranking import (
    ActivityKind,
    ReasonCode,
    infer_activity_kind,
)
from app.domain.recommendation_signal import RecommendationSignalSnapshot
from app.domain.tutor import (
    ExerciseType,
    LearningItem,
    LearningItemType,
    SkillDirection,
    SourceDocument,
    new_id,
)
from app.domain.weakness_pattern import pattern_reason_notes

DEFAULT_TODAY_SESSION_SEED = "today-session-v1"
"""未指定時の Session シード。Exercise 生成自体は DEFAULT_GENERATION_SEED。"""

REASON_EXPLANATIONS: dict[ReasonCode, str] = {
    "OVERDUE_REVIEW": "復習時期を迎えています",
    "RECENT_ERROR": "最近この項目で間違えています",
    "PRODUCTION_WEAKER": "意味は分かっていますが、自分で言う練習が不足しています",
    "RECOGNITION_WEAKER": "自分では言えますが、意味を素早く捉える練習が不足しています",
    "RECENT_SOURCE": "最近追加した教材に出てきた表現です",
    "LOW_MASTERY": "まだ定着が十分ではありません",
    "LAPSE_RISK": "以前つまずいた項目です",
    "LEVEL_FIT": "今の学習レベルに合っています",
    "HIGH_INTEREST": "関心の高い教材に出てきた表現です",
    "HIGH_IMPORTANCE": "優先して覚えたい項目です",
    "PATTERN_RECENT_ERRORS": "最近、同じ種類の項目で間違いが続いています",
    "PRODUCTION_PATTERN_WEAKNESS": (
        "最近、同じ種類の項目の自力回答で間違いが続いています"
    ),
}
"""reason code → 短い日本語説明。LLM では生成しない。"""

EMPTY_REASON_EXPLANATION = "今日の学習候補です"
"""reason code が無いときの説明。"""

TodaySessionSkipReason = Literal[
    "unsupported_exercise",
    "missing_item",
    "inactive_item",
    "stale_due",
    "stale_new",
]
"""Session に入れなかった plan entry の理由。内部 score ではない。"""


class TodayPlanEntryView(BaseModel):
    """Frontend 向け 1 entry。内部 score は載せない。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    learning_item_id: str = Field(min_length=1)
    canonical_form: str = Field(min_length=1)
    meaning_ja: str = Field(min_length=1)
    item_type: LearningItemType
    activity_kind: ActivityKind
    skill_direction: SkillDirection
    selected_exercise_type: ExerciseType
    reason_codes: tuple[ReasonCode, ...] = ()
    explanation: str = Field(min_length=1)
    source_titles: tuple[str, ...] = ()


class TodayLearningPlanView(BaseModel):
    """Frontend 向け Daily Learning Plan。正解・内部 score は持たない。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    generated_at: datetime
    requested_count: int = Field(ge=1)
    total_count: int = Field(ge=0)
    review_count: int = Field(ge=0)
    new_count: int = Field(ge=0)
    deferred_due_count: int = Field(ge=0)
    entries: tuple[TodayPlanEntryView, ...] = ()
    summary_reason_codes: tuple[ReasonCode, ...] = ()
    policy_version: str = POLICY_VERSION
    explanation_summary: str = Field(min_length=1)

    @model_validator(mode="after")
    def _check_invariants(self) -> TodayLearningPlanView:
        if self.total_count != len(self.entries):
            raise ValueError("total_count は entries 件数と一致する必要がある")
        if self.review_count + self.new_count != self.total_count:
            raise ValueError("review_count + new_count は total_count と一致する")
        if self.review_count != sum(
            1 for row in self.entries if row.activity_kind == "review"
        ):
            raise ValueError("review_count は activity_kind=review の件数と一致する")
        if self.new_count != sum(
            1 for row in self.entries if row.activity_kind == "new_practice"
        ):
            raise ValueError("new_count は activity_kind=new_practice の件数と一致する")
        return self


class SkippedTodayEntry(BaseModel):
    """Session に入れられなかった plan entry。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    learning_item_id: str = Field(min_length=1)
    skill_direction: SkillDirection
    activity_kind: ActivityKind
    skip_reason: TodaySessionSkipReason
    detail: str | None = None
    exercise_skip_reason: ExerciseSkipReason | None = None


class TodayLearningSession(BaseModel):
    """plan から組み立てた「今日の学習」Session。永続化しない。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: str = Field(min_length=1)
    exercises: tuple[GeneratedExercise, ...] = ()
    entries: tuple[TodayPlanEntryView, ...] = ()
    skipped_entries: tuple[SkippedTodayEntry, ...] = ()
    requested_count: int = Field(ge=1)
    generated_count: int = Field(ge=0)
    review_count: int = Field(ge=0)
    new_count: int = Field(ge=0)
    deferred_due_count: int = Field(ge=0)
    summary_reason_codes: tuple[ReasonCode, ...] = ()
    explanation_summary: str = Field(min_length=1)
    policy_version: str = POLICY_VERSION
    generated_at: datetime
    seed: str = Field(min_length=1)

    @model_validator(mode="after")
    def _check_invariants(self) -> TodayLearningSession:
        if self.generated_count != len(self.exercises):
            raise ValueError("generated_count は exercises 件数と一致する必要がある")
        if self.generated_count != len(self.entries):
            raise ValueError("generated_count は entries 件数と一致する必要がある")
        if self.generated_count > self.requested_count:
            raise ValueError("generated_count は requested_count を超えない")
        if self.review_count + self.new_count != self.generated_count:
            raise ValueError("review_count + new_count は generated_count と一致する")
        keys = [
            (row.spec.learning_item_id, row.spec.exercise_type)
            for row in self.exercises
        ]
        if len(keys) != len(set(keys)):
            raise ValueError(
                "1 Session 内で同じ learning_item_id + exercise_type は重複できない"
            )
        for exercise, entry in zip(self.exercises, self.entries, strict=True):
            if exercise.spec.learning_item_id != entry.learning_item_id:
                raise ValueError(
                    "exercises と entries の learning_item_id がずれている"
                )
            if exercise.spec.skill_direction != entry.skill_direction:
                raise ValueError("exercises と entries の skill_direction がずれている")
        return self

    def to_public_exercises(self) -> tuple[PublicExercise, ...]:
        """Frontend 向け DTO。正解・内部 metadata は載せない。"""
        return tuple(to_public_exercise(row.spec) for row in self.exercises)


def explain_reason_codes(
    codes: Sequence[ReasonCode],
    *,
    pattern_notes: Mapping[str, str] | None = None,
) -> str:
    """reason code から短い説明文を deterministic に生成する。

    LLM は使わない。code が無ければ中立な一文にする。
    pattern_notes がある code は、定型文のあとにパターン名入りの文を足す。
    """
    if not codes:
        return EMPTY_REASON_EXPLANATION
    notes = pattern_notes or {}
    parts: list[str] = []
    for code in codes:
        parts.append(REASON_EXPLANATIONS[code])
        note = notes.get(code)
        if note:
            parts.append(note)
    text = "。".join(parts)
    return text if text.endswith("。") else f"{text}。"


def summary_reason_codes(
    entries: Sequence[DailyLearningPlanEntry | TodayPlanEntryView],
) -> tuple[ReasonCode, ...]:
    """plan 全体の reason code。初出順。内部 score は出さない。"""
    seen: set[ReasonCode] = set()
    ordered: list[ReasonCode] = []
    for entry in entries:
        for code in entry.reason_codes:
            if code in seen:
                continue
            seen.add(code)
            ordered.append(code)
    return tuple(ordered)


def to_public_entry(
    entry: DailyLearningPlanEntry,
    item: LearningItem,
    *,
    sources_by_id: Mapping[str, SourceDocument] | None = None,
    snapshot: RecommendationSignalSnapshot | None = None,
) -> TodayPlanEntryView:
    """1 plan entry を公開 DTO にする。rank_score は載せない。"""
    notes = (
        pattern_reason_notes(snapshot.weakness_patterns) if snapshot is not None else {}
    )
    return TodayPlanEntryView(
        learning_item_id=item.id,
        canonical_form=item.canonical_form,
        meaning_ja=item.meaning_ja,
        item_type=item.item_type,
        activity_kind=entry.activity_kind,
        skill_direction=entry.skill_direction,
        selected_exercise_type=entry.selected_exercise_type,
        reason_codes=entry.reason_codes,
        explanation=explain_reason_codes(entry.reason_codes, pattern_notes=notes),
        source_titles=_source_titles(item, sources_by_id or {}),
    )


def to_public_plan(
    plan: DailyLearningPlan,
    *,
    items_by_id: Mapping[str, LearningItem],
    sources_by_id: Mapping[str, SourceDocument] | None = None,
    snapshots_by_id: Mapping[str, RecommendationSignalSnapshot] | None = None,
) -> TodayLearningPlanView:
    """DailyLearningPlan を公開 DTO にする。欠けた Item は落とさない。

    plan 組み立て時点で missing は skip 済み。ここでも見つからなければ
    例外にし、空の公開 plan へ黙って丸めない。
    """
    sources = sources_by_id or {}
    snapshots = snapshots_by_id or {}
    views: list[TodayPlanEntryView] = []
    for entry in plan.entries:
        item = items_by_id.get(entry.learning_item_id)
        if item is None:
            raise ValueError(
                "plan entry に対応する LearningItem が見つからない: "
                f"id={entry.learning_item_id}"
            )
        views.append(
            to_public_entry(
                entry,
                item,
                sources_by_id=sources,
                snapshot=snapshots.get(item.id),
            )
        )
    return TodayLearningPlanView(
        generated_at=_require_aware_utc(plan.generated_at),
        requested_count=plan.requested_count,
        total_count=len(views),
        review_count=plan.review_count,
        new_count=plan.new_count,
        deferred_due_count=plan.deferred_due_count,
        entries=tuple(views),
        summary_reason_codes=summary_reason_codes(views),
        policy_version=plan.policy_version,
        explanation_summary=plan.explanation_summary,
    )


def build_today_learning_session(
    plan: DailyLearningPlan,
    *,
    items_by_id: Mapping[str, LearningItem],
    snapshots_by_id: Mapping[str, RecommendationSignalSnapshot] | None = None,
    sources: Mapping[str, SourceDocument] | Sequence[SourceDocument] = (),
    seed: str | int = DEFAULT_TODAY_SESSION_SEED,
    session_id: str | None = None,
    context_usages_by_item: Mapping[str, Sequence[ContextUsage]] | None = None,
) -> TodayLearningSession:
    """plan entry を既存 Exercise へ解決する。stale は skip し、Event は作らない。

    長時間 plan を予約保持しない前提でも、呼び出し時点の DB 状態が
    plan 生成時とずれうる。inactive / 消化済み due / もう unseen でない
    新規 / 生成不能を安全に skip する。抜けた枠を別候補で埋め直すのは
    呼び出し側が plan を再計算して行う。
    """
    sources_by_id = _as_source_map(sources)
    usages_by_item = context_usages_by_item or {}
    snapshots = snapshots_by_id or {}
    active_pool = tuple(
        item for item in items_by_id.values() if item.status == "active"
    )
    used_keys: set[tuple[str, ExerciseType]] = set()
    exercises: list[GeneratedExercise] = []
    kept: list[TodayPlanEntryView] = []
    skipped: list[SkippedTodayEntry] = []

    for entry in plan.entries:
        exercise, skip = _resolve_entry(
            entry,
            items_by_id=items_by_id,
            snapshots=snapshots,
            pool=active_pool,
            sources_by_id=sources_by_id,
            used_keys=used_keys,
            context_usages=usages_by_item.get(entry.learning_item_id, ()),
        )
        if skip is not None:
            skipped.append(skip)
            continue
        if exercise is None:
            continue
        item = items_by_id[entry.learning_item_id]
        public_entry = to_public_entry(
            entry.model_copy(
                update={"selected_exercise_type": exercise.spec.exercise_type}
            ),
            item,
            sources_by_id=sources_by_id,
            snapshot=snapshots.get(item.id),
        )
        exercises.append(exercise)
        kept.append(public_entry)
        used_keys.add((exercise.spec.learning_item_id, exercise.spec.exercise_type))

    return TodayLearningSession(
        session_id=session_id if session_id is not None else new_id(),
        exercises=tuple(exercises),
        entries=tuple(kept),
        skipped_entries=tuple(skipped),
        requested_count=plan.requested_count,
        generated_count=len(exercises),
        review_count=sum(1 for row in kept if row.activity_kind == "review"),
        new_count=sum(1 for row in kept if row.activity_kind == "new_practice"),
        deferred_due_count=plan.deferred_due_count,
        summary_reason_codes=summary_reason_codes(kept),
        explanation_summary=plan.explanation_summary,
        policy_version=plan.policy_version,
        generated_at=_require_aware_utc(plan.generated_at),
        seed=str(seed),
    )


def _resolve_entry(
    entry: DailyLearningPlanEntry,
    *,
    items_by_id: Mapping[str, LearningItem],
    snapshots: Mapping[str, RecommendationSignalSnapshot],
    pool: Sequence[LearningItem],
    sources_by_id: Mapping[str, SourceDocument],
    used_keys: set[tuple[str, ExerciseType]],
    context_usages: Sequence[ContextUsage] = (),
) -> tuple[GeneratedExercise | None, SkippedTodayEntry | None]:
    item = items_by_id.get(entry.learning_item_id)
    stale = _stale_reason(entry, item, snapshots.get(entry.learning_item_id))
    if stale is not None:
        reason, detail = stale
        return None, SkippedTodayEntry(
            learning_item_id=entry.learning_item_id,
            skill_direction=entry.skill_direction,
            activity_kind=entry.activity_kind,
            skip_reason=reason,
            detail=detail,
        )
    assert item is not None
    exercise, generation_skip = _generate_for_entry(
        entry,
        item,
        pool=pool,
        sources_by_id=sources_by_id,
        used_keys=used_keys,
        context_usages=context_usages,
    )
    if generation_skip is not None:
        return None, generation_skip
    return exercise, None


def _stale_reason(
    entry: DailyLearningPlanEntry,
    item: LearningItem | None,
    snapshot: RecommendationSignalSnapshot | None,
) -> tuple[TodaySessionSkipReason, str] | None:
    if item is None:
        return (
            "missing_item",
            f"LearningItem が見つからない: id={entry.learning_item_id}",
        )
    if item.status != "active":
        return (
            "inactive_item",
            f"inactive な LearningItem は Session に入れない: status={item.status}",
        )
    if snapshot is None:
        kind: TodaySessionSkipReason = (
            "stale_due" if entry.activity_kind == "review" else "stale_new"
        )
        return (
            kind,
            "現在の signal が無く、stale plan から LearningEvent を作らない",
        )
    signal = snapshot.by_direction.get(entry.skill_direction)
    if signal is None:
        kind = "stale_due" if entry.activity_kind == "review" else "stale_new"
        return (
            kind,
            f"{entry.skill_direction} の signal が無く、stale plan を使わない",
        )
    inferred = infer_activity_kind(signal)
    if entry.activity_kind == "review":
        if inferred != "review":
            return (
                "stale_due",
                "期限到来ではなくなった direction を復習として出さない",
            )
        return None
    if inferred != "new_practice":
        return (
            "stale_new",
            "未学習ではなくなった direction を新規として出さない",
        )
    return None


def _generate_for_entry(
    entry: DailyLearningPlanEntry,
    item: LearningItem,
    *,
    pool: Sequence[LearningItem],
    sources_by_id: Mapping[str, SourceDocument],
    used_keys: set[tuple[str, ExerciseType]],
    context_usages: Sequence[ContextUsage] = (),
) -> tuple[GeneratedExercise | None, SkippedTodayEntry | None]:
    """plan の direction を守り、hint の ExerciseType を優先して生成する。"""
    ordered = _exercise_types_for(entry)
    first_reason: ExerciseSkipReason | None = None
    first_detail: str | None = None
    for exercise_type in ordered:
        if skill_direction_for(exercise_type) != entry.skill_direction:
            continue
        if (item.id, exercise_type) in used_keys:
            continue
        result = generate_exercise(
            item,
            exercise_type,
            pool=pool,
            seed=DEFAULT_GENERATION_SEED,
            sources=sources_by_id,
            context_usages=context_usages,
        )
        if result.eligible and result.exercise is not None:
            if result.exercise.spec.skill_direction != entry.skill_direction:
                if first_reason is None:
                    first_reason = "unsupported_combination"
                    first_detail = (
                        "生成結果の skill_direction が plan entry と一致しない"
                    )
                continue
            return result.exercise, None
        if first_reason is None:
            first_reason = result.skip_reason or "unsupported_combination"
            first_detail = result.detail or "unsupported exercise"
    return None, SkippedTodayEntry(
        learning_item_id=item.id,
        skill_direction=entry.skill_direction,
        activity_kind=entry.activity_kind,
        skip_reason="unsupported_exercise",
        detail=first_detail
        or (
            f"{item.item_type} の {entry.skill_direction} から Exercise を生成できない"
        ),
        exercise_skip_reason=first_reason,
    )


def _exercise_types_for(entry: DailyLearningPlanEntry) -> tuple[ExerciseType, ...]:
    """hint を先頭に、同じ direction の固定優先順で再試行する。"""
    ordered: list[ExerciseType] = [entry.selected_exercise_type]
    for exercise_type in PLAN_EXERCISE_PRIORITY[entry.skill_direction]:
        if exercise_type not in ordered:
            ordered.append(exercise_type)
    return tuple(ordered)


def _source_titles(
    item: LearningItem,
    sources_by_id: Mapping[str, SourceDocument],
) -> tuple[str, ...]:
    titles: list[str] = []
    seen: set[str] = set()
    for ref in item.source_refs:
        if ref.source_document_id in seen:
            continue
        seen.add(ref.source_document_id)
        source = sources_by_id.get(ref.source_document_id)
        if source is None:
            continue
        titles.append(source.title)
    return tuple(titles)


def _as_source_map(
    sources: Mapping[str, SourceDocument] | Sequence[SourceDocument],
) -> dict[str, SourceDocument]:
    if isinstance(sources, Mapping):
        return dict(sources)
    return {row.id: row for row in sources}


def _require_aware_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError("timezone-aware な datetime が必要")
    return dt.astimezone(UTC)


__all__ = [
    "DEFAULT_TODAY_SESSION_SEED",
    "EMPTY_REASON_EXPLANATION",
    "REASON_EXPLANATIONS",
    "SkippedTodayEntry",
    "TodayLearningPlanView",
    "TodayLearningSession",
    "TodayPlanEntryView",
    "TodaySessionSkipReason",
    "build_today_learning_session",
    "explain_reason_codes",
    "summary_reason_codes",
    "to_public_entry",
    "to_public_plan",
]
