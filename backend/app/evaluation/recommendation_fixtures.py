"""Tutor 推薦品質評価用の synthetic learner fixture（Issue #180）。

絶対 score の golden 固定はしない。順位・reason・配分制約の不変条件を
fixture ごとに持つ。LLM-as-judge は使わない。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from app.domain.daily_learning_plan import PlanConstraints
from app.domain.recommendation_ranking import ActivityKind, ReasonCode
from app.domain.recommendation_signal import (
    FEATURE_VERSION,
    DirectionSignal,
    RecommendationSignalSnapshot,
)
from app.domain.tutor import LearningItem, SkillDirection

QUALITY_NOW = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)
"""全 fixture で共有する now。wall clock は使わない。"""

CandidateRef = tuple[str, SkillDirection, ActivityKind]
"""ranking 単位の参照。(learning_item_id, skill_direction, activity_kind)。"""

CounterfactualExpect = Literal[
    "rank_improves",
    "score_increases",
    "enters_and_outranks",
    "still_below",
]


@dataclass(frozen=True)
class RankOrderExpectation:
    """higher が lower より上位であること。"""

    higher: CandidateRef
    lower: CandidateRef


@dataclass(frozen=True)
class ReasonExpectation:
    """指定 ranking 単位の reason code に対する包含 / 除外。"""

    candidate: CandidateRef
    must_include: tuple[ReasonCode, ...] = ()
    must_not_include: tuple[ReasonCode, ...] = ()


@dataclass(frozen=True)
class PlanCountExpectation:
    """Daily Learning Plan の件数制約。None の欄は検証しない。"""

    review_count: int | None = None
    new_count: int | None = None
    deferred_due_count: int | None = None
    total_entries: int | None = None
    unique_new_items: bool = True


@dataclass(frozen=True)
class LearnerScenario:
    """複数 LearningItem を持つ synthetic learner と、その期待不変条件。"""

    fixture_id: str
    name: str
    purpose: str
    snapshots: tuple[RecommendationSignalSnapshot, ...]
    items: tuple[LearningItem, ...]
    constraints: PlanConstraints | None = None
    rank_orders: tuple[RankOrderExpectation, ...] = ()
    reasons: tuple[ReasonExpectation, ...] = ()
    plan: PlanCountExpectation | None = None
    skipped_item_ids: tuple[str, ...] = ()
    """plan に入ってはいけない Item（inactive / mastered / 生成不能など）。"""
    notes: str = ""


@dataclass(frozen=True)
class CounterfactualCase:
    """同じ baseline から signal を 1 つだけ変えた反実仮想。"""

    case_id: str
    purpose: str
    baseline_snapshots: tuple[RecommendationSignalSnapshot, ...]
    mutated_snapshots: tuple[RecommendationSignalSnapshot, ...]
    focus: CandidateRef
    expect: CounterfactualExpect
    competitor: CandidateRef | None = None
    notes: str = ""


# ---------------------------------------------------------------------------
# snapshot / item builders
# ---------------------------------------------------------------------------


def direction_signal(
    skill_direction: SkillDirection = "recognition",
    *,
    mastery_score: float = 0.0,
    attempt_count: int = 0,
    consecutive_correct: int = 0,
    is_unseen: bool | None = None,
    review_urgency: str = "unscheduled",
    overdue_days: float = 0.0,
    lapse_count: int = 0,
    recent_error_rate: float = 0.0,
    recent_incorrect_count: int = 0,
    recent_correct_count: int = 0,
    last_incorrect_age_days: float | None = None,
) -> DirectionSignal:
    if is_unseen is None:
        is_unseen = attempt_count == 0
    return DirectionSignal(
        skill_direction=skill_direction,
        mastery_score=mastery_score,
        attempt_count=attempt_count,
        consecutive_correct=consecutive_correct,
        is_unseen=is_unseen,
        review_urgency=review_urgency,  # type: ignore[arg-type]
        overdue_days=overdue_days,
        lapse_count=lapse_count,
        recent_error_rate=recent_error_rate,
        recent_incorrect_count=recent_incorrect_count,
        recent_correct_count=recent_correct_count,
        last_incorrect_age_days=last_incorrect_age_days,
    )


def unseen(direction: SkillDirection) -> DirectionSignal:
    return direction_signal(direction)


def seen_due(
    direction: SkillDirection,
    *,
    overdue_days: float = 1.0,
    mastery_score: float = 0.8,
    attempt_count: int = 6,
    recent_error_rate: float = 0.0,
    recent_incorrect_count: int = 0,
    last_incorrect_age_days: float | None = None,
    lapse_count: int = 0,
) -> DirectionSignal:
    return direction_signal(
        direction,
        mastery_score=mastery_score,
        attempt_count=attempt_count,
        consecutive_correct=2,
        is_unseen=False,
        review_urgency="due",
        overdue_days=overdue_days,
        lapse_count=lapse_count,
        recent_error_rate=recent_error_rate,
        recent_incorrect_count=recent_incorrect_count,
        last_incorrect_age_days=last_incorrect_age_days,
    )


def seen_future(
    direction: SkillDirection,
    *,
    mastery_score: float = 0.8,
    attempt_count: int = 6,
) -> DirectionSignal:
    return direction_signal(
        direction,
        mastery_score=mastery_score,
        attempt_count=attempt_count,
        consecutive_correct=2,
        is_unseen=False,
        review_urgency="future",
    )


def snapshot(
    learning_item_id: str,
    *,
    recognition: DirectionSignal | None = None,
    production: DirectionSignal | None = None,
    production_gap: float | None | object = ...,
    item_level: str | None = None,
    learner_level: str = "B1",
    level_distance: int | None = None,
    source_recency_days: float | None = None,
    source_ref_count: int = 0,
    interest_weight: float = 1.0,
    importance_weight: float = 1.0,
) -> RecommendationSignalSnapshot:
    rec = recognition or unseen("recognition")
    prod = production or unseen("production")
    if production_gap is ...:
        if rec.is_unseen or prod.is_unseen:
            gap: float | None = None
        else:
            gap = rec.mastery_score - prod.mastery_score
    else:
        gap = production_gap  # type: ignore[assignment]
    return RecommendationSignalSnapshot(
        learning_item_id=learning_item_id,
        computed_at=QUALITY_NOW,
        feature_version=FEATURE_VERSION,
        by_direction={"recognition": rec, "production": prod},
        production_gap=gap,
        item_level=item_level,  # type: ignore[arg-type]
        learner_level=learner_level,  # type: ignore[arg-type]
        level_distance=level_distance,
        source_recency_days=source_recency_days,
        source_ref_count=source_ref_count,
        interest_weight=interest_weight,
        importance_weight=importance_weight,
    )


def vocab_item(item_id: str, *, status: str = "active") -> LearningItem:
    return LearningItem(
        id=item_id,
        item_type="vocabulary",
        canonical_form=item_id,
        meaning_ja=f"{item_id}の意味",
        status=status,  # type: ignore[arg-type]
    )


def unsupported_conjugation(item_id: str) -> LearningItem:
    """recognition / production とも Exercise を選べない conjugation。"""
    return LearningItem(
        id=item_id,
        item_type="conjugation",
        canonical_form="xyzverb",
        meaning_ja="未知の動詞",
    )


def replace_direction(
    snap: RecommendationSignalSnapshot,
    direction: SkillDirection,
    **updates: object,
) -> RecommendationSignalSnapshot:
    """指定 direction の signal だけを差し替え、production_gap を再計算する。"""
    current = snap.by_direction[direction]
    replaced = current.model_copy(update=updates)
    by_direction = dict(snap.by_direction)
    by_direction[direction] = replaced
    rec = by_direction.get("recognition")
    prod = by_direction.get("production")
    if rec is None or prod is None or rec.is_unseen or prod.is_unseen:
        gap = None
    else:
        gap = rec.mastery_score - prod.mastery_score
    return snap.model_copy(update={"by_direction": by_direction, "production_gap": gap})


def replace_snapshot(
    snap: RecommendationSignalSnapshot,
    **updates: object,
) -> RecommendationSignalSnapshot:
    return snap.model_copy(update=updates)


def _items(*rows: LearningItem) -> tuple[LearningItem, ...]:
    return rows


# ---------------------------------------------------------------------------
# A. overdue vs recent new
# ---------------------------------------------------------------------------


_A_OVERDUE = snapshot(
    "item-overdue",
    recognition=seen_due("recognition", overdue_days=3.0),
    production=seen_future("production"),
)
_A_NEW = snapshot(
    "item-new-today",
    source_recency_days=0.0,
    source_ref_count=1,
    interest_weight=3.0,
    importance_weight=2.0,
    item_level="B1",
    level_distance=0,
)

FIXTURE_A = LearnerScenario(
    fixture_id="A",
    name="overdue vs recent new",
    purpose="3日 overdue の復習が、今日追加した高 interest の新規より優先される",
    snapshots=(_A_OVERDUE, _A_NEW),
    items=_items(vocab_item("item-overdue"), vocab_item("item-new-today")),
    rank_orders=(
        RankOrderExpectation(
            higher=("item-overdue", "recognition", "review"),
            lower=("item-new-today", "recognition", "new_practice"),
        ),
    ),
    reasons=(
        ReasonExpectation(
            candidate=("item-overdue", "recognition", "review"),
            must_include=("OVERDUE_REVIEW",),
        ),
        ReasonExpectation(
            candidate=("item-new-today", "recognition", "new_practice"),
            must_include=("HIGH_INTEREST",),
            must_not_include=("OVERDUE_REVIEW", "LOW_MASTERY"),
        ),
    ),
    notes="interest / recency / importance だけでは due review を押しのけない。",
)


# ---------------------------------------------------------------------------
# B. recognition high / production low
# ---------------------------------------------------------------------------


_B_ITEM = snapshot(
    "item-imbalance",
    recognition=seen_due(
        "recognition",
        overdue_days=0.0,
        mastery_score=0.9,
        attempt_count=10,
    ),
    production=seen_due(
        "production",
        overdue_days=0.0,
        mastery_score=0.3,
        attempt_count=10,
        recent_error_rate=0.6,
        recent_incorrect_count=3,
        last_incorrect_age_days=1.0,
    ),
)

FIXTURE_B = LearnerScenario(
    fixture_id="B",
    name="recognition high / production low",
    purpose="同じ Item で production の習熟不足と直近誤答が recognition より優先される",
    snapshots=(_B_ITEM,),
    items=_items(vocab_item("item-imbalance")),
    rank_orders=(
        RankOrderExpectation(
            higher=("item-imbalance", "production", "review"),
            lower=("item-imbalance", "recognition", "review"),
        ),
    ),
    reasons=(
        ReasonExpectation(
            candidate=("item-imbalance", "production", "review"),
            must_include=("PRODUCTION_WEAKER", "RECENT_ERROR"),
        ),
        ReasonExpectation(
            candidate=("item-imbalance", "recognition", "review"),
            must_not_include=("PRODUCTION_WEAKER", "RECENT_ERROR"),
        ),
    ),
)


# ---------------------------------------------------------------------------
# C. same everything except recent error
# ---------------------------------------------------------------------------


_C_CLEAN = snapshot(
    "item-clean",
    recognition=seen_due("recognition", overdue_days=1.0, mastery_score=0.5),
    production=seen_future("production", mastery_score=0.5),
)
_C_ERRORED = snapshot(
    "item-errored",
    recognition=seen_due(
        "recognition",
        overdue_days=1.0,
        mastery_score=0.5,
        recent_error_rate=0.8,
        recent_incorrect_count=4,
        last_incorrect_age_days=1.0,
    ),
    production=seen_future("production", mastery_score=0.5),
)

FIXTURE_C = LearnerScenario(
    fixture_id="C",
    name="recent error pair",
    purpose="ほぼ同条件の 2 Item では直近誤答側の優先度が上がる",
    snapshots=(_C_CLEAN, _C_ERRORED),
    items=_items(vocab_item("item-clean"), vocab_item("item-errored")),
    rank_orders=(
        RankOrderExpectation(
            higher=("item-errored", "recognition", "review"),
            lower=("item-clean", "recognition", "review"),
        ),
    ),
    reasons=(
        ReasonExpectation(
            candidate=("item-errored", "recognition", "review"),
            must_include=("RECENT_ERROR",),
        ),
        ReasonExpectation(
            candidate=("item-clean", "recognition", "review"),
            must_not_include=("RECENT_ERROR",),
        ),
    ),
)


# ---------------------------------------------------------------------------
# D. level fit
# ---------------------------------------------------------------------------


def _level_new(
    item_id: str,
    *,
    item_level: str | None,
    level_distance: int | None,
) -> RecommendationSignalSnapshot:
    return snapshot(
        item_id,
        item_level=item_level,
        learner_level="A1",
        level_distance=level_distance,
    )


_D_A1 = _level_new("item-a1", item_level="A1", level_distance=0)
_D_A2 = _level_new("item-a2", item_level="A2", level_distance=1)
_D_B2 = _level_new("item-b2", item_level="B2", level_distance=3)
_D_UNKNOWN = _level_new("item-unknown", item_level=None, level_distance=None)

FIXTURE_D = LearnerScenario(
    fixture_id="D",
    name="level fit",
    purpose=(
        "A1 learner に対して level fit は補助 signal。"
        "B2 を排除せず unknown を極端に罰しない"
    ),
    snapshots=(_D_B2, _D_UNKNOWN, _D_A2, _D_A1),
    items=_items(
        vocab_item("item-a1"),
        vocab_item("item-a2"),
        vocab_item("item-b2"),
        vocab_item("item-unknown"),
    ),
    rank_orders=(
        RankOrderExpectation(
            higher=("item-a1", "recognition", "new_practice"),
            lower=("item-a2", "recognition", "new_practice"),
        ),
        RankOrderExpectation(
            higher=("item-a2", "recognition", "new_practice"),
            lower=("item-b2", "recognition", "new_practice"),
        ),
        RankOrderExpectation(
            higher=("item-unknown", "recognition", "new_practice"),
            lower=("item-b2", "recognition", "new_practice"),
        ),
    ),
    reasons=(
        ReasonExpectation(
            candidate=("item-a1", "recognition", "new_practice"),
            must_include=("LEVEL_FIT",),
        ),
        ReasonExpectation(
            candidate=("item-b2", "recognition", "new_practice"),
            must_not_include=("LEVEL_FIT",),
        ),
        ReasonExpectation(
            candidate=("item-unknown", "recognition", "new_practice"),
            must_not_include=("LEVEL_FIT", "LOW_MASTERY"),
        ),
    ),
    notes=(
        "B2 は ranking から落とさない。"
        "unknown は LEVEL_FIT を出さないが 0 寄与にもしない。"
    ),
)


# ---------------------------------------------------------------------------
# E. due overload
# ---------------------------------------------------------------------------


_E_DUES = tuple(
    snapshot(
        f"due-{index:02d}",
        recognition=seen_due("recognition", overdue_days=float(15 - index)),
        production=seen_future("production"),
    )
    for index in range(15)
)
_E_NEWS = tuple(snapshot(f"new-{index}") for index in range(4))

FIXTURE_E = LearnerScenario(
    fixture_id="E",
    name="due overload",
    purpose="due 15 / capacity 10 なら復習だけで埋め、new 0・deferred 5",
    snapshots=_E_DUES + _E_NEWS,
    items=_items(
        *(vocab_item(f"due-{index:02d}") for index in range(15)),
        *(vocab_item(f"new-{index}") for index in range(4)),
    ),
    constraints=PlanConstraints(total_count=10, max_new_count=3),
    plan=PlanCountExpectation(
        review_count=10,
        new_count=0,
        deferred_due_count=5,
        total_entries=10,
    ),
)


# ---------------------------------------------------------------------------
# F. due under capacity
# ---------------------------------------------------------------------------


_F_DUES = tuple(
    snapshot(
        f"due-{index}",
        recognition=seen_due("recognition", overdue_days=float(4 - index)),
        production=seen_future("production"),
    )
    for index in range(4)
)
_F_NEWS = tuple(snapshot(f"new-{index}") for index in range(6))

FIXTURE_F = LearnerScenario(
    fixture_id="F",
    name="due under capacity",
    purpose=(
        "due 4 / capacity 10 / max new 3 なら due4 + new3。同一 Item で水増ししない"
    ),
    snapshots=_F_DUES + _F_NEWS,
    items=_items(
        *(vocab_item(f"due-{index}") for index in range(4)),
        *(vocab_item(f"new-{index}") for index in range(6)),
    ),
    constraints=PlanConstraints(total_count=10, max_new_count=3),
    plan=PlanCountExpectation(
        review_count=4,
        new_count=3,
        deferred_due_count=0,
        total_entries=7,
        unique_new_items=True,
    ),
)


# ---------------------------------------------------------------------------
# INV. inactive / mastered / unsupported
# ---------------------------------------------------------------------------


_INV_ACTIVE = snapshot(
    "item-active",
    recognition=seen_due("recognition", overdue_days=2.0),
    production=seen_future("production"),
)
_INV_SUSPENDED = snapshot(
    "item-suspended",
    recognition=seen_due("recognition", overdue_days=5.0),
    production=seen_future("production"),
)
_INV_MASTERED = snapshot(
    "item-mastered",
    recognition=seen_due("recognition", overdue_days=4.0),
    production=seen_future("production"),
)
_INV_UNSUPPORTED = snapshot(
    "item-unsupported",
    recognition=seen_due("recognition", overdue_days=3.0),
    production=seen_future("production"),
)

FIXTURE_INV = LearnerScenario(
    fixture_id="INV",
    name="inactive mastered unsupported",
    purpose="inactive / mastered は plan に入れず、生成不能は skip 理由付き",
    snapshots=(_INV_SUSPENDED, _INV_MASTERED, _INV_UNSUPPORTED, _INV_ACTIVE),
    items=_items(
        vocab_item("item-active"),
        vocab_item("item-suspended", status="suspended"),
        vocab_item("item-mastered", status="mastered"),
        unsupported_conjugation("item-unsupported"),
    ),
    constraints=PlanConstraints(total_count=10, max_new_count=3),
    plan=PlanCountExpectation(
        review_count=1,
        new_count=0,
        deferred_due_count=3,
        total_entries=1,
    ),
    skipped_item_ids=("item-suspended", "item-mastered", "item-unsupported"),
    notes="ranking 単体は status を見ない。公開推薦である plan で除外する。",
)


RECOMMENDATION_QUALITY_FIXTURES: tuple[LearnerScenario, ...] = (
    FIXTURE_A,
    FIXTURE_B,
    FIXTURE_C,
    FIXTURE_D,
    FIXTURE_E,
    FIXTURE_F,
    FIXTURE_INV,
)

_FIXTURES_BY_ID = {row.fixture_id: row for row in RECOMMENDATION_QUALITY_FIXTURES}


def get_fixture(fixture_id: str) -> LearnerScenario:
    return _FIXTURES_BY_ID[fixture_id.upper()]


# ---------------------------------------------------------------------------
# counterfactuals（1 signal だけを変える）
# ---------------------------------------------------------------------------


_CF_INTEREST_LOW = snapshot("item-y")
_CF_INTEREST_PEER = snapshot("item-x")
_CF_ERROR_PEER = snapshot(
    "item-a",
    recognition=seen_due("recognition", overdue_days=1.0, mastery_score=0.5),
    production=seen_future("production", mastery_score=0.5),
)
_CF_ERROR_FOCUS = snapshot(
    "item-b",
    recognition=seen_due("recognition", overdue_days=1.0, mastery_score=0.5),
    production=seen_future("production", mastery_score=0.5),
)
_CF_FUTURE = snapshot(
    "item-was-future",
    recognition=seen_future("recognition"),
    production=seen_future("production"),
)
_CF_FUTURE_NEW = snapshot("item-new-competitor")
_CF_PROD_BALANCED = snapshot(
    "item-gap",
    recognition=seen_due("recognition", overdue_days=0.0, mastery_score=0.8),
    production=seen_due("production", overdue_days=0.0, mastery_score=0.8),
)

COUNTERFACTUAL_CASES: tuple[CounterfactualCase, ...] = (
    CounterfactualCase(
        case_id="interest-neutral-to-high",
        purpose="interest を neutral から high にすると当該 new item の順位が上がる",
        baseline_snapshots=(_CF_INTEREST_PEER, _CF_INTEREST_LOW),
        mutated_snapshots=(
            _CF_INTEREST_PEER,
            replace_snapshot(_CF_INTEREST_LOW, interest_weight=3.0),
        ),
        focus=("item-y", "recognition", "new_practice"),
        expect="rank_improves",
        competitor=("item-x", "recognition", "new_practice"),
    ),
    CounterfactualCase(
        case_id="error-none-to-recent",
        purpose="直近誤答を足すと、同条件だった Item の優先度が上がる",
        baseline_snapshots=(_CF_ERROR_PEER, _CF_ERROR_FOCUS),
        mutated_snapshots=(
            _CF_ERROR_PEER,
            replace_direction(
                _CF_ERROR_FOCUS,
                "recognition",
                recent_error_rate=0.8,
                recent_incorrect_count=4,
                last_incorrect_age_days=1.0,
            ),
        ),
        focus=("item-b", "recognition", "review"),
        expect="rank_improves",
        competitor=("item-a", "recognition", "review"),
    ),
    CounterfactualCase(
        case_id="future-to-overdue",
        purpose="future から overdue にすると review として現れ、新規より上に来る",
        baseline_snapshots=(_CF_FUTURE, _CF_FUTURE_NEW),
        mutated_snapshots=(
            replace_direction(
                _CF_FUTURE,
                "recognition",
                review_urgency="due",
                overdue_days=2.0,
            ),
            _CF_FUTURE_NEW,
        ),
        focus=("item-was-future", "recognition", "review"),
        expect="enters_and_outranks",
        competitor=("item-new-competitor", "recognition", "new_practice"),
    ),
    CounterfactualCase(
        case_id="production-mastery-drop",
        purpose="production mastery 0.8→0.3 で production が recognition より上がる",
        baseline_snapshots=(_CF_PROD_BALANCED,),
        mutated_snapshots=(
            replace_direction(_CF_PROD_BALANCED, "production", mastery_score=0.3),
        ),
        focus=("item-gap", "production", "review"),
        expect="rank_improves",
        competitor=("item-gap", "recognition", "review"),
    ),
    CounterfactualCase(
        case_id="high-interest-still-below-overdue",
        purpose="新規の interest を最大にしても overdue review は押しのけない",
        baseline_snapshots=(_A_OVERDUE, snapshot("item-new-today")),
        mutated_snapshots=(
            _A_OVERDUE,
            replace_snapshot(
                snapshot("item-new-today"),
                interest_weight=3.0,
                importance_weight=3.0,
                source_recency_days=0.0,
                source_ref_count=1,
            ),
        ),
        focus=("item-new-today", "recognition", "new_practice"),
        expect="still_below",
        competitor=("item-overdue", "recognition", "review"),
    ),
)

_COUNTERFACTUALS_BY_ID = {row.case_id: row for row in COUNTERFACTUAL_CASES}


def get_counterfactual(case_id: str) -> CounterfactualCase:
    return _COUNTERFACTUALS_BY_ID[case_id]
