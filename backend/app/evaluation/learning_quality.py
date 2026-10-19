"""Tutor 学習品質の複数日シミュレーション（Issue #206）。

admission、known skip、context rotation、弱点検出、負荷調整を
固定 clock の synthetic learner でつなぐ。pass/fail は説明可能な不変条件。
LLM-as-judge は使わない。同じシナリオなら同じ日次メトリクスになる。

1日の組み立て順は ``TodayLearningService._build_plan`` に合わせる。

```text
その朝の Source / Item
  -> signal / known / admission / ranking / adaptive plan / Daily Plan
  -> 答えた日だけ context を選んで LearningEvent を足す
  -> 翌日の due / backlog / 弱点
```
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

from app.domain.adaptive_plan import (
    POLICY_VERSION as ADAPTIVE_POLICY_VERSION,
)
from app.domain.adaptive_plan import (
    collect_adaptive_plan_signals,
    decide_adaptive_plan_constraints,
)
from app.domain.admission_policy import (
    DUE_BACKLOG_HARD_THRESHOLD,
    DUE_BACKLOG_SOFT_THRESHOLD,
    PER_SOURCE_ADMISSION_CAP,
    REDUCED_NEW_ADMISSION_CAP,
    SUPPRESSED_NEW_ADMISSION_CAP,
    UnseenBacklogItem,
    build_unseen_backlog_item,
    count_due_review_units,
    count_recent_introductions,
    decide_new_admissions,
    filter_ranked_new_practice,
    normalize_canonical_form,
)
from app.domain.admission_policy import (
    POLICY_VERSION as ADMISSION_POLICY_VERSION,
)
from app.domain.context_selection import (
    POLICY_VERSION as CONTEXT_POLICY_VERSION,
)
from app.domain.context_selection import (
    ContextCandidate,
    context_usages_from_events,
    select_context,
    source_evidence_id,
    usages_for_exercise,
)
from app.domain.daily_learning_plan import (
    DEFAULT_MAX_NEW_COUNT,
    DEFAULT_PLAN_SEED,
    DEFAULT_PLAN_SIZE,
    DailyLearningPlan,
    PlanConstraints,
    build_daily_learning_plan,
)
from app.domain.daily_learning_plan import (
    POLICY_VERSION as PLAN_POLICY_VERSION,
)
from app.domain.known_item_policy import (
    POLICY_VERSION as KNOWN_POLICY_VERSION,
)
from app.domain.known_item_policy import (
    decide_auto_skip,
    should_drop_today_candidate,
)
from app.domain.recommendation_ranking import (
    POLICY_VERSION as RANKING_POLICY_VERSION,
)
from app.domain.recommendation_ranking import (
    RankedRecommendation,
    infer_activity_kind,
    rank_recommendations,
)
from app.domain.recommendation_signal import (
    FEATURE_VERSION,
    SKILL_DIRECTIONS,
    RecommendationSignalSnapshot,
    extract_recommendation_signal,
)
from app.domain.review_scheduler import schedule_next_review
from app.domain.tutor import (
    AnswerOutcome,
    ExerciseType,
    LearnerState,
    LearningEvent,
    LearningItem,
    ReviewSchedule,
    SkillDirection,
    SourceDocument,
    apply_review_event,
    skill_direction_for_event,
)
from app.domain.weakness_pattern import (
    MIN_ATTEMPTS,
    PATTERN_VERSION,
    WeaknessPatternReport,
    aggregate_weakness_patterns,
    weakness_hints_for_item,
)
from app.evaluation.learning_quality_fixtures import (
    AnswerMode,
    Arrival,
    ItemBehavior,
    LearningQualityScenario,
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
class PolicyVersions:
    """回帰比較用の版。score の絶対値は持たない。"""

    feature_version: str
    ranking_policy_version: str
    plan_policy_version: str
    admission_policy_version: str
    adaptive_load_policy_version: str
    context_policy_version: str
    weakness_pattern_version: str
    known_item_policy_version: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class DayMetrics:
    """1日の計画と、答えたあとに残る材料。"""

    day_index: int
    phase: str
    studied: bool
    due_review_count: int
    overdue_count: int
    deferred_due_count: int
    admission_budget: int
    admitted_count: int
    deferred_count: int
    admitted_ids: tuple[str, ...]
    admitted_forms: tuple[str, ...]
    admitted_by_source: tuple[tuple[str, int], ...]
    unseen_by_source: tuple[tuple[str, int], ...]
    deferral_reasons: tuple[tuple[str, int], ...]
    plan_size: int
    requested_count: int
    review_count: int
    new_count: int
    max_new_count: int
    adaptive_reasons: tuple[str, ...]
    consecutive_difficult_sessions: int
    recent_attempt_count: int
    recent_error_rate: float | None
    known_skip_count: int
    weakness_count: int
    tracked_recognition_weak: bool | None
    tracked_production_weak: bool | None
    tracked_production_attempts: int
    entry_kinds: tuple[str, ...]
    new_item_ids: tuple[str, ...]
    recognition_count: int
    production_count: int
    context_selections: tuple[tuple[str, str, str, int], ...]
    """(item_id, exercise_type, source_id, candidate_count)。答えた日だけ。"""


@dataclass(frozen=True)
class LearningQualityMetrics:
    """日次系列。絶対値の golden 固定には使わない。"""

    day_count: int
    admitted_new_per_day: tuple[int, ...]
    deferred_new_per_day: tuple[int, ...]
    due_backlog_per_day: tuple[int, ...]
    overdue_per_day: tuple[int, ...]
    known_skip_per_day: tuple[int, ...]
    weakness_count_per_day: tuple[int, ...]
    plan_size_per_day: tuple[int, ...]
    max_new_per_day: tuple[int, ...]
    review_count_per_day: tuple[int, ...]
    new_count_per_day: tuple[int, ...]
    recognition_count: int
    production_count: int
    repeated_same_context_rate: float | None
    known_skip_total: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ScenarioQualityReport:
    scenario_id: str
    name: str
    purpose: str
    passed: bool
    checks: tuple[QualityCheck, ...]
    issues: tuple[str, ...]
    policy_versions: PolicyVersions
    metrics: LearningQualityMetrics
    days: tuple[DayMetrics, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "scenario_id": self.scenario_id,
            "name": self.name,
            "purpose": self.purpose,
            "passed": self.passed,
            "checks": [asdict(row) for row in self.checks],
            "issues": list(self.issues),
            "policy_versions": self.policy_versions.to_dict(),
            "metrics": self.metrics.to_dict(),
            "days": [asdict(row) for row in self.days],
        }


# ---------------------------------------------------------------------------
# world
# ---------------------------------------------------------------------------


@dataclass
class _World:
    sources: dict[str, SourceDocument] = field(default_factory=dict)
    items: dict[str, LearningItem] = field(default_factory=dict)
    events: dict[str, list[LearningEvent]] = field(default_factory=dict)
    states: dict[str, LearnerState] = field(default_factory=dict)
    schedules: dict[str, dict[SkillDirection, ReviewSchedule]] = field(
        default_factory=dict
    )


@dataclass(frozen=True)
class _ComposedDay:
    admission_budget: int
    admitted_ids: tuple[str, ...]
    admitted_forms: tuple[str, ...]
    admitted_by_source: tuple[tuple[str, int], ...]
    unseen_by_source: tuple[tuple[str, int], ...]
    deferral_reasons: tuple[tuple[str, int], ...]
    deferred_count: int
    due_review_count: int
    overdue_count: int
    plan: DailyLearningPlan
    max_new_count: int
    adaptive_reasons: tuple[str, ...]
    consecutive_difficult_sessions: int
    recent_attempt_count: int
    recent_error_rate: float | None
    known_skip_count: int
    weakness_count: int
    tracked_recognition_weak: bool | None
    tracked_production_weak: bool | None
    tracked_production_attempts: int
    versions: PolicyVersions


# ---------------------------------------------------------------------------
# simulation
# ---------------------------------------------------------------------------


def evaluate_scenario(scenario: LearningQualityScenario) -> ScenarioQualityReport:
    """シナリオを1回進めて不変条件を判定する。"""

    days, versions = _simulate(scenario)
    checks = _evaluate_invariants(scenario, days, versions)
    issues = tuple(
        f"{check.name}: {check.detail}" for check in checks if not check.passed
    )
    return ScenarioQualityReport(
        scenario_id=scenario.scenario_id,
        name=scenario.name,
        purpose=scenario.purpose,
        passed=not issues,
        checks=checks,
        issues=issues,
        policy_versions=versions,
        metrics=_metrics(days),
        days=days,
    )


def evaluate_all_scenarios(
    scenarios: Sequence[LearningQualityScenario],
) -> tuple[ScenarioQualityReport, ...]:
    return tuple(evaluate_scenario(scenario) for scenario in scenarios)


def reports_failed(reports: Sequence[ScenarioQualityReport]) -> bool:
    return any(not report.passed for report in reports)


def reports_to_json(reports: Sequence[ScenarioQualityReport]) -> str:
    payload = {
        "policy_versions": reports[0].policy_versions.to_dict() if reports else {},
        "scenarios": [report.to_dict() for report in reports],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def format_text_report(reports: Sequence[ScenarioQualityReport]) -> str:
    lines: list[str] = []
    for report in reports:
        versions = report.policy_versions
        lines.append(
            f"scenario {report.scenario_id} "
            f"{'PASS' if report.passed else 'FAIL'} — {report.name}"
        )
        lines.append(f"  {report.purpose}")
        lines.append(f"  feature_version={versions.feature_version}")
        lines.append(f"  ranking_policy_version={versions.ranking_policy_version}")
        lines.append(f"  plan_policy_version={versions.plan_policy_version}")
        lines.append(f"  admission_policy_version={versions.admission_policy_version}")
        lines.append(
            f"  adaptive_load_policy_version={versions.adaptive_load_policy_version}"
        )
        lines.append(f"  context_policy_version={versions.context_policy_version}")
        lines.append(f"  weakness_pattern_version={versions.weakness_pattern_version}")
        lines.append(
            f"  known_item_policy_version={versions.known_item_policy_version}"
        )
        metrics = report.metrics
        rate = metrics.repeated_same_context_rate
        rate_text = "n/a" if rate is None else f"{rate:.3f}"
        lines.append(
            "  metrics "
            f"days={metrics.day_count} "
            f"known_skip={metrics.known_skip_total} "
            f"recognition={metrics.recognition_count} "
            f"production={metrics.production_count} "
            f"same_context_rate={rate_text}"
        )
        lines.append(
            "  day phase studied due overdue budget admitted new max_new reasons weak"
        )
        for day in report.days:
            reasons = ",".join(day.adaptive_reasons)
            lines.append(
                f"  {day.day_index:02d} {day.phase} "
                f"{'yes' if day.studied else 'no'} "
                f"{day.due_review_count} {day.overdue_count} "
                f"{day.admission_budget} {day.admitted_count} "
                f"{day.new_count} {day.max_new_count} {reasons} "
                f"{day.weakness_count}"
            )
        for check in report.checks:
            mark = "ok" if check.passed else "NG"
            lines.append(f"  [{mark}] {check.name}: {check.detail}")
        lines.append("")
    return "\n".join(lines)


def _simulate(
    scenario: LearningQualityScenario,
) -> tuple[tuple[DayMetrics, ...], PolicyVersions]:
    _require_contiguous_days(scenario)
    world = _World()
    days: list[DayMetrics] = []
    versions: PolicyVersions | None = None
    for script in scenario.days:
        when = scenario.start + timedelta(days=script.day_index)
        _apply_arrivals(world, script.arrivals)
        composed = _compose_day(world, scenario, when)
        selections: tuple[tuple[str, str, str, int], ...] = ()
        if script.study:
            selections = _apply_answers(
                world,
                scenario,
                composed.plan,
                when=when,
                answer_mode=script.answer_mode,
                day_index=script.day_index,
            )
        versions = composed.versions
        days.append(
            DayMetrics(
                day_index=script.day_index,
                phase=script.phase,
                studied=script.study,
                due_review_count=composed.due_review_count,
                overdue_count=composed.overdue_count,
                deferred_due_count=composed.plan.deferred_due_count,
                admission_budget=composed.admission_budget,
                admitted_count=len(composed.admitted_ids),
                deferred_count=composed.deferred_count,
                admitted_ids=composed.admitted_ids,
                admitted_forms=composed.admitted_forms,
                admitted_by_source=composed.admitted_by_source,
                unseen_by_source=composed.unseen_by_source,
                deferral_reasons=composed.deferral_reasons,
                plan_size=len(composed.plan.entries),
                requested_count=composed.plan.requested_count,
                review_count=composed.plan.review_count,
                new_count=composed.plan.new_count,
                max_new_count=composed.max_new_count,
                adaptive_reasons=composed.adaptive_reasons,
                consecutive_difficult_sessions=(
                    composed.consecutive_difficult_sessions
                ),
                recent_attempt_count=composed.recent_attempt_count,
                recent_error_rate=composed.recent_error_rate,
                known_skip_count=composed.known_skip_count,
                weakness_count=composed.weakness_count,
                tracked_recognition_weak=composed.tracked_recognition_weak,
                tracked_production_weak=composed.tracked_production_weak,
                tracked_production_attempts=composed.tracked_production_attempts,
                entry_kinds=tuple(
                    entry.activity_kind for entry in composed.plan.entries
                ),
                new_item_ids=tuple(
                    entry.learning_item_id
                    for entry in composed.plan.entries
                    if entry.activity_kind == "new_practice"
                ),
                recognition_count=sum(
                    1
                    for entry in composed.plan.entries
                    if entry.skill_direction == "recognition"
                ),
                production_count=sum(
                    1
                    for entry in composed.plan.entries
                    if entry.skill_direction == "production"
                ),
                context_selections=selections,
            )
        )
    if versions is None:
        raise ValueError("シナリオに日がない")
    return tuple(days), versions


def _apply_arrivals(world: _World, arrivals: Sequence[Arrival]) -> None:
    for arrival in arrivals:
        if arrival.source.id in world.sources:
            raise ValueError(f"Source id が重複している: {arrival.source.id}")
        world.sources[arrival.source.id] = arrival.source
        for item in arrival.items:
            if item.id in world.items:
                raise ValueError(f"LearningItem id が重複している: {item.id}")
            world.items[item.id] = item
            world.events[item.id] = []


def _compose_day(
    world: _World,
    scenario: LearningQualityScenario,
    now: datetime,
) -> _ComposedDay:
    """TodayLearningService と同じ順で、その朝の Plan を作る。"""

    items = [world.items[item_id] for item_id in sorted(world.items)]
    events_by_item = world.events
    all_events = [event for item in items for event in events_by_item.get(item.id, [])]
    weakness_report = aggregate_weakness_patterns(items, all_events, now=now)
    snapshots: list[RecommendationSignalSnapshot] = []
    snapshots_by_id: dict[str, RecommendationSignalSnapshot] = {}
    unseen: list[UnseenBacklogItem] = []
    first_learned_at: dict[str, datetime] = {}
    auto_skipped: set[tuple[str, SkillDirection]] = set()
    known_ids = scenario.known_item_ids

    for item in items:
        if item.status != "active":
            continue
        by_direction = _events_by_direction(events_by_item.get(item.id, []))
        for direction, direction_events in by_direction.items():
            decision = decide_auto_skip(
                skill_direction=direction,
                events=direction_events,
                now=now,
            )
            if decision.skip_new:
                auto_skipped.add((item.id, direction))
        learned_at = [
            event.occurred_at
            for direction_events in by_direction.values()
            for event in direction_events
        ]
        if learned_at:
            first_learned_at[item.id] = min(learned_at)
        snapshot = extract_recommendation_signal(
            item,
            learner_state=world.states.get(item.id),
            schedules_by_direction=world.schedules.get(item.id, {}),
            events_by_direction=by_direction,
            sources_by_id=world.sources,
            weakness_patterns=weakness_hints_for_item(item.id, weakness_report),
            now=now,
        )
        snapshots.append(snapshot)
        snapshots_by_id[item.id] = snapshot
        if item.id in known_ids:
            continue
        backlog_item = build_unseen_backlog_item(
            item,
            snapshot,
            sources_by_id=world.sources,
        )
        if backlog_item is None:
            continue
        if _has_offerable_new_direction(snapshot, auto_skipped):
            unseen.append(backlog_item)

    due_review_count = count_due_review_units(snapshots)
    admission = decide_new_admissions(
        unseen,
        due_review_count=due_review_count,
        recent_introduced_count=count_recent_introductions(
            first_learned_at,
            now=now,
        ),
        now=now,
    )
    ranked = _drop_blocked_new_practice(
        filter_ranked_new_practice(rank_recommendations(snapshots), admission),
        explicit_known_ids=known_ids,
        auto_skipped=auto_skipped,
    )
    signals = collect_adaptive_plan_signals(
        snapshots,
        all_events,
        admission_budget=admission.admission_budget,
        now=now,
    )
    adaptive = decide_adaptive_plan_constraints(signals)
    plan = build_daily_learning_plan(
        ranked,
        items_by_id={item.id: item for item in items},
        snapshots_by_id=snapshots_by_id,
        constraints=PlanConstraints(
            total_count=adaptive.total_count,
            max_new_count=adaptive.max_new_count,
        ),
        generated_at=now,
        seed=DEFAULT_PLAN_SEED,
    )
    ranking_version = RANKING_POLICY_VERSION
    if ranked:
        ranking_version = ranked[0].score.policy_version
    recognition_weak, production_weak, production_attempts = _tracked_pattern(
        weakness_report,
        scenario.tracked_pattern_key,
    )
    known_skip_count = 0
    for item_id in known_ids:
        state = world.states.get(item_id)
        if state is None or state.attempt_count == 0:
            known_skip_count += 1
    forms = {
        item.learning_item_id: normalize_canonical_form(
            world.items[item.learning_item_id].canonical_form
        )
        for item in unseen
    }
    admitted_by_source: Counter[str] = Counter()
    unseen_by_source: Counter[str] = Counter()
    for item in unseen:
        source_id = item.primary_source_id or ""
        unseen_by_source[source_id] += 1
        if item.learning_item_id in admission.admitted_ids:
            admitted_by_source[source_id] += 1
    reasons: Counter[str] = Counter()
    for decision in admission.decisions:
        if decision.outcome == "defer" and decision.reason_codes:
            reasons[decision.reason_codes[0]] += 1
    return _ComposedDay(
        admission_budget=admission.admission_budget,
        admitted_ids=admission.admitted_ids,
        admitted_forms=tuple(forms[item_id] for item_id in admission.admitted_ids),
        admitted_by_source=tuple(sorted(admitted_by_source.items())),
        unseen_by_source=tuple(sorted(unseen_by_source.items())),
        deferral_reasons=tuple(sorted(reasons.items())),
        deferred_count=sum(reasons.values()),
        due_review_count=due_review_count,
        overdue_count=signals.overdue_count,
        plan=plan,
        max_new_count=adaptive.max_new_count,
        adaptive_reasons=adaptive.reason_codes,
        consecutive_difficult_sessions=signals.consecutive_difficult_sessions,
        recent_attempt_count=signals.recent_attempt_count,
        recent_error_rate=signals.recent_error_rate,
        known_skip_count=known_skip_count,
        weakness_count=len(weakness_report.weaknesses),
        tracked_recognition_weak=recognition_weak,
        tracked_production_weak=production_weak,
        tracked_production_attempts=production_attempts,
        versions=PolicyVersions(
            feature_version=(
                snapshots[0].feature_version if snapshots else FEATURE_VERSION
            ),
            ranking_policy_version=ranking_version,
            plan_policy_version=plan.policy_version,
            admission_policy_version=admission.policy_version,
            adaptive_load_policy_version=adaptive.policy_version,
            context_policy_version=CONTEXT_POLICY_VERSION,
            weakness_pattern_version=weakness_report.version,
            known_item_policy_version=KNOWN_POLICY_VERSION,
        ),
    )


def _apply_answers(
    world: _World,
    scenario: LearningQualityScenario,
    plan: DailyLearningPlan,
    *,
    when: datetime,
    answer_mode: AnswerMode,
    day_index: int,
) -> tuple[tuple[str, str, str, int], ...]:
    selections: list[tuple[str, str, str, int]] = []
    for index, entry in enumerate(plan.entries):
        item = world.items[entry.learning_item_id]
        occurred_at = when + timedelta(minutes=index)
        selection = _select_entry_context(world, item, entry.selected_exercise_type)
        metadata: dict[str, object] = {"exercise_version": "learning-quality-sim-v1"}
        if selection is not None:
            chosen, candidate_count = selection
            span = chosen.selected_source_ref.evidence_span
            if span is None:
                raise ValueError("選択した文脈に evidence が無い")
            source_id = chosen.selected_source_ref.source_document_id
            metadata.update(
                {
                    "source_document_id": source_id,
                    "source_evidence_id": source_evidence_id(
                        source_id, span.start, span.end
                    ),
                    "evidence_start": span.start,
                    "evidence_end": span.end,
                    "context_policy_version": chosen.policy_version,
                    "context_selection_reason": chosen.reason,
                }
            )
            selections.append(
                (
                    item.id,
                    entry.selected_exercise_type,
                    source_id,
                    candidate_count,
                )
            )
            if chosen.policy_version != CONTEXT_POLICY_VERSION:
                raise ValueError(
                    f"context policy_version が一致しない: {chosen.policy_version}"
                )
        event = LearningEvent(
            id=f"{scenario.scenario_id}-d{day_index:02d}-e{index:02d}",
            learning_item_id=item.id,
            exercise_type=entry.selected_exercise_type,
            result=_outcome(
                scenario.behavior_for(item.id),
                entry.skill_direction,
                answer_mode,
            ),
            occurred_at=occurred_at,
            metadata=metadata,
        )
        direction = skill_direction_for_event(event)
        if direction != entry.skill_direction:
            raise ValueError(
                "ExerciseType の direction が plan と一致しない: "
                f"item={item.id}, exercise={entry.selected_exercise_type}"
            )
        state = apply_review_event(world.states.get(item.id), event)
        previous = world.schedules.get(item.id, {}).get(direction)
        schedule = schedule_next_review(state, event, previous)
        world.states[item.id] = state
        world.schedules.setdefault(item.id, {})[direction] = schedule
        world.events.setdefault(item.id, []).append(event)
    return tuple(selections)


def _select_entry_context(
    world: _World,
    item: LearningItem,
    exercise_type: ExerciseType,
):
    candidates: list[ContextCandidate] = []
    for ref in item.source_refs:
        if ref.evidence_span is None:
            continue
        source = world.sources.get(ref.source_document_id)
        if source is None:
            continue
        candidates.append(
            ContextCandidate(source_ref=ref, source_created_at=source.created_at)
        )
    if not candidates:
        return None
    usages = usages_for_exercise(
        context_usages_from_events(world.events.get(item.id, [])),
        exercise_type,
    )
    chosen = select_context(
        learning_item_id=item.id,
        candidates=candidates,
        usages=usages,
    )
    if chosen is None:
        return None
    return chosen, len(candidates)


def _outcome(
    behavior: ItemBehavior,
    direction: SkillDirection,
    answer_mode: AnswerMode,
) -> AnswerOutcome:
    """production だけ弱い item は、難しい日でも recognition を誤答にしない。"""

    if behavior == "production_weak":
        if direction == "production":
            return "incorrect"
        return "correct"
    if answer_mode == "all_incorrect":
        return "incorrect"
    return "correct"


def _events_by_direction(
    events: Sequence[LearningEvent],
) -> dict[SkillDirection, list[LearningEvent]]:
    grouped: dict[SkillDirection, list[LearningEvent]] = {
        direction: [] for direction in SKILL_DIRECTIONS
    }
    for event in events:
        direction = skill_direction_for_event(event)
        if direction is None:
            continue
        grouped[direction].append(event)
    return grouped


def _has_offerable_new_direction(
    snapshot: RecommendationSignalSnapshot,
    auto_skipped: set[tuple[str, SkillDirection]],
) -> bool:
    for direction, signal in snapshot.by_direction.items():
        if infer_activity_kind(signal) != "new_practice":
            continue
        if (snapshot.learning_item_id, direction) in auto_skipped:
            continue
        return True
    return False


def _drop_blocked_new_practice(
    ranked: tuple[RankedRecommendation, ...],
    *,
    explicit_known_ids: frozenset[str],
    auto_skipped: set[tuple[str, SkillDirection]],
) -> tuple[RankedRecommendation, ...]:
    return tuple(
        row
        for row in ranked
        if not should_drop_today_candidate(
            activity_kind=row.activity_kind,
            explicit_known=row.learning_item_id in explicit_known_ids,
            auto_skip_new=(row.learning_item_id, row.skill_direction) in auto_skipped,
        )
    )


def _tracked_pattern(
    report: WeaknessPatternReport,
    pattern_key: str | None,
) -> tuple[bool | None, bool | None, int]:
    if pattern_key is None:
        return None, None, 0
    for pattern in report.patterns:
        if pattern.pattern_key != pattern_key:
            continue
        return (
            pattern.by_direction["recognition"].is_weakness,
            pattern.by_direction["production"].is_weakness,
            pattern.by_direction["production"].recent_attempt_count,
        )
    return False, False, 0


def _require_contiguous_days(scenario: LearningQualityScenario) -> None:
    indexes = [day.day_index for day in scenario.days]
    expected = list(range(len(scenario.days)))
    if indexes != expected:
        raise ValueError(f"day_index は 0 から連続である必要がある: {indexes}")


def _metrics(days: Sequence[DayMetrics]) -> LearningQualityMetrics:
    rate = _same_context_rate(
        [selection for day in days for selection in day.context_selections]
    )
    return LearningQualityMetrics(
        day_count=len(days),
        admitted_new_per_day=tuple(day.admitted_count for day in days),
        deferred_new_per_day=tuple(day.deferred_count for day in days),
        due_backlog_per_day=tuple(day.due_review_count for day in days),
        overdue_per_day=tuple(day.overdue_count for day in days),
        known_skip_per_day=tuple(day.known_skip_count for day in days),
        weakness_count_per_day=tuple(day.weakness_count for day in days),
        plan_size_per_day=tuple(day.plan_size for day in days),
        max_new_per_day=tuple(day.max_new_count for day in days),
        review_count_per_day=tuple(day.review_count for day in days),
        new_count_per_day=tuple(day.new_count for day in days),
        recognition_count=sum(day.recognition_count for day in days),
        production_count=sum(day.production_count for day in days),
        repeated_same_context_rate=rate,
        known_skip_total=sum(day.known_skip_count for day in days),
    )


def _same_context_rate(
    selections: Sequence[tuple[str, str, str, int]],
) -> float | None:
    grouped: dict[tuple[str, str], list[str]] = {}
    for item_id, exercise_type, source_id, candidate_count in selections:
        if candidate_count < 2:
            continue
        grouped.setdefault((item_id, exercise_type), []).append(source_id)
    pairs = 0
    repeats = 0
    for sources in grouped.values():
        for previous, current in zip(sources, sources[1:], strict=False):
            pairs += 1
            if previous == current:
                repeats += 1
    if pairs == 0:
        return None
    return repeats / pairs


# ---------------------------------------------------------------------------
# invariants
# ---------------------------------------------------------------------------


def _evaluate_invariants(
    scenario: LearningQualityScenario,
    days: Sequence[DayMetrics],
    versions: PolicyVersions,
) -> tuple[QualityCheck, ...]:
    expectations = scenario.expectations
    return (
        _check_due_priority(days),
        _check_new_follows_admission(days),
        _check_due_backlog(days, require=expectations.require_high_due_backlog),
        _check_known(scenario, days, require=expectations.require_known_skip),
        _check_source_cap(days, require=expectations.require_source_cap_pressure),
        _check_duplicates(days, require=expectations.require_duplicate_deferral),
        _check_context(
            scenario,
            days,
            require=expectations.require_context_rotation,
        ),
        _check_weakness(scenario, days),
        _check_load(days, require=expectations.require_difficult_recovery),
        _check_overdue(days, require=expectations.require_overdue),
        _check_directions(days, require=expectations.require_both_directions),
        _check_versions(versions),
    )


def _check(name: str, problems: list[str], ok_detail: str) -> QualityCheck:
    if problems:
        return QualityCheck(name=name, passed=False, detail="; ".join(problems))
    return QualityCheck(name=name, passed=True, detail=ok_detail)


def _check_due_priority(days: Sequence[DayMetrics]) -> QualityCheck:
    problems: list[str] = []
    for day in days:
        seen_new = False
        for kind in day.entry_kinds:
            if kind == "new_practice":
                seen_new = True
            elif kind == "review" and seen_new:
                problems.append(f"day {day.day_index}: review が new より後ろ")
                break
        if day.deferred_due_count > 0 and day.new_count > 0:
            problems.append(
                f"day {day.day_index}: deferred due {day.deferred_due_count} "
                f"なのに new {day.new_count}"
            )
        if day.due_review_count > 0 and day.review_count == 0:
            problems.append(
                f"day {day.day_index}: due {day.due_review_count} なのに review 0"
            )
    return _check(
        "due_reviews_are_prioritized",
        problems,
        "due review が new より先で、入りきらない due がある日は new を入れない",
    )


def _check_new_follows_admission(days: Sequence[DayMetrics]) -> QualityCheck:
    problems: list[str] = []
    for day in days:
        admitted = set(day.admitted_ids)
        extra = [item_id for item_id in day.new_item_ids if item_id not in admitted]
        if extra:
            problems.append(f"day {day.day_index}: admission 外の new {extra}")
        if day.new_count > day.max_new_count:
            problems.append(
                f"day {day.day_index}: new {day.new_count} が "
                f"max_new {day.max_new_count} を超えた"
            )
        if day.admitted_count > day.admission_budget:
            problems.append(
                f"day {day.day_index}: admitted {day.admitted_count} > "
                f"budget {day.admission_budget}"
            )
    return _check(
        "new_entries_follow_admission",
        problems,
        "Plan の新規は admission 済みかつ max_new 以内",
    )


def _check_due_backlog(days: Sequence[DayMetrics], *, require: bool) -> QualityCheck:
    problems: list[str] = []
    high = [day for day in days if day.due_review_count >= DUE_BACKLOG_SOFT_THRESHOLD]
    for day in high:
        if day.due_review_count >= DUE_BACKLOG_HARD_THRESHOLD:
            if day.admission_budget != SUPPRESSED_NEW_ADMISSION_CAP:
                problems.append(
                    f"day {day.day_index}: due {day.due_review_count} で "
                    f"budget {day.admission_budget}"
                )
            if day.max_new_count != 0:
                problems.append(
                    f"day {day.day_index}: due {day.due_review_count} で "
                    f"max_new {day.max_new_count}"
                )
            if day.admitted_count != 0:
                problems.append(
                    f"day {day.day_index}: hard backlog なのに "
                    f"admitted {day.admitted_count}"
                )
            continue
        if day.admission_budget > REDUCED_NEW_ADMISSION_CAP:
            problems.append(
                f"day {day.day_index}: due {day.due_review_count} で "
                f"budget {day.admission_budget}"
            )
        if day.max_new_count > 1:
            problems.append(
                f"day {day.day_index}: due {day.due_review_count} で "
                f"max_new {day.max_new_count}"
            )
        if day.admitted_count > day.admission_budget:
            problems.append(f"day {day.day_index}: admitted が budget を超えた")
    if require and not high:
        problems.append(f"due が {DUE_BACKLOG_SOFT_THRESHOLD} 以上の日がない")
    detail = (
        f"due {DUE_BACKLOG_SOFT_THRESHOLD} 以上の日は新規を抑え、"
        f"{DUE_BACKLOG_HARD_THRESHOLD} 以上では新規を止める"
    )
    if not high and not require:
        detail = "high backlog の日は無い。抑制規則の対象外"
    return _check("due_backlog_suppresses_new", problems, detail)


def _check_known(
    scenario: LearningQualityScenario,
    days: Sequence[DayMetrics],
    *,
    require: bool,
) -> QualityCheck:
    problems: list[str] = []
    known = scenario.known_item_ids
    if not known and not require:
        return _check(
            "known_items_do_not_consume_new_slots",
            [],
            "既知項目は無い",
        )
    for day in days:
        used = [
            item_id
            for item_id in (*day.admitted_ids, *day.new_item_ids)
            if item_id in known
        ]
        if used:
            problems.append(f"day {day.day_index}: known が新規に入った {used}")
    if require and sum(day.known_skip_count for day in days) <= 0:
        problems.append("既知項目の skip が一度も無い")
    return _check(
        "known_items_do_not_consume_new_slots",
        problems,
        "explicit known は new 枠に入らない",
    )


def _check_source_cap(days: Sequence[DayMetrics], *, require: bool) -> QualityCheck:
    problems: list[str] = []
    pressured = False
    for day in days:
        admitted = dict(day.admitted_by_source)
        for source_id, count in day.admitted_by_source:
            if count > PER_SOURCE_ADMISSION_CAP:
                problems.append(f"day {day.day_index}: {source_id} が {count} 件 admit")
        for source_id, unseen in day.unseen_by_source:
            taken = admitted.get(source_id, 0)
            others = day.admitted_count - taken
            if (
                unseen > PER_SOURCE_ADMISSION_CAP
                and taken == PER_SOURCE_ADMISSION_CAP
                and others > 0
            ):
                pressured = True
    if require and not pressured:
        problems.append("在庫が多くても他 Source と枠を分ける日がない")
    return _check(
        "single_source_does_not_monopolize",
        problems,
        f"同一 Source の admit は {PER_SOURCE_ADMISSION_CAP} 件まで",
    )


def _check_duplicates(days: Sequence[DayMetrics], *, require: bool) -> QualityCheck:
    problems: list[str] = []
    deferred = False
    for day in days:
        if len(day.admitted_forms) != len(set(day.admitted_forms)):
            problems.append(f"day {day.day_index}: 同じ表記を複数 admit")
        if dict(day.deferral_reasons).get("DUPLICATE_OR_REDUNDANT", 0) > 0:
            deferred = True
    if require and not deferred:
        problems.append("DUPLICATE_OR_REDUNDANT の見送りが無い")
    return _check(
        "duplicate_expression_is_deferred",
        problems,
        "同じ表記の未学習は 1 件だけ admit する",
    )


def _check_context(
    scenario: LearningQualityScenario,
    days: Sequence[DayMetrics],
    *,
    require: bool,
) -> QualityCheck:
    problems: list[str] = []
    selections = [selection for day in days for selection in day.context_selections]
    rate = _same_context_rate(selections)
    if rate not in (None, 0.0):
        problems.append(f"連続して同じ文脈を選んだ割合が {rate:.3f}")
    tracked = scenario.tracked_context_item_id
    varied = False
    if tracked is not None:
        grouped: dict[str, list[str]] = {}
        for item_id, exercise_type, source_id, candidate_count in selections:
            if item_id != tracked or candidate_count < 2:
                continue
            grouped.setdefault(exercise_type, []).append(source_id)
        for exercise_type, sources in grouped.items():
            if len(sources) < 2:
                continue
            if len(set(sources)) >= 2 and all(
                previous != current
                for previous, current in zip(sources, sources[1:], strict=False)
            ):
                varied = True
            elif len(set(sources)) < 2:
                problems.append(
                    f"{tracked} の {exercise_type} が同じ文脈のまま: {sources}"
                )
    if require and not varied:
        problems.append("複数文脈の item が別文脈へ移った履歴がない")
    return _check(
        "context_does_not_stay_fixed",
        problems,
        "複数文脈は直近と同じ出典に固定されない",
    )


def _check_weakness(
    scenario: LearningQualityScenario,
    days: Sequence[DayMetrics],
) -> QualityCheck:
    expectations = scenario.expectations
    if expectations.require_no_weakness:
        problems = [
            f"day {day.day_index}: weakness {day.weakness_count}"
            for day in days
            if day.weakness_count != 0
        ]
        return _check(
            "sparse_errors_are_not_a_pattern",
            problems,
            "少数誤答だけでは WeaknessPattern を断定しない",
        )
    if not expectations.require_production_only_weakness:
        return _check(
            "production_weakness_spares_recognition",
            [],
            "弱点の断定はこのシナリオでは要求しない",
        )
    problems: list[str] = []
    saw_weak = False
    saw_below_threshold = False
    for day in days:
        if day.tracked_recognition_weak:
            problems.append(
                f"day {day.day_index}: production だけの弱点が recognition まで弱い"
            )
        if day.tracked_production_attempts < MIN_ATTEMPTS:
            saw_below_threshold = True
            if day.tracked_production_weak:
                problems.append(
                    f"day {day.day_index}: attempt {day.tracked_production_attempts} "
                    "で production を弱点にした"
                )
        elif day.tracked_production_weak:
            saw_weak = True
    if not saw_below_threshold:
        problems.append("閾値未満の日がなく、少数誤答の不変条件を見ていない")
    if not saw_weak:
        problems.append("production の横断弱点が一度も検出されない")
    return _check(
        "production_weakness_spares_recognition",
        problems,
        "production だけの弱点は recognition を弱点にしない",
    )


def _check_load(days: Sequence[DayMetrics], *, require: bool) -> QualityCheck:
    problems: list[str] = []
    for day in days:
        if day.adaptive_reasons == ("STABLE_PROGRESS",) and (
            day.max_new_count != DEFAULT_MAX_NEW_COUNT
            or day.requested_count != DEFAULT_PLAN_SIZE
        ):
            problems.append(
                f"day {day.day_index}: STABLE なのに "
                f"total {day.requested_count} / max_new {day.max_new_count}"
            )
        if "RECENT_ERROR_RATE_HIGH" in day.adaptive_reasons and (
            day.max_new_count >= DEFAULT_MAX_NEW_COUNT
        ):
            problems.append(
                f"day {day.day_index}: 誤答圧力なのに max_new {day.max_new_count}"
            )
    if not require:
        return _check(
            "load_returns_after_difficult_period",
            problems,
            "負荷の往復はこのシナリオでは要求しない",
        )
    error_days = [
        day
        for day in days
        if "RECENT_ERROR_RATE_HIGH" in day.adaptive_reasons
        and day.max_new_count < DEFAULT_MAX_NEW_COUNT
    ]
    if not error_days:
        problems.append("難しい期間のあと max_new が下がった日がない")
        return _check("load_returns_after_difficult_period", problems, "")
    later = [
        day
        for day in days
        if day.day_index > error_days[0].day_index
        and day.adaptive_reasons == ("STABLE_PROGRESS",)
        and day.max_new_count == DEFAULT_MAX_NEW_COUNT
        and day.requested_count == DEFAULT_PLAN_SIZE
    ]
    if not later:
        problems.append("状態改善後にデフォルトの 10 問・新規 3 件へ戻らない")
    return _check(
        "load_returns_after_difficult_period",
        problems,
        "難しい期間は max_new を下げ、改善後はデフォルトへ戻る",
    )


def _check_overdue(days: Sequence[DayMetrics], *, require: bool) -> QualityCheck:
    if not require:
        return _check("overdue_is_visible", [], "overdue はこのシナリオでは要求しない")
    peak = max((day.overdue_count for day in days), default=0)
    if peak < 1:
        return _check(
            "overdue_is_visible",
            ["overdue が一度も発生しない"],
            "",
        )
    return _check(
        "overdue_is_visible",
        [],
        f"欠席後の overdue 最大 {peak}",
    )


def _check_directions(days: Sequence[DayMetrics], *, require: bool) -> QualityCheck:
    recognition = sum(day.recognition_count for day in days)
    production = sum(day.production_count for day in days)
    if not require:
        return _check(
            "direction_balance_is_recorded",
            [],
            f"recognition {recognition} / production {production}",
        )
    problems: list[str] = []
    if recognition <= 0 or production <= 0:
        problems.append(
            f"direction が片側だけ: recognition {recognition} / production {production}"
        )
    return _check(
        "direction_balance_is_recorded",
        problems,
        f"recognition {recognition} / production {production}",
    )


def _check_versions(versions: PolicyVersions) -> QualityCheck:
    expected = {
        "feature_version": FEATURE_VERSION,
        "ranking_policy_version": RANKING_POLICY_VERSION,
        "plan_policy_version": PLAN_POLICY_VERSION,
        "admission_policy_version": ADMISSION_POLICY_VERSION,
        "adaptive_load_policy_version": ADAPTIVE_POLICY_VERSION,
        "context_policy_version": CONTEXT_POLICY_VERSION,
        "weakness_pattern_version": PATTERN_VERSION,
        "known_item_policy_version": KNOWN_POLICY_VERSION,
    }
    actual = versions.to_dict()
    problems = [
        f"{key}={actual[key]}"
        for key, value in expected.items()
        if actual[key] != value
    ]
    return _check(
        "policy_versions_are_reported",
        problems,
        "feature / ranking / plan / admission / adaptive / context の版を残す",
    )
