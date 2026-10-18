"""苦手パターンの固定 fixture（Issue #203）。

LLM は使わない。同じ Item / Event / now から同じ検出になり、
pattern の加点だけでは due review を超えないことを確認する。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from app.domain.recommendation_ranking import (
    COMPONENT_WEIGHTS,
    DUE_BASE,
    rank_recommendations,
    score_recommendation,
)
from app.domain.recommendation_signal import (
    DirectionSignal,
    RecommendationSignalSnapshot,
    extract_recommendation_signal,
)
from app.domain.tutor import (
    ExerciseType,
    LearningEvent,
    LearningItem,
    LearningItemType,
    SkillDirection,
)
from app.domain.weakness_pattern import (
    PATTERN_VERSION,
    WeaknessPatternHint,
    aggregate_weakness_patterns,
)
from app.evaluation.recommendation_fixtures import QUALITY_NOW

_NOW = QUALITY_NOW


@dataclass(frozen=True)
class WeaknessQualityCheck:
    name: str
    passed: bool
    detail: str


def _item(
    item_id: str,
    *,
    form: str,
    metadata: dict[str, object] | None = None,
    item_type: LearningItemType = "expression",
) -> LearningItem:
    return LearningItem(
        id=item_id,
        item_type=item_type,
        canonical_form=form,
        meaning_ja=form,
        metadata=metadata or {},
        created_at=_NOW - timedelta(days=30),
    )


def _event(
    event_id: str,
    item_id: str,
    *,
    result: str,
    exercise_type: ExerciseType = "ja_to_fr",
    days_ago: float = 1,
) -> LearningEvent:
    outcome = "incorrect" if result == "incorrect" else "correct"
    return LearningEvent(
        id=event_id,
        learning_item_id=item_id,
        exercise_type=exercise_type,
        result=outcome,
        occurred_at=_NOW - timedelta(days=days_ago),
    )


def _direction(direction: SkillDirection, *, unseen: bool) -> DirectionSignal:
    if unseen:
        return DirectionSignal(
            skill_direction=direction,
            mastery_score=0.0,
            attempt_count=0,
            consecutive_correct=0,
            is_unseen=True,
            review_urgency="unscheduled",
            overdue_days=0.0,
            lapse_count=0,
            recent_error_rate=0.0,
            recent_incorrect_count=0,
            recent_correct_count=0,
            last_incorrect_age_days=None,
        )
    return DirectionSignal(
        skill_direction=direction,
        mastery_score=0.5,
        attempt_count=4,
        consecutive_correct=0,
        is_unseen=False,
        review_urgency="due",
        overdue_days=0.0,
        lapse_count=1,
        recent_error_rate=0.5,
        recent_incorrect_count=2,
        recent_correct_count=2,
        last_incorrect_age_days=1.0,
    )


def _snapshot(
    item_id: str,
    *,
    unseen: bool,
    interest_weight: float = 1.0,
    importance_weight: float = 1.0,
    source_recency_days: float | None = None,
    level_distance: int | None = None,
    hints: tuple[WeaknessPatternHint, ...] = (),
) -> RecommendationSignalSnapshot:
    item = _item(item_id, form=item_id)
    base = extract_recommendation_signal(item, weakness_patterns=hints, now=_NOW)
    return base.model_copy(
        update={
            "by_direction": {
                "recognition": _direction("recognition", unseen=unseen),
                "production": _direction("production", unseen=unseen),
            },
            "interest_weight": interest_weight,
            "importance_weight": importance_weight,
            "source_recency_days": source_recency_days,
            "level_distance": level_distance,
            "item_level": None if level_distance is None else "B1",
        }
    )


def evaluate_weakness_pattern_quality() -> tuple[WeaknessQualityCheck, ...]:
    """固定 fixture の pass/fail。同じ入力なら同じ結果。"""
    checks: list[WeaknessQualityCheck] = []
    lever = _item("se-lever", form="se lever", metadata={"pronominal": True})
    laver = _item("se-laver", form="se laver", metadata={"pronominal": True})
    plain = _item("plain", form="se promener")
    events: list[LearningEvent] = []
    for prefix, item_id in (("a", lever.id), ("b", laver.id)):
        for attempt in range(4):
            events.append(
                _event(
                    f"{prefix}-{attempt}",
                    item_id,
                    result="incorrect",
                    days_ago=1 + attempt,
                )
            )
    for attempt in range(4):
        events.append(
            _event(f"plain-{attempt}", plain.id, result="incorrect", days_ago=1)
        )

    report = aggregate_weakness_patterns((lever, laver, plain), events, now=_NOW)
    pronominal = [
        row for row in report.weaknesses if row.pattern_key == "pronominal:true"
    ]
    detected = pronominal[0] if pronominal else None
    checks.append(
        WeaknessQualityCheck(
            name="shared_pronominal_production",
            passed=detected is not None
            and detected.label == "代名動詞"
            and detected.weak_directions == ("production",)
            and detected.evidence_item_ids == ("se-laver", "se-lever")
            and detected.version == PATTERN_VERSION,
            detail="代名動詞の production 誤答を複数 Item で検出する",
        )
    )
    checks.append(
        WeaknessQualityCheck(
            name="missing_metadata_is_not_inferred",
            passed=detected is not None and "plain" not in detected.evidence_item_ids,
            detail="代名動詞と書いていない se promener は根拠に入れない",
        )
    )

    single = aggregate_weakness_patterns((lever,), events[:4], now=_NOW)
    checks.append(
        WeaknessQualityCheck(
            name="single_item_is_not_a_pattern",
            passed=all(
                row.pattern_key != "pronominal:true" for row in single.weaknesses
            ),
            detail="1 Item の誤答だけでは苦手パターンにしない",
        )
    )

    boosted = WeaknessPatternHint(
        pattern_key="pronominal:true",
        label="代名動詞",
        skill_direction="recognition",
        recent_error_count=4,
        error_rate=1.0,
    )
    due = _snapshot("due-item", unseen=False)
    fresh = _snapshot(
        "new-item",
        unseen=True,
        interest_weight=3.0,
        importance_weight=3.0,
        source_recency_days=0.0,
        level_distance=0,
        hints=(boosted,),
    )
    due_score = score_recommendation(due, "recognition", "review")
    new_score = score_recommendation(fresh, "recognition", "new_practice")
    ranked = rank_recommendations((fresh, due))
    soft_weights = (
        COMPONENT_WEIGHTS["level_fit"]
        + COMPONENT_WEIGHTS["source_recency"]
        + COMPONENT_WEIGHTS["interest"]
        + COMPONENT_WEIGHTS["importance"]
        + COMPONENT_WEIGHTS["pattern_weakness"]
    )
    due_floor = COMPONENT_WEIGHTS["overdue"] * DUE_BASE
    checks.append(
        WeaknessQualityCheck(
            name="pattern_weight_does_not_beat_due",
            passed=soft_weights < due_floor
            and new_score.components["pattern_weakness"] > 0
            and due_score.total_score > new_score.total_score
            and ranked[0].learning_item_id == "due-item"
            and ranked[0].activity_kind == "review",
            detail="pattern 加点を足しても due review が新規より上",
        )
    )

    evidence = _snapshot(
        "se-lever",
        unseen=False,
        hints=(
            WeaknessPatternHint(
                pattern_key="pronominal:true",
                label="代名動詞",
                skill_direction="production",
                recent_error_count=8,
                error_rate=1.0,
            ),
        ),
    )
    production = score_recommendation(evidence, "production", "review")
    checks.append(
        WeaknessQualityCheck(
            name="production_pattern_reason",
            passed="PRODUCTION_PATTERN_WEAKNESS" in production.reason_codes
            and "PATTERN_RECENT_ERRORS" not in production.reason_codes
            and production.components["pattern_weakness"]
            <= COMPONENT_WEIGHTS["pattern_weakness"],
            detail="production の根拠に PRODUCTION_PATTERN_WEAKNESS を出す",
        )
    )
    return tuple(checks)
