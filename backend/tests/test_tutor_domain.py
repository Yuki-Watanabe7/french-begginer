"""
Tutor中核ドメインモデル（Phase 0）の型・不変条件を検証するテスト。

検証方針:
  - 必須項目の欠落・不正enum値がValidationErrorとして検出されること
  - 範囲制約（mastery_score / confidence 等）が効いていること
  - 日時はtimezone-awareのみ受け付け、内部ではUTCへ正規化されること
  - LearningEventが履歴として書き換え不可であること
"""

from datetime import UTC, datetime, timedelta, timezone
from typing import get_args

import pytest
from pydantic import ValidationError

from app.domain.tutor import (
    SKILL_DIRECTION_BY_EXERCISE_TYPE,
    EvidenceSpan,
    ExerciseType,
    LearnerState,
    LearningEvent,
    LearningItem,
    LearningItemCandidate,
    MasteryStats,
    ReviewSchedule,
    SourceDocument,
    SourceRef,
    apply_candidate_status,
    apply_review_event,
    compute_mastery_score,
    new_id,
    read_source_evidence,
    skill_direction_for_event,
    utcnow,
)

# ---------------------------------------------------------------------------
# ユーティリティ
# ---------------------------------------------------------------------------


def test_utcnow_is_timezone_aware_utc():
    now = utcnow()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


def test_new_id_is_unique():
    assert new_id() != new_id()


# ---------------------------------------------------------------------------
# SourceDocument
# ---------------------------------------------------------------------------


def test_source_document_minimal_fields_and_defaults():
    doc = SourceDocument(title="Le Monde 記事", content="Il s'agit d'un article.")
    assert doc.source_type == "manual_text"
    assert doc.language == "fr"
    assert doc.metadata == {}
    assert doc.id
    assert doc.created_at.tzinfo is not None


def test_source_document_requires_title_and_content():
    with pytest.raises(ValidationError):
        SourceDocument(content="texte")
    with pytest.raises(ValidationError):
        SourceDocument(title="titre")


def test_source_document_rejects_empty_title():
    with pytest.raises(ValidationError):
        SourceDocument(title="", content="texte")


def test_source_document_rejects_unknown_source_type():
    with pytest.raises(ValidationError):
        SourceDocument(title="t", content="c", source_type="youtube")


def test_source_document_rejects_naive_created_at():
    with pytest.raises(ValidationError):
        SourceDocument(title="t", content="c", created_at=datetime(2026, 1, 1, 12, 0))


def test_source_document_normalizes_created_at_to_utc():
    jst = timezone(timedelta(hours=9))
    doc = SourceDocument(
        title="t", content="c", created_at=datetime(2026, 1, 1, 9, 0, tzinfo=jst)
    )
    assert doc.created_at == datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    assert doc.created_at.utcoffset() == timedelta(0)


# ---------------------------------------------------------------------------
# LearningItem / SourceRef / EvidenceSpan
# ---------------------------------------------------------------------------


def test_learning_item_minimal_fields_and_defaults():
    item = LearningItem(
        item_type="expression",
        canonical_form="il s'agit de",
        meaning_ja="〜が問題である",
    )
    assert item.status == "active"
    assert item.source_refs == []
    assert item.explanation_ja is None
    assert item.level is None


def test_learning_item_requires_core_fields():
    with pytest.raises(ValidationError):
        LearningItem(canonical_form="livre", meaning_ja="本")
    with pytest.raises(ValidationError):
        LearningItem(item_type="vocabulary", meaning_ja="本")
    with pytest.raises(ValidationError):
        LearningItem(item_type="vocabulary", canonical_form="livre")


def test_learning_item_rejects_unknown_item_type():
    with pytest.raises(ValidationError):
        LearningItem(item_type="idiom", canonical_form="livre", meaning_ja="本")


def test_learning_item_rejects_unknown_status():
    with pytest.raises(ValidationError):
        LearningItem(
            item_type="vocabulary",
            canonical_form="livre",
            meaning_ja="本",
            status="archived",
        )


def test_learning_item_rejects_unknown_level():
    with pytest.raises(ValidationError):
        LearningItem(
            item_type="vocabulary", canonical_form="livre", meaning_ja="本", level="N1"
        )


def test_learning_item_holds_source_refs():
    """同じ学習項目が複数Sourceから再発見されうるため source_refs は複数持てる。"""
    doc_a = SourceDocument(title="A", content="il s'agit de ...")
    doc_b = SourceDocument(title="B", content="... il s'agit de")
    item = LearningItem(
        item_type="expression",
        canonical_form="il s'agit de",
        meaning_ja="〜が問題である",
        source_refs=[
            SourceRef(source_document_id=doc_a.id),
            SourceRef(source_document_id=doc_b.id),
        ],
    )
    assert [ref.source_document_id for ref in item.source_refs] == [doc_a.id, doc_b.id]


def test_source_ref_extension_points_default_to_none():
    """evidence_span / confidence はPhase 2用の拡張点で、Phase 0では未設定。"""
    ref = SourceRef(source_document_id="doc-1")
    assert ref.evidence_span is None
    assert ref.confidence is None


def test_source_ref_can_carry_evidence_span_and_confidence():
    ref = SourceRef(
        source_document_id="doc-1",
        evidence_span=EvidenceSpan(start=3, end=15, text="il s'agit de"),
        confidence=0.82,
    )
    assert ref.evidence_span is not None
    assert ref.evidence_span.text == "il s'agit de"
    assert ref.confidence == 0.82


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_source_ref_rejects_confidence_out_of_range(confidence: float):
    with pytest.raises(ValidationError):
        SourceRef(source_document_id="doc-1", confidence=confidence)


def test_evidence_span_rejects_non_positive_length():
    with pytest.raises(ValidationError):
        EvidenceSpan(start=5, end=5)
    with pytest.raises(ValidationError):
        EvidenceSpan(start=5, end=3)


def test_evidence_span_rejects_negative_start():
    with pytest.raises(ValidationError):
        EvidenceSpan(start=-1, end=3)


# ---------------------------------------------------------------------------
# LearningItemCandidate
# ---------------------------------------------------------------------------


def _candidate(**overrides) -> LearningItemCandidate:
    values = {
        "source_document_id": "src-1",
        "item_type": "expression",
        "canonical_form": "il s'agit de",
        "meaning_ja": "〜が問題である",
        "evidence_span": EvidenceSpan(start=0, end=12),
        "extraction_version": "extract-v1",
    }
    values.update(overrides)
    return LearningItemCandidate(**values)


def test_learning_item_candidate_minimal_fields_and_defaults():
    candidate = _candidate()
    assert candidate.status == "candidate"
    assert candidate.explanation_ja is None
    assert candidate.level is None
    assert candidate.confidence is None
    assert candidate.evidence_span.text is None
    assert candidate.metadata == {}
    assert candidate.id
    assert candidate.created_at.tzinfo is not None


def test_candidate_is_not_a_learning_item():
    """Candidate と LearningItem は別モデルであり、責務を混ぜない。"""
    candidate = _candidate()
    item = LearningItem(
        item_type="expression",
        canonical_form="il s'agit de",
        meaning_ja="〜が問題である",
    )
    assert not isinstance(candidate, LearningItem)
    assert not isinstance(item, LearningItemCandidate)
    assert "source_document_id" not in LearningItem.model_fields
    assert "extraction_version" not in LearningItem.model_fields
    assert "source_refs" not in LearningItemCandidate.model_fields
    assert candidate.status not in ("active", "suspended", "mastered")


def test_candidate_requires_core_fields():
    with pytest.raises(ValidationError):
        LearningItemCandidate(
            canonical_form="livre",
            meaning_ja="本",
            evidence_span=EvidenceSpan(start=0, end=5),
            extraction_version="v1",
        )
    with pytest.raises(ValidationError):
        _candidate(canonical_form="")
    with pytest.raises(ValidationError):
        _candidate(meaning_ja="")
    with pytest.raises(ValidationError):
        _candidate(extraction_version="")
    with pytest.raises(ValidationError):
        _candidate(source_document_id="")


def test_candidate_rejects_unknown_item_type():
    with pytest.raises(ValidationError):
        _candidate(item_type="idiom")


def test_candidate_rejects_unknown_status():
    with pytest.raises(ValidationError):
        _candidate(status="pending")
    with pytest.raises(ValidationError):
        _candidate(status="active")


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_candidate_rejects_confidence_out_of_range(confidence: float):
    with pytest.raises(ValidationError):
        _candidate(confidence=confidence)


@pytest.mark.parametrize("confidence", [0.0, 0.5, 1.0])
def test_candidate_accepts_confidence_within_range(confidence: float):
    assert _candidate(confidence=confidence).confidence == confidence


def test_candidate_rejects_naive_created_at():
    with pytest.raises(ValidationError):
        _candidate(created_at=datetime(2026, 1, 1, 12, 0))


def test_candidate_normalizes_created_at_to_utc():
    jst = timezone(timedelta(hours=9))
    candidate = _candidate(created_at=datetime(2026, 1, 1, 9, 0, tzinfo=jst))
    assert candidate.created_at == datetime(2026, 1, 1, 0, 0, tzinfo=UTC)


def test_read_source_evidence_reconstructs_text_without_storing_fragment():
    content = "Oui, il s'agit de cela."
    start = content.index("il s'agit de")
    end = start + len("il s'agit de")
    span = EvidenceSpan(start=start, end=end)
    assert span.text is None
    assert read_source_evidence(content, span) == "il s'agit de"


def test_read_source_evidence_rejects_span_outside_source():
    with pytest.raises(ValueError, match="範囲外"):
        read_source_evidence("abc", EvidenceSpan(start=0, end=10))


def test_apply_candidate_status_accepts_and_rejects_from_candidate():
    original = _candidate()
    accepted = apply_candidate_status(original, "accepted")
    rejected = apply_candidate_status(original, "rejected")
    assert original.status == "candidate"
    assert accepted.status == "accepted"
    assert rejected.status == "rejected"
    assert accepted.id == original.id


def test_apply_candidate_status_same_status_is_idempotent():
    candidate = _candidate()
    assert apply_candidate_status(candidate, "candidate") is candidate
    accepted = apply_candidate_status(candidate, "accepted")
    assert apply_candidate_status(accepted, "accepted") is accepted


@pytest.mark.parametrize(
    ("current", "nxt"),
    [
        ("accepted", "rejected"),
        ("accepted", "candidate"),
        ("rejected", "accepted"),
        ("rejected", "candidate"),
    ],
)
def test_apply_candidate_status_forbids_terminal_transitions(current: str, nxt: str):
    candidate = _candidate(status=current)
    with pytest.raises(ValueError, match="変更できない"):
        apply_candidate_status(candidate, nxt)


# ---------------------------------------------------------------------------
# LearningEvent
# ---------------------------------------------------------------------------


def test_learning_event_minimal_fields_and_defaults():
    event = LearningEvent(
        learning_item_id="item-1", exercise_type="fr_to_ja", result="correct"
    )
    assert event.event_type == "review"
    assert event.response_time_ms is None
    assert event.occurred_at.tzinfo is not None


def test_learning_event_requires_core_fields():
    with pytest.raises(ValidationError):
        LearningEvent(exercise_type="fr_to_ja", result="correct")
    with pytest.raises(ValidationError):
        LearningEvent(learning_item_id="item-1", result="correct")
    with pytest.raises(ValidationError):
        LearningEvent(learning_item_id="item-1", exercise_type="fr_to_ja")


def test_learning_event_rejects_unknown_result():
    with pytest.raises(ValidationError):
        LearningEvent(
            learning_item_id="item-1", exercise_type="fr_to_ja", result="partial"
        )


def test_learning_event_rejects_unknown_exercise_type():
    with pytest.raises(ValidationError):
        LearningEvent(
            learning_item_id="item-1", exercise_type="dictation", result="correct"
        )


def test_learning_event_rejects_negative_response_time():
    with pytest.raises(ValidationError):
        LearningEvent(
            learning_item_id="item-1",
            exercise_type="fr_to_ja",
            result="correct",
            response_time_ms=-1,
        )


def test_learning_event_rejects_naive_occurred_at():
    with pytest.raises(ValidationError):
        LearningEvent(
            learning_item_id="item-1",
            exercise_type="fr_to_ja",
            result="correct",
            occurred_at=datetime(2026, 1, 1, 12, 0),
        )


def test_learning_event_is_immutable():
    """履歴は事実であり書き換えない（append-only）。"""
    event = LearningEvent(
        learning_item_id="item-1", exercise_type="fr_to_ja", result="correct"
    )
    with pytest.raises(ValidationError):
        event.result = "incorrect"


def test_learning_event_accepts_existing_quiz_exercise_types():
    """既存の動詞・名詞クイズもLearningEventとして記録できる。"""
    for exercise_type in ("verb_conjugation", "noun_gender", "noun_article"):
        event = LearningEvent(
            learning_item_id="item-1", exercise_type=exercise_type, result="correct"
        )
        assert event.exercise_type == exercise_type


# ---------------------------------------------------------------------------
# LearnerState / MasteryStats
# ---------------------------------------------------------------------------


def test_learner_state_defaults_to_unstudied():
    state = LearnerState(learning_item_id="item-1")
    assert state.attempt_count == 0
    assert state.correct_count == 0
    assert state.incorrect_count == 0
    assert state.consecutive_correct == 0
    assert state.last_reviewed_at is None
    assert state.mastery_score == 0.0
    assert state.by_direction == {}


def test_learner_state_requires_learning_item_id():
    with pytest.raises(ValidationError):
        LearnerState()


@pytest.mark.parametrize("score", [-0.01, 1.01])
def test_learner_state_rejects_mastery_score_out_of_range(score: float):
    with pytest.raises(ValidationError):
        LearnerState(learning_item_id="item-1", mastery_score=score)


@pytest.mark.parametrize("score", [0.0, 0.5, 1.0])
def test_learner_state_accepts_mastery_score_within_range(score: float):
    state = LearnerState(learning_item_id="item-1", mastery_score=score)
    assert state.mastery_score == score


def test_learner_state_rejects_negative_counts():
    with pytest.raises(ValidationError):
        LearnerState(learning_item_id="item-1", attempt_count=-1)


def test_learner_state_rejects_inconsistent_attempt_count():
    with pytest.raises(ValidationError):
        LearnerState(
            learning_item_id="item-1",
            attempt_count=5,
            correct_count=3,
            incorrect_count=1,
            last_reviewed_at=utcnow(),
        )


def test_learner_state_rejects_consecutive_correct_over_correct_count():
    with pytest.raises(ValidationError):
        LearnerState(
            learning_item_id="item-1",
            attempt_count=3,
            correct_count=2,
            incorrect_count=1,
            consecutive_correct=3,
            last_reviewed_at=utcnow(),
        )


def test_learner_state_rejects_last_reviewed_at_without_attempts():
    with pytest.raises(ValidationError):
        LearnerState(learning_item_id="item-1", last_reviewed_at=utcnow())


def test_learner_state_requires_last_reviewed_at_after_attempts():
    with pytest.raises(ValidationError):
        LearnerState(
            learning_item_id="item-1",
            attempt_count=1,
            correct_count=1,
            incorrect_count=0,
        )


def test_learner_state_accepts_consistent_studied_state():
    reviewed_at = utcnow()
    state = LearnerState(
        learning_item_id="item-1",
        attempt_count=4,
        correct_count=3,
        incorrect_count=1,
        consecutive_correct=2,
        last_reviewed_at=reviewed_at,
        mastery_score=0.75,
    )
    assert state.attempt_count == 4
    assert state.last_reviewed_at == reviewed_at


def test_learner_state_can_hold_direction_breakdown():
    """recognition / production を別々に保持できる。"""
    reviewed_at = utcnow()
    state = LearnerState(
        learning_item_id="item-1",
        attempt_count=3,
        correct_count=2,
        incorrect_count=1,
        consecutive_correct=1,
        last_reviewed_at=reviewed_at,
        mastery_score=0.6,
        by_direction={
            "recognition": MasteryStats(
                attempt_count=2,
                correct_count=2,
                incorrect_count=0,
                consecutive_correct=2,
                last_reviewed_at=reviewed_at,
                mastery_score=0.9,
            ),
            "production": MasteryStats(
                attempt_count=1,
                correct_count=0,
                incorrect_count=1,
                last_reviewed_at=reviewed_at,
                mastery_score=0.2,
            ),
        },
    )
    assert state.by_direction["recognition"].mastery_score == 0.9
    assert state.by_direction["production"].correct_count == 0


def test_learner_state_rejects_unknown_direction():
    with pytest.raises(ValidationError):
        LearnerState(
            learning_item_id="item-1",
            by_direction={"listening": MasteryStats()},
        )


def test_learner_state_rejects_naive_last_reviewed_at():
    with pytest.raises(ValidationError):
        LearnerState(
            learning_item_id="item-1",
            attempt_count=1,
            correct_count=1,
            last_reviewed_at=datetime(2026, 1, 1, 12, 0),
        )


# ---------------------------------------------------------------------------
# ReviewSchedule
# ---------------------------------------------------------------------------


def test_review_schedule_minimal_fields_and_defaults():
    due_at = utcnow() + timedelta(days=1)
    schedule = ReviewSchedule(
        learning_item_id="item-1",
        skill_direction="recognition",
        due_at=due_at,
        interval_days=1.0,
    )
    assert schedule.review_count == 0
    assert schedule.lapse_count == 0
    assert schedule.scheduler_version == "v1-directional"
    assert schedule.metadata == {}


def test_review_schedule_requires_due_at_and_interval():
    with pytest.raises(ValidationError):
        ReviewSchedule(
            learning_item_id="item-1",
            skill_direction="recognition",
            interval_days=1.0,
        )
    with pytest.raises(ValidationError):
        ReviewSchedule(
            learning_item_id="item-1",
            skill_direction="recognition",
            due_at=utcnow(),
        )


def test_review_schedule_requires_skill_direction():
    with pytest.raises(ValidationError):
        ReviewSchedule(learning_item_id="item-1", due_at=utcnow(), interval_days=1.0)


def test_review_schedule_rejects_unknown_skill_direction():
    with pytest.raises(ValidationError):
        ReviewSchedule(
            learning_item_id="item-1",
            skill_direction="listening",
            due_at=utcnow(),
            interval_days=1.0,
        )


def test_review_schedule_rejects_negative_values():
    due_at = utcnow()
    with pytest.raises(ValidationError):
        ReviewSchedule(
            learning_item_id="item-1",
            skill_direction="recognition",
            due_at=due_at,
            interval_days=-1.0,
        )
    with pytest.raises(ValidationError):
        ReviewSchedule(
            learning_item_id="item-1",
            skill_direction="recognition",
            due_at=due_at,
            interval_days=1.0,
            review_count=-1,
        )
    with pytest.raises(ValidationError):
        ReviewSchedule(
            learning_item_id="item-1",
            skill_direction="production",
            due_at=due_at,
            interval_days=1.0,
            lapse_count=-1,
        )


def test_review_schedule_rejects_naive_due_at():
    with pytest.raises(ValidationError):
        ReviewSchedule(
            learning_item_id="item-1",
            skill_direction="recognition",
            due_at=datetime(2026, 1, 1, 12, 0),
            interval_days=1.0,
        )


def test_review_schedule_normalizes_due_at_to_utc():
    jst = timezone(timedelta(hours=9))
    schedule = ReviewSchedule(
        learning_item_id="item-1",
        skill_direction="recognition",
        due_at=datetime(2026, 1, 2, 9, 0, tzinfo=jst),
        interval_days=1.0,
    )
    assert schedule.due_at == datetime(2026, 1, 2, 0, 0, tzinfo=UTC)


def test_review_schedule_allows_sub_day_interval():
    """再学習ステップ（数分後の再出題）を表せるようintervalはfloat。"""
    schedule = ReviewSchedule(
        learning_item_id="item-1",
        skill_direction="production",
        due_at=utcnow(),
        interval_days=0.0,
    )
    assert schedule.interval_days == 0.0


# ---------------------------------------------------------------------------
# apply_review_event / compute_mastery_score
# ---------------------------------------------------------------------------

REVIEW_SEQUENCE = (
    "correct",
    "correct",
    "incorrect",
    "correct",
    "incorrect",
    "incorrect",
    "correct",
)


def _review_event(item_id: str, result: str, **overrides) -> LearningEvent:
    values = {
        "learning_item_id": item_id,
        "exercise_type": "fr_to_ja",
        "result": result,
    }
    values.update(overrides)
    return LearningEvent(**values)


def _legacy_event(item_id: str, result: str, **overrides) -> LearningEvent:
    """exercise_type から direction を決められない legacy event。"""
    values = {
        "id": "evt-legacy",
        "learning_item_id": item_id,
        "event_type": "review",
        "exercise_type": "legacy_unknown",
        "result": result,
        "occurred_at": datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
        "response_time_ms": None,
        "metadata": {},
    }
    values.update(overrides)
    return LearningEvent.model_construct(**values)


def test_compute_mastery_score_is_accuracy():
    assert compute_mastery_score(correct_count=0, attempt_count=0) == 0.0
    assert compute_mastery_score(correct_count=0, attempt_count=1) == 0.0
    assert compute_mastery_score(correct_count=1, attempt_count=1) == 1.0
    assert compute_mastery_score(correct_count=2, attempt_count=3) == pytest.approx(
        2 / 3
    )


@pytest.mark.parametrize(
    ("correct_count", "attempt_count"),
    [(0, 0), (0, 1), (1, 1), (2, 3), (5, 5)],
)
def test_mastery_score_does_not_worsen_on_correct(
    correct_count: int, attempt_count: int
):
    before = compute_mastery_score(
        correct_count=correct_count, attempt_count=attempt_count
    )
    after = compute_mastery_score(
        correct_count=correct_count + 1, attempt_count=attempt_count + 1
    )
    assert after >= before


@pytest.mark.parametrize(
    ("correct_count", "attempt_count"),
    [(0, 0), (0, 1), (1, 1), (2, 3), (5, 5)],
)
def test_mastery_score_does_not_improve_on_incorrect(
    correct_count: int, attempt_count: int
):
    before = compute_mastery_score(
        correct_count=correct_count, attempt_count=attempt_count
    )
    after = compute_mastery_score(
        correct_count=correct_count, attempt_count=attempt_count + 1
    )
    assert after <= before


def test_apply_review_event_creates_state_from_first_correct():
    occurred_at = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    event = _review_event("item-1", "correct", occurred_at=occurred_at)
    state = apply_review_event(None, event)
    assert state.learning_item_id == "item-1"
    assert state.attempt_count == 1
    assert state.correct_count == 1
    assert state.incorrect_count == 0
    assert state.consecutive_correct == 1
    assert state.last_reviewed_at == occurred_at
    assert state.mastery_score == 1.0
    recognition = state.by_direction["recognition"]
    assert recognition.attempt_count == 1
    assert recognition.correct_count == 1
    assert recognition.mastery_score == 1.0
    assert "production" not in state.by_direction


def test_apply_review_event_creates_state_from_first_incorrect():
    occurred_at = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    event = _review_event("item-1", "incorrect", occurred_at=occurred_at)
    state = apply_review_event(None, event)
    assert state.attempt_count == 1
    assert state.correct_count == 0
    assert state.incorrect_count == 1
    assert state.consecutive_correct == 0
    assert state.last_reviewed_at == occurred_at
    assert state.mastery_score == 0.0


def test_apply_review_event_resets_consecutive_correct_on_incorrect():
    item_id = "item-1"
    state = apply_review_event(None, _review_event(item_id, "correct"))
    state = apply_review_event(state, _review_event(item_id, "correct"))
    assert state.consecutive_correct == 2
    state = apply_review_event(state, _review_event(item_id, "incorrect"))
    assert state.consecutive_correct == 0
    assert state.correct_count == 2
    assert state.incorrect_count == 1


def test_apply_review_event_updates_last_reviewed_at_to_event_time():
    item_id = "item-1"
    first_at = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    second_at = datetime(2026, 1, 1, 11, 0, tzinfo=UTC)
    state = apply_review_event(
        None, _review_event(item_id, "correct", occurred_at=first_at)
    )
    state = apply_review_event(
        state, _review_event(item_id, "incorrect", occurred_at=second_at)
    )
    assert state.last_reviewed_at == second_at


def test_apply_review_event_does_not_mutate_previous_state():
    event = _review_event("item-1", "correct")
    original = LearnerState(learning_item_id="item-1")
    updated = apply_review_event(original, event)
    assert original.attempt_count == 0
    assert updated.attempt_count == 1


def test_apply_review_event_rejects_mismatched_item_id():
    state = LearnerState(learning_item_id="item-a")
    with pytest.raises(ValueError, match="learning_item_id が一致しない"):
        apply_review_event(state, _review_event("item-b", "correct"))


def test_skill_direction_mapping_covers_every_exercise_type():
    assert set(SKILL_DIRECTION_BY_EXERCISE_TYPE) == set(get_args(ExerciseType))


def test_skill_direction_for_event_uses_exercise_type_not_metadata():
    event = _review_event(
        "item-1",
        "correct",
        exercise_type="meaning_recognition",
        metadata={"skill_direction": "production"},
    )
    assert skill_direction_for_event(event) == "recognition"


def test_apply_review_event_updates_recognition_only_on_recognition_correct():
    event = _review_event("item-1", "correct", exercise_type="meaning_recognition")
    state = apply_review_event(None, event)
    assert state.attempt_count == 1
    assert state.correct_count == 1
    assert state.by_direction["recognition"].correct_count == 1
    assert "production" not in state.by_direction


def test_apply_review_event_updates_production_only_on_production_incorrect():
    event = _review_event("item-1", "incorrect", exercise_type="ja_to_fr")
    state = apply_review_event(None, event)
    assert state.attempt_count == 1
    assert state.incorrect_count == 1
    assert state.by_direction["production"].incorrect_count == 1
    assert "recognition" not in state.by_direction


def test_overall_stats_include_both_directions():
    rec = _review_event("item-1", "correct", exercise_type="meaning_recognition")
    prod = _review_event("item-1", "incorrect", exercise_type="ja_to_fr")
    state = apply_review_event(None, rec)
    state = apply_review_event(state, prod)
    assert state.attempt_count == 2
    assert state.correct_count == 1
    assert state.incorrect_count == 1
    assert state.mastery_score == pytest.approx(0.5)
    assert state.by_direction["recognition"].attempt_count == 1
    assert state.by_direction["production"].attempt_count == 1


def test_recognition_and_production_have_independent_mastery():
    rec = _review_event("item-1", "correct", exercise_type="fr_to_ja")
    prod = _review_event("item-1", "incorrect", exercise_type="cloze")
    state = apply_review_event(None, rec)
    state = apply_review_event(state, prod)
    assert state.by_direction["recognition"].mastery_score == 1.0
    assert state.by_direction["production"].mastery_score == 0.0
    assert state.mastery_score == pytest.approx(0.5)


def test_recognition_correct_does_not_raise_production_mastery():
    prod = _review_event("item-1", "incorrect", exercise_type="ja_to_fr")
    rec = _review_event("item-1", "correct", exercise_type="meaning_recognition")
    state = apply_review_event(None, prod)
    assert state.by_direction["production"].mastery_score == 0.0
    state = apply_review_event(state, rec)
    assert state.by_direction["production"].mastery_score == 0.0
    assert state.by_direction["recognition"].mastery_score == 1.0


def test_production_incorrect_does_not_reset_recognition_streak():
    rec1 = _review_event("item-1", "correct", exercise_type="meaning_recognition")
    rec2 = _review_event("item-1", "correct", exercise_type="noun_gender")
    prod = _review_event("item-1", "incorrect", exercise_type="verb_conjugation")
    state = apply_review_event(None, rec1)
    state = apply_review_event(state, rec2)
    assert state.consecutive_correct == 2
    assert state.by_direction["recognition"].consecutive_correct == 2
    state = apply_review_event(state, prod)
    assert state.consecutive_correct == 0
    assert state.by_direction["recognition"].consecutive_correct == 2
    assert state.by_direction["production"].consecutive_correct == 0


def test_direction_attempt_counts_match_classified_events_only():
    events = [
        _review_event("item-1", "correct", exercise_type="meaning_recognition"),
        _review_event("item-1", "correct", exercise_type="ja_to_fr"),
        _review_event("item-1", "incorrect", exercise_type="cloze"),
        _legacy_event("item-1", "correct"),
    ]
    state: LearnerState | None = None
    for event in events:
        state = apply_review_event(state, event)
    assert state is not None
    assert state.attempt_count == 4
    classified = (
        state.by_direction["recognition"].attempt_count
        + state.by_direction["production"].attempt_count
    )
    assert classified == 3
    assert state.by_direction["recognition"].attempt_count == 1
    assert state.by_direction["production"].attempt_count == 2


def test_apply_review_event_replay_rebuilds_same_by_direction():
    events = [
        _review_event(
            "item-1",
            "correct",
            exercise_type="meaning_recognition",
            occurred_at=datetime(2026, 1, 1, 10, tzinfo=UTC),
        ),
        _review_event(
            "item-1",
            "incorrect",
            exercise_type="ja_to_fr",
            occurred_at=datetime(2026, 1, 1, 11, tzinfo=UTC),
        ),
        _review_event(
            "item-1",
            "correct",
            exercise_type="cloze",
            occurred_at=datetime(2026, 1, 1, 12, tzinfo=UTC),
        ),
        _legacy_event(
            "item-1",
            "incorrect",
            occurred_at=datetime(2026, 1, 1, 13, tzinfo=UTC),
        ),
    ]

    def fold(sequence: list[LearningEvent]) -> LearnerState:
        state: LearnerState | None = None
        for event in sequence:
            state = apply_review_event(state, event)
        assert state is not None
        return state

    first = fold(events)
    second = fold(events)
    assert first == second
    assert first.by_direction["recognition"].correct_count == 1
    assert first.by_direction["production"].attempt_count == 2
    assert first.attempt_count == 4


def test_legacy_event_updates_overall_but_not_by_direction():
    event = _legacy_event(
        "item-1",
        "correct",
        metadata={"skill_direction": "recognition"},
    )
    state = apply_review_event(None, event)
    assert skill_direction_for_event(event) is None
    assert state.attempt_count == 1
    assert state.correct_count == 1
    assert state.mastery_score == 1.0
    assert state.by_direction == {}


def test_apply_review_event_does_not_mutate_previous_by_direction():
    original = apply_review_event(
        None,
        _review_event("item-1", "correct", exercise_type="meaning_recognition"),
    )
    updated = apply_review_event(
        original,
        _review_event("item-1", "correct", exercise_type="ja_to_fr"),
    )
    assert original.attempt_count == 1
    assert "production" not in original.by_direction
    assert original.by_direction["recognition"].attempt_count == 1
    assert updated.by_direction["production"].attempt_count == 1


def test_apply_review_event_sequence_is_deterministic():
    item_id = "item-1"
    events = [
        _review_event(item_id, result, occurred_at=datetime(2026, 1, 1, i, tzinfo=UTC))
        for i, result in enumerate(REVIEW_SEQUENCE, start=10)
    ]

    def fold(sequence: list[LearningEvent]) -> LearnerState:
        state: LearnerState | None = None
        for event in sequence:
            state = apply_review_event(state, event)
        assert state is not None
        return state

    first = fold(events)
    second = fold(events)
    assert first == second
    assert first.attempt_count == 7
    assert first.correct_count == 4
    assert first.incorrect_count == 3
    assert first.consecutive_correct == 1
    assert first.mastery_score == pytest.approx(4 / 7)
    assert first.last_reviewed_at == events[-1].occurred_at
    recognition = first.by_direction["recognition"]
    assert recognition.attempt_count == first.attempt_count
    assert recognition.correct_count == first.correct_count
    assert recognition.mastery_score == first.mastery_score
    assert "production" not in first.by_direction
