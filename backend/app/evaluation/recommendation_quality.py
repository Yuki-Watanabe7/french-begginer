"""Tutor 推薦品質の deterministic チェック（Issue #180）。

CI の pass/fail は順位・reason・配分制約の不変条件を主根拠にする。
LLM-as-judge は使わない。同じ fixture / 同じ now からは同じレポートになる。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass

from app.domain.daily_learning_plan import (
    POLICY_VERSION as PLAN_POLICY_VERSION,
)
from app.domain.daily_learning_plan import (
    DailyLearningPlan,
    PlanConstraints,
    build_daily_learning_plan,
)
from app.domain.recommendation_ranking import (
    POLICY_VERSION as RANKING_POLICY_VERSION,
)
from app.domain.recommendation_ranking import (
    REASON_MIN_CONTRIBUTION,
    REASON_TO_COMPONENT,
    RankedRecommendation,
    rank_recommendations,
)
from app.domain.recommendation_signal import (
    FEATURE_VERSION,
    NEUTRAL_IMPORTANCE_WEIGHT,
    NEUTRAL_INTEREST_WEIGHT,
    RecommendationSignalSnapshot,
)
from app.evaluation.recommendation_fixtures import (
    QUALITY_NOW,
    CandidateRef,
    CounterfactualCase,
    LearnerScenario,
    PlanCountExpectation,
    RankOrderExpectation,
    ReasonExpectation,
)

# ---------------------------------------------------------------------------
# reports
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QualityCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class RankedIdReason:
    learning_item_id: str
    skill_direction: str
    activity_kind: str
    reason_codes: tuple[str, ...]
    total_score: float


@dataclass(frozen=True)
class PolicySnapshot:
    """weight 変更時に「何が変わったか」を見比べるための評価記録。"""

    fixture_id: str
    fixture_name: str
    feature_version: str
    ranking_policy_version: str
    plan_policy_version: str | None
    ranked: tuple[RankedIdReason, ...]
    plan_entries: tuple[RankedIdReason, ...] | None
    review_count: int | None
    new_count: int | None
    deferred_due_count: int | None

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["ranked"] = [asdict(row) for row in self.ranked]
        if self.plan_entries is None:
            payload["plan_entries"] = None
        else:
            payload["plan_entries"] = [asdict(row) for row in self.plan_entries]
        return payload


@dataclass(frozen=True)
class ScenarioQualityReport:
    fixture_id: str
    name: str
    passed: bool
    checks: tuple[QualityCheck, ...]
    issues: tuple[str, ...]
    policy_snapshot: PolicySnapshot

    def to_dict(self) -> dict[str, object]:
        return {
            "fixture_id": self.fixture_id,
            "name": self.name,
            "passed": self.passed,
            "checks": [asdict(row) for row in self.checks],
            "issues": list(self.issues),
            "policy_snapshot": self.policy_snapshot.to_dict(),
        }


@dataclass(frozen=True)
class CounterfactualReport:
    case_id: str
    purpose: str
    passed: bool
    detail: str
    feature_version: str
    ranking_policy_version: str
    baseline_ranked: tuple[RankedIdReason, ...]
    mutated_ranked: tuple[RankedIdReason, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "purpose": self.purpose,
            "passed": self.passed,
            "detail": self.detail,
            "feature_version": self.feature_version,
            "ranking_policy_version": self.ranking_policy_version,
            "baseline_ranked": [asdict(row) for row in self.baseline_ranked],
            "mutated_ranked": [asdict(row) for row in self.mutated_ranked],
        }


# ---------------------------------------------------------------------------
# ranking helpers
# ---------------------------------------------------------------------------


def candidate_key(row: RankedRecommendation) -> CandidateRef:
    return (row.learning_item_id, row.skill_direction, row.activity_kind)


def ranked_index(
    ranked: Sequence[RankedRecommendation], ref: CandidateRef
) -> int | None:
    for index, row in enumerate(ranked):
        if candidate_key(row) == ref:
            return index
    return None


def to_ranked_id_reasons(
    ranked: Sequence[RankedRecommendation],
) -> tuple[RankedIdReason, ...]:
    return tuple(
        RankedIdReason(
            learning_item_id=row.learning_item_id,
            skill_direction=row.skill_direction,
            activity_kind=row.activity_kind,
            reason_codes=tuple(row.score.reason_codes),
            total_score=row.score.total_score,
        )
        for row in ranked
    )


def snapshots_by_id(
    snapshots: Sequence[RecommendationSignalSnapshot],
) -> dict[str, RecommendationSignalSnapshot]:
    return {row.learning_item_id: row for row in snapshots}


# ---------------------------------------------------------------------------
# invariant checks
# ---------------------------------------------------------------------------


def _reason_signal_issues(
    row: RankedRecommendation,
    snap: RecommendationSignalSnapshot,
) -> list[str]:
    signal = snap.by_direction.get(row.skill_direction)
    if signal is None:
        return [f"{candidate_key(row)} に DirectionSignal が無い"]
    issues: list[str] = []
    codes = row.score.reason_codes

    if "HIGH_INTEREST" in codes and snap.interest_weight <= NEUTRAL_INTEREST_WEIGHT:
        issues.append("neutral interest なのに HIGH_INTEREST を出した")
    if (
        "HIGH_IMPORTANCE" in codes
        and snap.importance_weight <= NEUTRAL_IMPORTANCE_WEIGHT
    ):
        issues.append("neutral importance なのに HIGH_IMPORTANCE を出した")
    if "LOW_MASTERY" in codes and signal.is_unseen:
        issues.append("unseen を LOW_MASTERY にした")
    if "OVERDUE_REVIEW" in codes and (
        row.activity_kind != "review" or signal.review_urgency != "due"
    ):
        issues.append("due review でないのに OVERDUE_REVIEW を出した")
    if "RECENT_ERROR" in codes and (
        signal.recent_error_rate == 0.0 and signal.last_incorrect_age_days is None
    ):
        issues.append("誤答 signal が無いのに RECENT_ERROR を出した")
    if "PRODUCTION_WEAKER" in codes:
        if row.skill_direction != "production":
            issues.append("recognition に PRODUCTION_WEAKER を出した")
        elif snap.production_gap is None or snap.production_gap <= 0:
            issues.append("production_gap が正でないのに PRODUCTION_WEAKER を出した")
    if "RECOGNITION_WEAKER" in codes:
        if row.skill_direction != "recognition":
            issues.append("production に RECOGNITION_WEAKER を出した")
        elif snap.production_gap is None or snap.production_gap >= 0:
            issues.append("production_gap が負でないのに RECOGNITION_WEAKER を出した")
    if "LEVEL_FIT" in codes and (
        snap.level_distance is None or snap.level_distance > 1
    ):
        issues.append("level fit 対象外なのに LEVEL_FIT を出した")
    if "RECENT_SOURCE" in codes and snap.source_recency_days is None:
        issues.append("Source が無いのに RECENT_SOURCE を出した")

    for code in codes:
        component = REASON_TO_COMPONENT[code]
        if row.score.components[component] < REASON_MIN_CONTRIBUTION:
            issues.append(f"{code} の寄与が閾値未満")
    return issues


def invariant_checks(
    ranked: Sequence[RankedRecommendation],
    snapshots: Sequence[RecommendationSignalSnapshot],
) -> list[QualityCheck]:
    by_id = snapshots_by_id(snapshots)
    checks: list[QualityCheck] = []

    reranked = rank_recommendations(tuple(reversed(snapshots)))
    same = to_ranked_id_reasons(ranked) == to_ranked_id_reasons(reranked)
    checks.append(
        QualityCheck(
            name="same_input_same_order",
            passed=same,
            detail="同じ snapshot / 同じ now なら順位も reason も同じ"
            if same
            else "入力順を変えると順位が変わった",
        )
    )

    review_after_new = False
    saw_new = False
    for row in ranked:
        if row.activity_kind == "new_practice":
            saw_new = True
        elif row.activity_kind == "review" and saw_new:
            review_after_new = True
            break
    checks.append(
        QualityCheck(
            name="due_review_before_new",
            passed=not review_after_new,
            detail="due review が new_practice より後ろに来ない"
            if not review_after_new
            else "new_practice が due review より上に来た",
        )
    )

    reason_issues: list[str] = []
    for row in ranked:
        snap = by_id.get(row.learning_item_id)
        if snap is None:
            reason_issues.append(f"{row.learning_item_id} の snapshot が無い")
            continue
        reason_issues.extend(_reason_signal_issues(row, snap))
    checks.append(
        QualityCheck(
            name="reason_matches_signal",
            passed=not reason_issues,
            detail="reason code が実 signal と矛盾しない"
            if not reason_issues
            else "; ".join(reason_issues),
        )
    )
    return checks


def _plan_invariant_checks(
    plan: DailyLearningPlan,
    *,
    constraints: PlanConstraints,
    skipped_item_ids: tuple[str, ...],
    expectation: PlanCountExpectation | None,
) -> list[QualityCheck]:
    checks: list[QualityCheck] = []
    within_new_cap = plan.new_count <= constraints.max_new_count
    checks.append(
        QualityCheck(
            name="max_new_count",
            passed=within_new_cap,
            detail=(
                f"new_count={plan.new_count} <= "
                f"max_new_count={constraints.max_new_count}"
            ),
        )
    )
    within_total = len(plan.entries) <= constraints.total_count
    checks.append(
        QualityCheck(
            name="plan_capacity",
            passed=within_total,
            detail=(
                f"entries={len(plan.entries)} <= total_count={constraints.total_count}"
            ),
        )
    )

    new_ids = [
        row.learning_item_id
        for row in plan.entries
        if row.activity_kind == "new_practice"
    ]
    unique_new = len(new_ids) == len(set(new_ids))
    checks.append(
        QualityCheck(
            name="no_new_item_inflation",
            passed=unique_new,
            detail="新規 Item を同一 plan で水増ししていない"
            if unique_new
            else f"重複した新規 Item: {new_ids}",
        )
    )

    selected_ids = {row.learning_item_id for row in plan.entries}
    leaked = [item_id for item_id in skipped_item_ids if item_id in selected_ids]
    checks.append(
        QualityCheck(
            name="inactive_mastered_unsupported_not_selected",
            passed=not leaked,
            detail="inactive / mastered / 生成不能を plan に入れない"
            if not leaked
            else f"除外すべき Item が残った: {leaked}",
        )
    )

    skip_ids = {row.learning_item_id for row in plan.skipped}
    missing_skip_reason = [
        item_id for item_id in skipped_item_ids if item_id not in skip_ids
    ]
    checks.append(
        QualityCheck(
            name="skipped_have_reason",
            passed=not missing_skip_reason,
            detail="除外候補に skip 理由が付いている"
            if not missing_skip_reason
            else f"skip 理由が無い: {missing_skip_reason}",
        )
    )

    if expectation is None:
        return checks

    def _count(name: str, actual: int, expected: int | None) -> None:
        if expected is None:
            return
        checks.append(
            QualityCheck(
                name=name,
                passed=actual == expected,
                detail=f"{name} actual={actual} expected={expected}",
            )
        )

    _count("review_count", plan.review_count, expectation.review_count)
    _count("new_count", plan.new_count, expectation.new_count)
    _count(
        "deferred_due_count",
        plan.deferred_due_count,
        expectation.deferred_due_count,
    )
    _count("total_entries", len(plan.entries), expectation.total_entries)
    return checks


def _rank_order_check(
    ranked: Sequence[RankedRecommendation],
    spec: RankOrderExpectation,
) -> QualityCheck:
    higher = ranked_index(ranked, spec.higher)
    lower = ranked_index(ranked, spec.lower)
    if higher is None:
        return QualityCheck(
            name="rank_order",
            passed=False,
            detail=f"上位候補が無い: {spec.higher}",
        )
    if lower is None:
        return QualityCheck(
            name="rank_order",
            passed=False,
            detail=f"下位候補が無い: {spec.lower}",
        )
    passed = higher < lower
    return QualityCheck(
        name="rank_order",
        passed=passed,
        detail=(
            f"{spec.higher} #{higher + 1} が {spec.lower} #{lower + 1} より上位"
            if passed
            else f"{spec.higher} #{higher + 1} が {spec.lower} #{lower + 1} 以下"
        ),
    )


def _reason_check(
    ranked: Sequence[RankedRecommendation],
    spec: ReasonExpectation,
) -> QualityCheck:
    index = ranked_index(ranked, spec.candidate)
    if index is None:
        return QualityCheck(
            name="reason_codes",
            passed=False,
            detail=f"候補が無い: {spec.candidate}",
        )
    codes = set(ranked[index].score.reason_codes)
    missing = [code for code in spec.must_include if code not in codes]
    unexpected = [code for code in spec.must_not_include if code in codes]
    passed = not missing and not unexpected
    codes_tuple = tuple(ranked[index].score.reason_codes)
    detail_parts = [f"{spec.candidate} reasons={codes_tuple}"]
    if missing:
        detail_parts.append(f"不足={missing}")
    if unexpected:
        detail_parts.append(f"余分={unexpected}")
    return QualityCheck(
        name="reason_codes",
        passed=passed,
        detail="; ".join(detail_parts),
    )


# ---------------------------------------------------------------------------
# evaluate
# ---------------------------------------------------------------------------


def build_plan(
    scenario: LearnerScenario,
    ranked: Sequence[RankedRecommendation],
) -> DailyLearningPlan:
    constraints = scenario.constraints or PlanConstraints()
    return build_daily_learning_plan(
        ranked,
        items_by_id={item.id: item for item in scenario.items},
        snapshots_by_id=snapshots_by_id(scenario.snapshots),
        constraints=constraints,
        generated_at=QUALITY_NOW,
        seed=f"quality-{scenario.fixture_id}",
    )


def make_policy_snapshot(
    scenario: LearnerScenario,
    ranked: Sequence[RankedRecommendation],
    plan: DailyLearningPlan | None,
) -> PolicySnapshot:
    plan_entries: tuple[RankedIdReason, ...] | None = None
    if plan is not None:
        plan_entries = tuple(
            RankedIdReason(
                learning_item_id=row.learning_item_id,
                skill_direction=row.skill_direction,
                activity_kind=row.activity_kind,
                reason_codes=tuple(row.reason_codes),
                total_score=row.rank_score,
            )
            for row in plan.entries
        )
    return PolicySnapshot(
        fixture_id=scenario.fixture_id,
        fixture_name=scenario.name,
        feature_version=FEATURE_VERSION,
        ranking_policy_version=RANKING_POLICY_VERSION,
        plan_policy_version=None if plan is None else PLAN_POLICY_VERSION,
        ranked=to_ranked_id_reasons(ranked),
        plan_entries=plan_entries,
        review_count=None if plan is None else plan.review_count,
        new_count=None if plan is None else plan.new_count,
        deferred_due_count=None if plan is None else plan.deferred_due_count,
    )


def evaluate_learner_scenario(scenario: LearnerScenario) -> ScenarioQualityReport:
    ranked = rank_recommendations(scenario.snapshots)
    checks: list[QualityCheck] = []
    checks.extend(invariant_checks(ranked, scenario.snapshots))
    for spec in scenario.rank_orders:
        checks.append(_rank_order_check(ranked, spec))
    for spec in scenario.reasons:
        checks.append(_reason_check(ranked, spec))

    plan: DailyLearningPlan | None = None
    if scenario.items:
        plan = build_plan(scenario, ranked)
        checks.extend(
            _plan_invariant_checks(
                plan,
                constraints=scenario.constraints or PlanConstraints(),
                skipped_item_ids=scenario.skipped_item_ids,
                expectation=scenario.plan,
            )
        )

    issues = tuple(check.detail for check in checks if not check.passed)
    return ScenarioQualityReport(
        fixture_id=scenario.fixture_id,
        name=scenario.name,
        passed=not issues,
        checks=tuple(checks),
        issues=issues,
        policy_snapshot=make_policy_snapshot(scenario, ranked, plan),
    )


def evaluate_counterfactual(case: CounterfactualCase) -> CounterfactualReport:
    baseline = rank_recommendations(case.baseline_snapshots)
    mutated = rank_recommendations(case.mutated_snapshots)
    baseline_index = ranked_index(baseline, case.focus)
    mutated_index = ranked_index(mutated, case.focus)
    passed = False
    detail = ""

    if case.expect == "rank_improves":
        if mutated_index is None:
            detail = f"変更後に {case.focus} が ranking から消えた"
        elif baseline_index is None:
            detail = f"変更前に {case.focus} が無い（rank_improves には不適）"
        else:
            passed = mutated_index < baseline_index
            detail = (
                f"{case.focus} が #{baseline_index + 1} から #{mutated_index + 1} へ"
            )
    elif case.expect == "score_increases":
        if mutated_index is None or baseline_index is None:
            detail = f"{case.focus} を両方の ranking で見つけられない"
        else:
            before = baseline[baseline_index].score.total_score
            after = mutated[mutated_index].score.total_score
            passed = after > before
            detail = f"{case.focus} score {before} -> {after}"
    elif case.expect == "enters_and_outranks":
        if case.competitor is None:
            detail = "competitor が無い"
        elif mutated_index is None:
            detail = f"変更後も {case.focus} が ranking に入らない"
        else:
            competitor_index = ranked_index(mutated, case.competitor)
            entered = baseline_index is None
            outranks = competitor_index is not None and mutated_index < competitor_index
            passed = entered and outranks
            competitor_pos = (
                "-" if competitor_index is None else str(competitor_index + 1)
            )
            detail = (
                f"{case.focus} が新規に #{mutated_index + 1}、"
                f"competitor={case.competitor} #{competitor_pos}"
            )
    elif case.expect == "still_below":
        if case.competitor is None:
            detail = "competitor が無い"
        elif mutated_index is None:
            detail = f"変更後に {case.focus} が無い"
        else:
            competitor_index = ranked_index(mutated, case.competitor)
            passed = competitor_index is not None and mutated_index > competitor_index
            competitor_pos = (
                "-" if competitor_index is None else str(competitor_index + 1)
            )
            detail = (
                f"{case.focus} #{mutated_index + 1} が "
                f"{case.competitor} #{competitor_pos} より下"
            )
    else:
        detail = f"未知の期待: {case.expect}"

    return CounterfactualReport(
        case_id=case.case_id,
        purpose=case.purpose,
        passed=passed,
        detail=detail,
        feature_version=FEATURE_VERSION,
        ranking_policy_version=RANKING_POLICY_VERSION,
        baseline_ranked=to_ranked_id_reasons(baseline),
        mutated_ranked=to_ranked_id_reasons(mutated),
    )


def evaluate_all_scenarios(
    fixtures: Sequence[LearnerScenario],
) -> list[ScenarioQualityReport]:
    return [evaluate_learner_scenario(row) for row in fixtures]


def evaluate_all_counterfactuals(
    cases: Sequence[CounterfactualCase],
) -> list[CounterfactualReport]:
    return [evaluate_counterfactual(row) for row in cases]


def reports_failed(
    reports: Sequence[ScenarioQualityReport | CounterfactualReport],
) -> bool:
    return any(not row.passed for row in reports)


def format_text_report(
    scenarios: Sequence[ScenarioQualityReport],
    counterfactuals: Sequence[CounterfactualReport] | None = None,
) -> str:
    lines: list[str] = [
        "Tutor recommendation quality",
        f"feature_version={FEATURE_VERSION}",
        f"ranking_policy_version={RANKING_POLICY_VERSION}",
        f"plan_policy_version={PLAN_POLICY_VERSION}",
        "",
    ]
    for report in scenarios:
        mark = "PASS" if report.passed else "FAIL"
        lines.append(f"[{mark}] fixture {report.fixture_id} {report.name}")
        snap = report.policy_snapshot
        ranked_ids = [
            f"{row.learning_item_id}/{row.skill_direction}/{row.activity_kind}"
            for row in snap.ranked[:8]
        ]
        lines.append(f"  ranked: {', '.join(ranked_ids)}")
        if snap.review_count is not None:
            lines.append(
                "  plan: "
                f"review={snap.review_count} new={snap.new_count} "
                f"deferred={snap.deferred_due_count}"
            )
        for issue in report.issues:
            lines.append(f"  - {issue}")
        lines.append("")
    if counterfactuals:
        for report in counterfactuals:
            mark = "PASS" if report.passed else "FAIL"
            lines.append(f"[{mark}] counterfactual {report.case_id}: {report.detail}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def reports_to_json(
    scenarios: Sequence[ScenarioQualityReport],
    counterfactuals: Sequence[CounterfactualReport] | None = None,
) -> str:
    payload = {
        "feature_version": FEATURE_VERSION,
        "ranking_policy_version": RANKING_POLICY_VERSION,
        "plan_policy_version": PLAN_POLICY_VERSION,
        "scenarios": [row.to_dict() for row in scenarios],
        "counterfactuals": [row.to_dict() for row in (counterfactuals or ())],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


__all__ = [
    "CounterfactualReport",
    "PolicySnapshot",
    "QualityCheck",
    "RankedIdReason",
    "ScenarioQualityReport",
    "build_plan",
    "evaluate_all_counterfactuals",
    "evaluate_all_scenarios",
    "evaluate_counterfactual",
    "evaluate_learner_scenario",
    "format_text_report",
    "invariant_checks",
    "make_policy_snapshot",
    "reports_failed",
    "reports_to_json",
]
