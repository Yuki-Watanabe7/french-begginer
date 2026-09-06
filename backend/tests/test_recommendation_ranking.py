"""説明可能な Tutor ranking policy の単体テスト（Issue #176）。

テスト対象: `app.domain.recommendation_ranking`

固定 fixture で以下を確認する。OpenAI / wall clock 非依存。
"""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime
from datetime import timedelta as td

import pytest

from app.domain.recommendation_ranking import (
    ACTIVITY_KIND_ORDER,
    COMPONENT_NAMES,
    COMPONENT_WEIGHTS,
    DUE_BASE,
    POLICY_VERSION,
    REASON_TO_COMPONENT,
    MissingDirectionSignalError,
    RankedRecommendation,
    infer_activity_kind,
    rank_recommendations,
    recommendation_sort_key,
    score_recommendation,
)
from app.domain.recommendation_signal import (
    FEATURE_VERSION,
    DirectionSignal,
    RecommendationSignalSnapshot,
    extract_recommendation_signal,
)
from app.domain.tutor import LearningItem, ReviewSchedule, SkillDirection

_NOW = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _direction(
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


def _snapshot(
    learning_item_id: str,
    *,
    recognition: DirectionSignal | None = None,
    production: DirectionSignal | None = None,
    production_gap: float | None = None,
    item_level: str | None = None,
    learner_level: str = "B1",
    level_distance: int | None = None,
    source_recency_days: float | None = None,
    source_ref_count: int = 0,
    interest_weight: float = 1.0,
    importance_weight: float = 1.0,
) -> RecommendationSignalSnapshot:
    rec = recognition or _direction("recognition")
    prod = production or _direction("production")
    by_direction = {
        "recognition": rec,
        "production": prod,
    }
    return RecommendationSignalSnapshot(
        learning_item_id=learning_item_id,
        computed_at=_NOW,
        feature_version=FEATURE_VERSION,
        by_direction=by_direction,
        production_gap=production_gap,
        item_level=item_level,  # type: ignore[arg-type]
        learner_level=learner_level,  # type: ignore[arg-type]
        level_distance=level_distance,
        source_recency_days=source_recency_days,
        source_ref_count=source_ref_count,
        interest_weight=interest_weight,
        importance_weight=importance_weight,
    )


def _overdue_snapshot(
    item_id: str = "overdue",
    *,
    overdue_days: float = 2.0,
    direction: SkillDirection = "recognition",
    **kwargs,
) -> RecommendationSignalSnapshot:
    seen = _direction(
        direction,
        mastery_score=0.8,
        attempt_count=5,
        consecutive_correct=2,
        is_unseen=False,
        review_urgency="due",
        overdue_days=overdue_days,
    )
    args: dict = {
        "recognition": (
            seen if direction == "recognition" else _direction("recognition")
        ),
        "production": (seen if direction == "production" else _direction("production")),
    }
    args.update(kwargs)
    return _snapshot(item_id, **args)


def _new_snapshot(item_id: str = "new", **kwargs) -> RecommendationSignalSnapshot:
    return _snapshot(item_id, **kwargs)


def _ids(ranked: tuple[RankedRecommendation, ...]) -> list[tuple[str, str, str]]:
    return [(c.learning_item_id, c.skill_direction, c.activity_kind) for c in ranked]


# ---------------------------------------------------------------------------
# 1. overdue review が neutral new item より上位
# ---------------------------------------------------------------------------


class TestOverdueBeatsNew:
    def test_overdue_review_ranks_above_neutral_new_item(self) -> None:
        overdue = _overdue_snapshot("overdue", overdue_days=1.0)
        new = _new_snapshot("new")
        ranked = rank_recommendations([new, overdue])
        ids = _ids(ranked)
        assert ids[0] == ("overdue", "recognition", "review")
        assert ("new", "recognition", "new_practice") in ids
        assert ids.index(("overdue", "recognition", "review")) < ids.index(
            ("new", "recognition", "new_practice")
        )

    def test_just_due_still_beats_new(self) -> None:
        due = _overdue_snapshot("due", overdue_days=0.0)
        new = _new_snapshot("new")
        ranked = rank_recommendations([new, due])
        assert ranked[0].learning_item_id == "due"
        assert ranked[0].activity_kind == "review"


# ---------------------------------------------------------------------------
# 2. recent error が同条件 Item の優先度を上げる
# ---------------------------------------------------------------------------


class TestRecentErrorBoost:
    def test_recent_error_raises_priority_of_otherwise_equal_item(self) -> None:
        base_kwargs = dict(
            mastery_score=0.5,
            attempt_count=4,
            is_unseen=False,
            review_urgency="due",
            overdue_days=1.0,
        )
        clean = _snapshot(
            "clean",
            recognition=_direction("recognition", **base_kwargs),
        )
        errored = _snapshot(
            "errored",
            recognition=_direction(
                "recognition",
                **base_kwargs,
                recent_error_rate=0.8,
                recent_incorrect_count=4,
                last_incorrect_age_days=1.0,
            ),
        )
        ranked = rank_recommendations([clean, errored])
        review_ids = [
            c.learning_item_id
            for c in ranked
            if c.activity_kind == "review" and c.skill_direction == "recognition"
        ]
        assert review_ids[0] == "errored"
        errored_score = score_recommendation(errored, "recognition", "review")
        clean_score = score_recommendation(clean, "recognition", "review")
        assert (
            errored_score.components["recent_error"]
            > clean_score.components["recent_error"]
        )
        assert errored_score.total_score > clean_score.total_score


# ---------------------------------------------------------------------------
# 3. production gap で production が上位
# ---------------------------------------------------------------------------


class TestDirectionImbalance:
    def test_production_gap_ranks_production_above_recognition(self) -> None:
        rec = _direction(
            "recognition",
            mastery_score=0.9,
            attempt_count=10,
            is_unseen=False,
            review_urgency="due",
            overdue_days=0.0,
        )
        prod = _direction(
            "production",
            mastery_score=0.3,
            attempt_count=10,
            is_unseen=False,
            review_urgency="due",
            overdue_days=0.0,
        )
        snap = _snapshot(
            "gap-item",
            recognition=rec,
            production=prod,
            production_gap=0.6,
        )
        ranked = rank_recommendations([snap])
        review = [c for c in ranked if c.activity_kind == "review"]
        assert review[0].skill_direction == "production"
        assert review[1].skill_direction == "recognition"
        prod_score = score_recommendation(snap, "production", "review")
        rec_score = score_recommendation(snap, "recognition", "review")
        assert prod_score.components["direction_imbalance"] > 0
        assert rec_score.components["direction_imbalance"] == 0.0
        assert "PRODUCTION_WEAKER" in prod_score.reason_codes

    def test_recognition_weaker_is_symmetric(self) -> None:
        rec = _direction(
            "recognition",
            mastery_score=0.2,
            attempt_count=8,
            is_unseen=False,
            review_urgency="due",
            overdue_days=0.0,
        )
        prod = _direction(
            "production",
            mastery_score=0.9,
            attempt_count=8,
            is_unseen=False,
            review_urgency="due",
            overdue_days=0.0,
        )
        snap = _snapshot(
            "rev-gap",
            recognition=rec,
            production=prod,
            production_gap=-0.7,
        )
        rec_score = score_recommendation(snap, "recognition", "review")
        prod_score = score_recommendation(snap, "production", "review")
        assert rec_score.components["direction_imbalance"] > 0
        assert prod_score.components["direction_imbalance"] == 0.0
        assert "RECOGNITION_WEAKER" in rec_score.reason_codes


# ---------------------------------------------------------------------------
# 4. interest だけで overdue を押しのけない
# ---------------------------------------------------------------------------


class TestInterestDoesNotOverrideDue:
    def test_max_interest_does_not_outrank_overdue(self) -> None:
        overdue = _overdue_snapshot("overdue", overdue_days=0.0)
        interested = _new_snapshot(
            "interested",
            interest_weight=3.0,
            importance_weight=3.0,
            source_recency_days=0.0,
            source_ref_count=1,
            item_level="B1",
            level_distance=0,
        )
        ranked = rank_recommendations([interested, overdue])
        overdue_rank = next(
            i
            for i, c in enumerate(ranked)
            if c.learning_item_id == "overdue" and c.activity_kind == "review"
        )
        new_rank = next(
            i
            for i, c in enumerate(ranked)
            if c.learning_item_id == "interested" and c.activity_kind == "new_practice"
        )
        assert overdue_rank < new_rank

    def test_auxiliary_max_is_below_min_due(self) -> None:
        """weight 設計: interest+recency+importance+level_fit < ちょうど due。"""
        auxiliary = (
            COMPONENT_WEIGHTS["interest"]
            + COMPONENT_WEIGHTS["source_recency"]
            + COMPONENT_WEIGHTS["importance"]
            + COMPONENT_WEIGHTS["level_fit"]
        )
        min_due = COMPONENT_WEIGHTS["overdue"] * DUE_BASE
        assert min_due > auxiliary


# ---------------------------------------------------------------------------
# 5. unknown level を極端に不利にしない
# ---------------------------------------------------------------------------


class TestUnknownLevelNotPenalized:
    def test_unknown_level_is_not_far_below_perfect_fit(self) -> None:
        known = _new_snapshot("known", item_level="B1", level_distance=0)
        unknown = _new_snapshot("unknown", item_level=None, level_distance=None)
        known_score = score_recommendation(known, "recognition", "new_practice")
        unknown_score = score_recommendation(unknown, "recognition", "new_practice")
        delta = (
            known_score.components["level_fit"] - unknown_score.components["level_fit"]
        )
        # 未知は 0 寄与にせず、完璧フィットとの差は level_fit weight 未満
        assert unknown_score.components["level_fit"] > 0
        assert delta < COMPONENT_WEIGHTS["level_fit"]
        assert "LEVEL_FIT" not in unknown_score.reason_codes

    def test_far_level_is_not_excluded(self) -> None:
        far = _overdue_snapshot(
            "far",
            overdue_days=1.0,
            item_level="C2",
            learner_level="A1",
            level_distance=5,
        )
        ranked = rank_recommendations([far])
        assert any(c.learning_item_id == "far" for c in ranked)
        score = score_recommendation(far, "recognition", "review")
        assert score.components["level_fit"] == 0.0


# ---------------------------------------------------------------------------
# 6. unseen と low mastery を区別
# ---------------------------------------------------------------------------


class TestUnseenVsLowMastery:
    def test_unseen_does_not_get_low_mastery_component(self) -> None:
        unseen = _new_snapshot("unseen")
        score = score_recommendation(unseen, "recognition", "new_practice")
        assert score.components["low_mastery"] == 0.0
        assert "LOW_MASTERY" not in score.reason_codes

    def test_low_mastery_seen_item_gets_component(self) -> None:
        low = _snapshot(
            "low",
            recognition=_direction(
                "recognition",
                mastery_score=0.0,
                attempt_count=3,
                is_unseen=False,
                review_urgency="due",
                overdue_days=0.0,
            ),
        )
        score = score_recommendation(low, "recognition", "review")
        assert score.components["low_mastery"] > 0
        assert "LOW_MASTERY" in score.reason_codes

    def test_unseen_is_not_direction_imbalance(self) -> None:
        snap = _snapshot("one-sided", production_gap=None)
        score = score_recommendation(snap, "production", "new_practice")
        assert score.components["direction_imbalance"] == 0.0


# ---------------------------------------------------------------------------
# 7. same snapshot → same score / order
# ---------------------------------------------------------------------------


class TestDeterministic:
    def test_same_snapshot_same_score(self) -> None:
        snap = _overdue_snapshot(
            "same",
            overdue_days=3.0,
            interest_weight=1.5,
            source_recency_days=4.0,
            source_ref_count=1,
        )
        s1 = score_recommendation(snap, "recognition", "review")
        s2 = score_recommendation(snap, "recognition", "review")
        assert s1 == s2

    def test_same_snapshots_same_order(self) -> None:
        snapshots = [
            _new_snapshot("b", interest_weight=2.0),
            _overdue_snapshot("a", overdue_days=2.0),
            _new_snapshot("c"),
        ]
        r1 = rank_recommendations(snapshots)
        r2 = rank_recommendations(list(reversed(snapshots)))
        assert _ids(r1) == _ids(r2)
        assert [c.score for c in r1] == [c.score for c in r2]


# ---------------------------------------------------------------------------
# 8. tie-break deterministic
# ---------------------------------------------------------------------------


class TestTieBreak:
    def test_review_before_new_when_scores_equal(self) -> None:
        review_snap = _overdue_snapshot("item-r", overdue_days=1.0)
        new_snap = _new_snapshot("item-n")
        review = RankedRecommendation(
            learning_item_id="item-r",
            skill_direction="recognition",
            activity_kind="review",
            score=score_recommendation(review_snap, "recognition", "review").model_copy(
                update={"total_score": 1.0}
            ),
        )
        new = RankedRecommendation(
            learning_item_id="item-n",
            skill_direction="recognition",
            activity_kind="new_practice",
            score=score_recommendation(
                new_snap, "recognition", "new_practice"
            ).model_copy(update={"total_score": 1.0}),
        )
        by_id = {"item-r": review_snap, "item-n": new_snap}
        ordered = sorted(
            [new, review],
            key=lambda c: recommendation_sort_key(c, by_id[c.learning_item_id]),
        )
        assert ordered[0].activity_kind == "review"
        assert ACTIVITY_KIND_ORDER[0] == "review"

    def test_more_overdue_first_when_score_tied(self) -> None:
        a = _overdue_snapshot("item-a", overdue_days=5.0)
        b = _overdue_snapshot("item-b", overdue_days=1.0)
        cand_a = RankedRecommendation(
            learning_item_id="item-a",
            skill_direction="recognition",
            activity_kind="review",
            score=score_recommendation(a, "recognition", "review").model_copy(
                update={"total_score": 1.0}
            ),
        )
        cand_b = RankedRecommendation(
            learning_item_id="item-b",
            skill_direction="recognition",
            activity_kind="review",
            score=score_recommendation(b, "recognition", "review").model_copy(
                update={"total_score": 1.0}
            ),
        )
        ordered = sorted(
            [cand_b, cand_a],
            key=lambda c: recommendation_sort_key(
                c, {"item-a": a, "item-b": b}[c.learning_item_id]
            ),
        )
        assert ordered[0].learning_item_id == "item-a"

    def test_newer_source_first_for_new_practice_tie(self) -> None:
        newer = _new_snapshot("newer", source_recency_days=1.0, source_ref_count=1)
        older = _new_snapshot("older", source_recency_days=20.0, source_ref_count=1)
        equal_score = score_recommendation(
            newer, "recognition", "new_practice"
        ).model_copy(update={"total_score": 0.1})
        cand_new = RankedRecommendation(
            learning_item_id="newer",
            skill_direction="recognition",
            activity_kind="new_practice",
            score=equal_score,
        )
        cand_old = RankedRecommendation(
            learning_item_id="older",
            skill_direction="recognition",
            activity_kind="new_practice",
            score=equal_score,
        )
        ordered = sorted(
            [cand_old, cand_new],
            key=lambda c: recommendation_sort_key(
                c, {"newer": newer, "older": older}[c.learning_item_id]
            ),
        )
        assert ordered[0].learning_item_id == "newer"

    def test_item_id_then_direction(self) -> None:
        snap_m = _new_snapshot("item-m")
        snap_z = _new_snapshot("item-z")
        ranked = rank_recommendations([snap_z, snap_m])
        new_only = [c for c in ranked if c.activity_kind == "new_practice"]
        assert new_only[0].learning_item_id == "item-m"
        same_item = [c for c in new_only if c.learning_item_id == "item-m"]
        assert [c.skill_direction for c in same_item] == [
            "recognition",
            "production",
        ]


# ---------------------------------------------------------------------------
# 9. component 合計と total の整合
# ---------------------------------------------------------------------------


class TestComponentSum:
    def test_components_sum_to_total(self) -> None:
        snap = _overdue_snapshot(
            "sum",
            overdue_days=4.0,
            recognition=_direction(
                "recognition",
                mastery_score=0.4,
                attempt_count=6,
                is_unseen=False,
                review_urgency="due",
                overdue_days=4.0,
                lapse_count=2,
                recent_error_rate=0.5,
                last_incorrect_age_days=2.0,
            ),
            production_gap=0.3,
            item_level="B1",
            level_distance=0,
            source_recency_days=3.0,
            source_ref_count=1,
            interest_weight=2.0,
            importance_weight=1.5,
        )
        score = score_recommendation(snap, "recognition", "review")
        assert set(score.components) == set(COMPONENT_NAMES)
        assert score.total_score == pytest.approx(sum(score.components.values()))

    def test_all_components_are_finite_and_non_negative(self) -> None:
        snap = _overdue_snapshot("finite", overdue_days=10.0)
        score = score_recommendation(snap, "recognition", "review")
        for name, value in score.components.items():
            assert value >= 0.0, name
            assert value == value, name  # not NaN
            assert value <= COMPONENT_WEIGHTS[name] + 1e-9, name


# ---------------------------------------------------------------------------
# 10. reason code が component と一致
# ---------------------------------------------------------------------------


class TestReasonCodes:
    def test_reason_codes_match_positive_components(self) -> None:
        snap = _snapshot(
            "reasons",
            recognition=_direction(
                "recognition",
                mastery_score=0.2,
                attempt_count=5,
                is_unseen=False,
                review_urgency="due",
                overdue_days=3.0,
                lapse_count=3,
                recent_error_rate=0.7,
                last_incorrect_age_days=1.0,
            ),
            production=_direction(
                "production",
                mastery_score=0.8,
                attempt_count=5,
                is_unseen=False,
            ),
            production_gap=-0.6,
            item_level="B1",
            level_distance=0,
            source_recency_days=2.0,
            source_ref_count=1,
            interest_weight=2.5,
            importance_weight=2.0,
        )
        score = score_recommendation(snap, "recognition", "review")
        assert score.reason_codes
        assert "OVERDUE_REVIEW" in score.reason_codes
        assert "RECENT_ERROR" in score.reason_codes
        assert "RECOGNITION_WEAKER" in score.reason_codes
        for code in score.reason_codes:
            component = REASON_TO_COMPONENT[code]
            assert score.components[component] > 0, code

    def test_production_weaker_reason(self) -> None:
        snap = _snapshot(
            "prod-weak",
            recognition=_direction(
                "recognition",
                mastery_score=0.9,
                attempt_count=5,
                is_unseen=False,
                review_urgency="due",
                overdue_days=0.0,
            ),
            production=_direction(
                "production",
                mastery_score=0.2,
                attempt_count=5,
                is_unseen=False,
                review_urgency="due",
                overdue_days=0.0,
            ),
            production_gap=0.7,
        )
        score = score_recommendation(snap, "production", "review")
        assert "PRODUCTION_WEAKER" in score.reason_codes
        assert "RECOGNITION_WEAKER" not in score.reason_codes

    def test_new_practice_does_not_emit_overdue_reason(self) -> None:
        snap = _new_snapshot("fresh")
        score = score_recommendation(snap, "recognition", "new_practice")
        assert "OVERDUE_REVIEW" not in score.reason_codes


# ---------------------------------------------------------------------------
# 11. policy_version
# ---------------------------------------------------------------------------


class TestPolicyVersion:
    def test_policy_version_is_set(self) -> None:
        snap = _new_snapshot("v")
        score = score_recommendation(snap, "recognition", "new_practice")
        assert score.policy_version == POLICY_VERSION
        ranked = rank_recommendations([snap])
        assert all(c.score.policy_version == POLICY_VERSION for c in ranked)


# ---------------------------------------------------------------------------
# 12. activity_kind 推論 / 展開
# ---------------------------------------------------------------------------


class TestActivityKind:
    def test_due_is_review(self) -> None:
        signal = _direction("recognition", review_urgency="due", overdue_days=1.0)
        assert infer_activity_kind(signal) == "review"

    def test_unseen_is_new_practice(self) -> None:
        signal = _direction("recognition")
        assert infer_activity_kind(signal) == "new_practice"

    def test_future_seen_is_not_today(self) -> None:
        signal = _direction(
            "recognition",
            mastery_score=0.7,
            attempt_count=4,
            is_unseen=False,
            review_urgency="future",
        )
        assert infer_activity_kind(signal) is None

    def test_due_unseen_is_still_review(self) -> None:
        signal = _direction(
            "recognition",
            is_unseen=True,
            review_urgency="due",
            overdue_days=0.0,
        )
        assert infer_activity_kind(signal) == "review"

    def test_future_seen_is_excluded_from_ranking(self) -> None:
        snap = _snapshot(
            "future",
            recognition=_direction(
                "recognition",
                mastery_score=0.8,
                attempt_count=3,
                is_unseen=False,
                review_urgency="future",
            ),
            production=_direction(
                "production",
                mastery_score=0.8,
                attempt_count=3,
                is_unseen=False,
                review_urgency="future",
            ),
        )
        ranked = rank_recommendations([snap])
        assert ranked == ()


# ---------------------------------------------------------------------------
# 13. 異常系 / LLM 非依存
# ---------------------------------------------------------------------------


class TestBoundaries:
    def test_missing_direction_raises(self) -> None:
        snap = RecommendationSignalSnapshot(
            learning_item_id="only-rec",
            computed_at=_NOW,
            by_direction={"recognition": _direction("recognition")},
            learner_level="B1",
            source_ref_count=0,
            interest_weight=1.0,
            importance_weight=1.0,
        )
        with pytest.raises(MissingDirectionSignalError):
            score_recommendation(snap, "production", "new_practice")

    def test_module_does_not_import_llm(self) -> None:
        import app.domain.recommendation_ranking as ranking

        forbidden = {"openai", "anthropic", "langchain", "litellm"}
        tree = ast.parse(inspect.getsource(ranking))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".", 1)[0])
        assert not (names & forbidden)


# ---------------------------------------------------------------------------
# 14. extract_recommendation_signal との接続
# ---------------------------------------------------------------------------


class TestSignalPipeline:
    def test_extracted_snapshot_can_be_ranked(self) -> None:
        item = LearningItem(
            item_type="vocabulary",
            canonical_form="parler",
            meaning_ja="話す",
        )
        schedules = {
            "recognition": ReviewSchedule(
                learning_item_id=item.id,
                skill_direction="recognition",
                due_at=_NOW - td(days=2),
                interval_days=1.0,
            ),
        }
        snap = extract_recommendation_signal(
            item, schedules_by_direction=schedules, now=_NOW
        )
        ranked = rank_recommendations([snap])
        assert any(
            c.activity_kind == "review" and c.skill_direction == "recognition"
            for c in ranked
        )
        assert all(c.score.policy_version == POLICY_VERSION for c in ranked)
