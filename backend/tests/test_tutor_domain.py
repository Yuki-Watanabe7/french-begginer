"""
Tutor中核ドメインモデル（Phase 0）の型・不変条件を検証するテスト。

検証方針:
  - 必須項目の欠落・不正enum値がValidationErrorとして検出されること
  - 範囲制約（mastery_score / confidence 等）が効いていること
  - 日時はtimezone-awareのみ受け付け、内部ではUTCへ正規化されること
  - LearningEventが履歴として書き換え不可であること
"""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.domain.tutor import (
    EvidenceSpan,
    LearnerState,
    LearningEvent,
    LearningItem,
    MasteryStats,
    ReviewSchedule,
    SourceDocument,
    SourceRef,
    new_id,
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
    """recognition / production を将来分離できる構造であることを確認する。"""
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
        learning_item_id="item-1", due_at=due_at, interval_days=1.0
    )
    assert schedule.review_count == 0
    assert schedule.lapse_count == 0
    assert schedule.scheduler_version == "v0"
    assert schedule.metadata == {}


def test_review_schedule_requires_due_at_and_interval():
    with pytest.raises(ValidationError):
        ReviewSchedule(learning_item_id="item-1", interval_days=1.0)
    with pytest.raises(ValidationError):
        ReviewSchedule(learning_item_id="item-1", due_at=utcnow())


def test_review_schedule_rejects_negative_values():
    due_at = utcnow()
    with pytest.raises(ValidationError):
        ReviewSchedule(learning_item_id="item-1", due_at=due_at, interval_days=-1.0)
    with pytest.raises(ValidationError):
        ReviewSchedule(
            learning_item_id="item-1",
            due_at=due_at,
            interval_days=1.0,
            review_count=-1,
        )
    with pytest.raises(ValidationError):
        ReviewSchedule(
            learning_item_id="item-1",
            due_at=due_at,
            interval_days=1.0,
            lapse_count=-1,
        )


def test_review_schedule_rejects_naive_due_at():
    with pytest.raises(ValidationError):
        ReviewSchedule(
            learning_item_id="item-1",
            due_at=datetime(2026, 1, 1, 12, 0),
            interval_days=1.0,
        )


def test_review_schedule_normalizes_due_at_to_utc():
    jst = timezone(timedelta(hours=9))
    schedule = ReviewSchedule(
        learning_item_id="item-1",
        due_at=datetime(2026, 1, 2, 9, 0, tzinfo=jst),
        interval_days=1.0,
    )
    assert schedule.due_at == datetime(2026, 1, 2, 0, 0, tzinfo=UTC)


def test_review_schedule_allows_sub_day_interval():
    """再学習ステップ（数分後の再出題）を表せるようintervalはfloat。"""
    schedule = ReviewSchedule(
        learning_item_id="item-1", due_at=utcnow(), interval_days=0.0
    )
    assert schedule.interval_days == 0.0
