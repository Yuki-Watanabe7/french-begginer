"""新規 LearningItem の admission policy（Issue #200）。

テスト対象: `app.domain.admission_policy` と TodayLearningService への接続。
OpenAI / wall clock には依存しない。defer は status を変えず、条件が
変われば同じ Item を再度 eligible にする。
"""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime, timedelta

import pytest

from app.domain.admission_policy import (
    DAILY_INTRODUCTION_QUOTA,
    DUE_BACKLOG_HARD_THRESHOLD,
    DUE_BACKLOG_SOFT_THRESHOLD,
    NORMAL_NEW_ADMISSION_CAP,
    PER_SOURCE_ADMISSION_CAP,
    POLICY_VERSION,
    REDUCED_NEW_ADMISSION_CAP,
    AdmissionResult,
    InvalidAdmissionInputError,
    UnseenBacklogItem,
    build_unseen_backlog_item,
    compute_admission_budget,
    count_due_review_units,
    count_recent_introductions,
    decide_new_admissions,
    filter_ranked_new_practice,
    normalize_canonical_form,
    select_primary_source_id,
)
from app.domain.daily_learning_plan import (
    DEFAULT_MAX_NEW_COUNT,
    PlanConstraints,
    build_daily_learning_plan,
)
from app.domain.recommendation_ranking import rank_recommendations
from app.domain.recommendation_signal import (
    FEATURE_VERSION,
    DirectionSignal,
    RecommendationSignalSnapshot,
)
from app.domain.tutor import LearningItem, SourceDocument, SourceRef
from app.repositories.sqlite import TutorSqliteStore
from app.services.today_learning_service import build_today_learning_service
from app.services.tutor_service import build_tutor_service

_NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def _item(
    item_id: str,
    *,
    form: str | None = None,
    level_distance: int | None = 0,
    source_recency_days: float | None = 1.0,
    primary_source_id: str | None = None,
    interest_weight: float = 1.0,
    importance_weight: float = 1.0,
) -> UnseenBacklogItem:
    return UnseenBacklogItem(
        learning_item_id=item_id,
        canonical_form=item_id if form is None else form,
        level_distance=level_distance,
        source_recency_days=source_recency_days,
        primary_source_id=primary_source_id,
        interest_weight=interest_weight,
        importance_weight=importance_weight,
    )


def _decide(
    items: list[UnseenBacklogItem],
    *,
    due: int = 0,
    recent: int = 0,
    now: datetime = _NOW,
) -> AdmissionResult:
    return decide_new_admissions(
        items,
        due_review_count=due,
        recent_introduced_count=recent,
        now=now,
    )


def _by_id(result: AdmissionResult) -> dict[str, tuple[str, tuple[str, ...]]]:
    return {
        row.learning_item_id: (row.outcome, row.reason_codes)
        for row in result.decisions
    }


def _direction(
    skill_direction: str,
    *,
    attempt_count: int = 0,
    review_urgency: str = "unscheduled",
    overdue_days: float = 0.0,
    mastery_score: float = 0.0,
) -> DirectionSignal:
    return DirectionSignal(
        skill_direction=skill_direction,  # type: ignore[arg-type]
        mastery_score=mastery_score,
        attempt_count=attempt_count,
        consecutive_correct=0,
        is_unseen=attempt_count == 0,
        review_urgency=review_urgency,  # type: ignore[arg-type]
        overdue_days=overdue_days,
        lapse_count=0,
        recent_error_rate=0.0,
        recent_incorrect_count=0,
        recent_correct_count=0,
    )


def _snapshot(
    item_id: str,
    *,
    recognition: DirectionSignal | None = None,
    production: DirectionSignal | None = None,
    level_distance: int | None = None,
    source_recency_days: float | None = None,
) -> RecommendationSignalSnapshot:
    return RecommendationSignalSnapshot(
        learning_item_id=item_id,
        computed_at=_NOW,
        feature_version=FEATURE_VERSION,
        by_direction={
            "recognition": recognition or _direction("recognition"),
            "production": production or _direction("production"),
        },
        item_level=None,
        learner_level="B1",
        level_distance=level_distance,
        source_recency_days=source_recency_days,
        source_ref_count=0,
        interest_weight=1.0,
        importance_weight=1.0,
    )


def _vocab(item_id: str, *, status: str = "active") -> LearningItem:
    return LearningItem(
        id=item_id,
        item_type="vocabulary",
        canonical_form=item_id,
        meaning_ja=f"{item_id}の意味",
        status=status,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# 定数と budget
# ---------------------------------------------------------------------------


def test_constants_leave_room_for_existing_today_plans() -> None:
    """Phase 5 の少件数と Phase 6 の新規 7 件 / Source あたり 2 件を残す。"""
    assert NORMAL_NEW_ADMISSION_CAP >= 7
    assert NORMAL_NEW_ADMISSION_CAP >= DEFAULT_MAX_NEW_COUNT
    assert PER_SOURCE_ADMISSION_CAP >= 2
    assert PER_SOURCE_ADMISSION_CAP < NORMAL_NEW_ADMISSION_CAP
    assert DUE_BACKLOG_SOFT_THRESHOLD > 4
    assert DAILY_INTRODUCTION_QUOTA >= NORMAL_NEW_ADMISSION_CAP


def test_budget_follows_due_and_recent_introductions() -> None:
    assert (
        compute_admission_budget(due_review_count=0, recent_introduced_count=0)
        == NORMAL_NEW_ADMISSION_CAP
    )
    assert (
        compute_admission_budget(
            due_review_count=DUE_BACKLOG_SOFT_THRESHOLD - 1,
            recent_introduced_count=0,
        )
        == NORMAL_NEW_ADMISSION_CAP
    )
    assert (
        compute_admission_budget(
            due_review_count=DUE_BACKLOG_SOFT_THRESHOLD,
            recent_introduced_count=0,
        )
        == REDUCED_NEW_ADMISSION_CAP
    )
    assert (
        compute_admission_budget(
            due_review_count=DUE_BACKLOG_HARD_THRESHOLD,
            recent_introduced_count=0,
        )
        == 0
    )
    assert (
        compute_admission_budget(
            due_review_count=0,
            recent_introduced_count=DAILY_INTRODUCTION_QUOTA,
        )
        == 0
    )
    assert (
        compute_admission_budget(
            due_review_count=0,
            recent_introduced_count=DAILY_INTRODUCTION_QUOTA - 1,
        )
        == 1
    )


def test_negative_counts_and_naive_now_are_rejected() -> None:
    with pytest.raises(InvalidAdmissionInputError):
        compute_admission_budget(due_review_count=-1, recent_introduced_count=0)
    with pytest.raises(InvalidAdmissionInputError):
        _decide([_item("a")], now=datetime(2026, 10, 1, 12, 0))


# ---------------------------------------------------------------------------
# due backlog
# ---------------------------------------------------------------------------


def test_high_due_backlog_suppresses_new_admission() -> None:
    items = [_item(f"item-{index:02d}", primary_source_id=None) for index in range(10)]
    result = _decide(items, due=DUE_BACKLOG_HARD_THRESHOLD)
    assert result.policy_version == POLICY_VERSION
    assert result.admission_budget == 0
    assert result.admitted_ids == ()
    reasons = _by_id(result)
    assert all(outcome == "defer" for outcome, _reason in reasons.values())
    review_held = [
        item_id
        for item_id, (outcome, reason) in reasons.items()
        if outcome == "defer" and reason == ("REVIEW_BACKLOG_HIGH",)
    ]
    assert len(review_held) == NORMAL_NEW_ADMISSION_CAP
    assert ("HIGHER_PRIORITY_NEW_EXISTS",) in {
        reason for _outcome, reason in reasons.values()
    }


def test_low_due_backlog_allows_new_admission() -> None:
    items = [_item(f"item-{index}") for index in range(3)]
    result = _decide(items, due=1)
    assert result.admission_budget == NORMAL_NEW_ADMISSION_CAP
    assert set(result.admitted_ids) == {item.learning_item_id for item in items}
    assert all(
        row.outcome == "admit" and row.reason_codes == () for row in result.decisions
    )


def test_soft_due_backlog_keeps_a_small_new_quota() -> None:
    items = [
        _item("newer", source_recency_days=1),
        _item("older", source_recency_days=10),
        _item("oldest", source_recency_days=20),
    ]
    result = _decide(items, due=DUE_BACKLOG_SOFT_THRESHOLD)
    assert result.admission_budget == REDUCED_NEW_ADMISSION_CAP
    assert result.admitted_ids == ("newer",)
    assert _by_id(result)["older"] == ("defer", ("REVIEW_BACKLOG_HIGH",))
    assert _by_id(result)["oldest"] == ("defer", ("REVIEW_BACKLOG_HIGH",))


def test_recent_introductions_consume_the_quota_without_rejecting() -> None:
    items = [_item(f"item-{index}") for index in range(3)]
    blocked = _decide(items, recent=DAILY_INTRODUCTION_QUOTA)
    assert blocked.admission_budget == 0
    assert blocked.admitted_ids == ()
    assert all(
        row.reason_codes == ("HIGHER_PRIORITY_NEW_EXISTS",) for row in blocked.decisions
    )
    opened = _decide(items, recent=0)
    assert set(opened.admitted_ids) == {item.learning_item_id for item in items}


# ---------------------------------------------------------------------------
# Source cap と公平性
# ---------------------------------------------------------------------------


def test_single_source_does_not_fill_the_admission_budget() -> None:
    items = [
        _item(f"pdf-{index:02d}", primary_source_id="pdf-long", source_recency_days=1)
        for index in range(10)
    ]
    result = _decide(items, due=0)
    assert len(result.admitted_ids) == PER_SOURCE_ADMISSION_CAP
    assert len(result.admitted_ids) < result.admission_budget
    deferred = [row for row in result.decisions if row.outcome == "defer"]
    assert len(deferred) == 8
    assert all(row.reason_codes == ("SOURCE_DAILY_CAP",) for row in deferred)


def test_multiple_sources_are_fair_and_deterministic() -> None:
    items = [
        _item("a1", primary_source_id="source-a", source_recency_days=1),
        _item("a2", primary_source_id="source-a", source_recency_days=1),
        _item("a3", primary_source_id="source-a", source_recency_days=1),
        _item("b1", primary_source_id="source-b", source_recency_days=10),
        _item("b2", primary_source_id="source-b", source_recency_days=10),
    ]
    first = _decide(items)
    second = _decide(list(reversed(items)))
    assert first == second
    assert first.admitted_ids == ("a1", "b1", "a2", "b2")
    assert _by_id(first)["a3"] == ("defer", ("SOURCE_DAILY_CAP",))
    per_source = {"source-a": 0, "source-b": 0}
    by_item = {item.learning_item_id: item for item in items}
    for item_id in first.admitted_ids:
        source_id = by_item[item_id].primary_source_id
        assert source_id is not None
        per_source[source_id] += 1
    assert per_source == {"source-a": PER_SOURCE_ADMISSION_CAP, "source-b": 2}


def test_overflow_beyond_budget_is_higher_priority_not_a_stored_reject() -> None:
    extra = NORMAL_NEW_ADMISSION_CAP + 2
    items = [_item(f"item-{index:02d}") for index in range(extra)]
    result = _decide(items)
    assert len(result.admitted_ids) == NORMAL_NEW_ADMISSION_CAP
    deferred = [row for row in result.decisions if row.outcome == "defer"]
    higher = ("HIGHER_PRIORITY_NEW_EXISTS",)
    assert [row.reason_codes for row in deferred] == [higher, higher]


def test_same_state_and_now_returns_the_same_result() -> None:
    items = [
        _item("m", primary_source_id="s1", importance_weight=2),
        _item("n", primary_source_id="s2", interest_weight=2),
        _item("o", form="Bonjour"),
        _item("p", form="bonjour", source_recency_days=20),
    ]
    assert _decide(items) == _decide(items, now=_NOW)


# ---------------------------------------------------------------------------
# CEFR / 重複 / 再 eligible
# ---------------------------------------------------------------------------


def test_unknown_cefr_is_not_excluded() -> None:
    items = [
        _item("close", level_distance=0),
        _item("unknown", level_distance=None),
        _item("near", level_distance=2),
        _item("far", level_distance=4),
    ]
    result = _decide(items)
    outcomes = _by_id(result)
    assert outcomes["unknown"][0] == "admit"
    assert outcomes["close"][0] == "admit"
    assert outcomes["near"][0] == "admit"
    assert outcomes["far"] == ("defer", ("LEVEL_TOO_FAR_FOR_NOW",))
    assert "LEVEL_TOO_FAR_FOR_NOW" not in outcomes["unknown"][1]


def test_duplicate_forms_defer_the_lower_priority_copy() -> None:
    items = [
        _item("winner", form="rendez-vous", source_recency_days=1),
        _item("loser", form="rendez vous", source_recency_days=20),
        _item("case-winner", form="Café", source_recency_days=1),
        _item("case-loser", form="café", source_recency_days=15),
    ]
    result = _decide(items)
    outcomes = _by_id(result)
    assert outcomes["winner"][0] == "admit"
    assert outcomes["case-winner"][0] == "admit"
    assert outcomes["loser"] == ("defer", ("DUPLICATE_OR_REDUNDANT",))
    assert outcomes["case-loser"] == ("defer", ("DUPLICATE_OR_REDUNDANT",))
    assert normalize_canonical_form("où") != normalize_canonical_form("ou")


def test_deferred_item_becomes_eligible_when_conditions_change() -> None:
    waiting = _item("waiting")
    held = _decide([waiting], due=DUE_BACKLOG_HARD_THRESHOLD)
    assert _by_id(held)["waiting"] == ("defer", ("REVIEW_BACKLOG_HIGH",))
    released = _decide([waiting], due=0)
    assert _by_id(released)["waiting"] == ("admit", ())

    winner = _item("winner", form="gare", source_recency_days=1)
    duplicate = _item("duplicate", form="gare", source_recency_days=12)
    crowded = _decide([winner, duplicate])
    assert _by_id(crowded)["duplicate"] == ("defer", ("DUPLICATE_OR_REDUNDANT",))
    alone = _decide([duplicate])
    assert _by_id(alone)["duplicate"] == ("admit", ())


# ---------------------------------------------------------------------------
# Phase 5 plan との境界
# ---------------------------------------------------------------------------


def test_max_new_count_still_bounds_the_plan() -> None:
    wide = [_item(f"new-{index:02d}") for index in range(5)]
    wide_plan, wide_admission = _plan_for(wide, due=0, max_new_count=3)
    assert len(wide_admission.admitted_ids) == 5
    assert wide_plan.new_count == 3
    assert wide_plan.new_count == DEFAULT_MAX_NEW_COUNT

    capped = _plan_for(wide, due=0, max_new_count=0)[0]
    assert capped.new_count == 0

    tight = [_item(f"tight-{index}") for index in range(4)]
    tight_plan, tight_admission = _plan_for(
        tight,
        due=DUE_BACKLOG_SOFT_THRESHOLD,
        max_new_count=3,
    )
    assert tight_admission.admission_budget == REDUCED_NEW_ADMISSION_CAP
    assert tight_plan.new_count == 1


def test_deferring_a_new_direction_keeps_the_due_review() -> None:
    item = _vocab("mixed")
    snapshot = _snapshot(
        item.id,
        recognition=_direction(
            "recognition",
            attempt_count=2,
            review_urgency="due",
            overdue_days=2,
            mastery_score=0.5,
        ),
        production=_direction("production"),
        level_distance=4,
    )
    backlog = build_unseen_backlog_item(item, snapshot)
    assert backlog is not None
    admission = _decide([backlog], due=1)
    ranked = rank_recommendations([snapshot])
    filtered = filter_ranked_new_practice(ranked, admission)
    assert any(row.activity_kind == "review" for row in filtered)
    assert all(row.activity_kind != "new_practice" for row in filtered)
    assert _by_id(admission)[item.id] == ("defer", ("LEVEL_TOO_FAR_FOR_NOW",))


def test_build_unseen_backlog_skips_inactive_and_seen_items() -> None:
    active = _vocab("active")
    unseen = _snapshot(active.id)
    assert build_unseen_backlog_item(active, unseen) is not None
    paused = _vocab("paused", status="suspended")
    assert build_unseen_backlog_item(paused, _snapshot(paused.id)) is None
    seen = _snapshot(
        "seen",
        recognition=_direction(
            "recognition",
            attempt_count=3,
            review_urgency="future",
            mastery_score=1,
        ),
        production=_direction(
            "production",
            attempt_count=3,
            review_urgency="future",
            mastery_score=1,
        ),
    )
    assert build_unseen_backlog_item(_vocab("seen"), seen) is None


def test_primary_source_prefers_the_newest_document() -> None:
    older = SourceDocument(
        id="source-old",
        title="old",
        content="ancien",
        created_at=_NOW - timedelta(days=10),
    )
    newer = SourceDocument(
        id="source-new",
        title="new",
        content="nouveau",
        created_at=_NOW - timedelta(hours=1),
    )
    tied_a = SourceDocument(
        id="source-b",
        title="b",
        content="b",
        created_at=_NOW - timedelta(days=1),
    )
    tied_b = SourceDocument(
        id="source-a",
        title="a",
        content="a",
        created_at=_NOW - timedelta(days=1),
    )
    item = LearningItem(
        id="item",
        item_type="vocabulary",
        canonical_form="livre",
        meaning_ja="本",
        source_refs=[
            SourceRef(source_document_id=older.id),
            SourceRef(source_document_id=newer.id),
        ],
    )
    sources = {older.id: older, newer.id: newer}
    assert select_primary_source_id(item, sources) == "source-new"
    tied = LearningItem(
        id="tied",
        item_type="vocabulary",
        canonical_form="table",
        meaning_ja="机",
        source_refs=[
            SourceRef(source_document_id=tied_a.id),
            SourceRef(source_document_id=tied_b.id),
        ],
    )
    assert select_primary_source_id(tied, {tied_a.id: tied_a, tied_b.id: tied_b}) == (
        "source-a"
    )
    assert select_primary_source_id(item, {}) == "source-new"
    bare = _vocab("bare")
    assert select_primary_source_id(bare, {}) is None


def test_due_and_recent_introduction_counts() -> None:
    due = _snapshot(
        "due",
        recognition=_direction(
            "recognition",
            attempt_count=1,
            review_urgency="due",
            overdue_days=1,
            mastery_score=0,
        ),
    )
    fresh = _snapshot("fresh")
    assert count_due_review_units([due, fresh]) == 1
    first = {
        "started": _NOW - timedelta(days=1),
        "older": _NOW - timedelta(days=1, seconds=1),
        "future": _NOW + timedelta(seconds=1),
    }
    assert count_recent_introductions(first, now=_NOW) == 1


def test_future_source_recency_does_not_reject_the_item() -> None:
    result = _decide([_item("future", source_recency_days=-2)])
    assert result.admitted_ids == ("future",)


def test_duplicate_item_ids_are_rejected() -> None:
    with pytest.raises(InvalidAdmissionInputError):
        _decide([_item("same"), _item("same", form="autre")])


def test_module_does_not_import_llm() -> None:
    import app.domain.admission_policy as admission

    forbidden = {"openai", "anthropic", "langchain", "litellm"}
    tree = ast.parse(inspect.getsource(admission))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".", 1)[0])
    assert not (names & forbidden)


def _plan_for(
    items: list[UnseenBacklogItem],
    *,
    due: int,
    max_new_count: int,
    total_count: int = 10,
):
    admission = _decide(items, due=due)
    snapshots = [_snapshot(item.learning_item_id) for item in items]
    ranked = filter_ranked_new_practice(rank_recommendations(snapshots), admission)
    items_by_id = {
        item.learning_item_id: _vocab(item.learning_item_id) for item in items
    }
    plan = build_daily_learning_plan(
        ranked,
        items_by_id=items_by_id,
        constraints=PlanConstraints(
            total_count=total_count,
            max_new_count=max_new_count,
        ),
        generated_at=_NOW,
    )
    return plan, admission


# ---------------------------------------------------------------------------
# TodayLearningService
# ---------------------------------------------------------------------------


def _services():
    store = TutorSqliteStore.in_memory()
    tutor = build_tutor_service(store, clock=lambda: _NOW)
    today = build_today_learning_service(store, clock=lambda: _NOW)
    return store, tutor, today


def _stable_due(tutor, item: LearningItem) -> None:
    """recognition だけ due。production は未来予定で、導入は窓の外。"""
    tutor.record_review(
        item.id,
        exercise_type="ja_to_fr",
        result="correct",
        occurred_at=_NOW - timedelta(days=10),
    )
    tutor.record_review(
        item.id,
        exercise_type="ja_to_fr",
        result="correct",
        occurred_at=_NOW - timedelta(days=2),
    )
    tutor.record_review(
        item.id,
        exercise_type="meaning_recognition",
        result="incorrect",
        occurred_at=_NOW - timedelta(days=3),
    )


def test_today_plan_suppresses_new_when_due_backlog_is_high() -> None:
    _store, tutor, today = _services()
    for index in range(DUE_BACKLOG_HARD_THRESHOLD):
        item = tutor.create_item(
            item_type="vocabulary",
            canonical_form=f"due-{index}",
            meaning_ja=f"復習{index}",
        )
        _stable_due(tutor, item)
    for index in range(3):
        tutor.create_item(
            item_type="vocabulary",
            canonical_form=f"new-{index}",
            meaning_ja=f"新規{index}",
        )
    plan = today.get_plan(question_count=20, max_new_count=3)
    assert plan.review_count == DUE_BACKLOG_HARD_THRESHOLD
    assert plan.new_count == 0
    assert all(item.status == "active" for item in _store.learning_items.list())


def test_today_plan_admits_new_when_due_backlog_is_low() -> None:
    _store, tutor, today = _services()
    due = tutor.create_item(
        item_type="vocabulary",
        canonical_form="due-one",
        meaning_ja="復習",
    )
    _stable_due(tutor, due)
    for index in range(3):
        tutor.create_item(
            item_type="vocabulary",
            canonical_form=f"new-{index}",
            meaning_ja=f"新規{index}",
        )
    plan = today.get_plan(question_count=10, max_new_count=3)
    assert plan.review_count == 1
    assert plan.new_count == 3


def test_today_plan_does_not_let_one_source_fill_max_new() -> None:
    store, tutor, today = _services()
    source = store.source_documents.create(
        SourceDocument(
            title="long pdf",
            content="Un long document.",
            created_at=_NOW - timedelta(days=1),
        )
    )
    for index in range(6):
        tutor.create_item(
            item_type="vocabulary",
            canonical_form=f"mot-{index}",
            meaning_ja=f"語{index}",
            source_refs=[SourceRef(source_document_id=source.id)],
        )
    plan = today.get_plan(question_count=10, max_new_count=3)
    assert plan.new_count == PER_SOURCE_ADMISSION_CAP
    assert plan.new_count < 3
    forms = {row.canonical_form for row in plan.entries}
    assert forms <= {f"mot-{index}" for index in range(6)}
