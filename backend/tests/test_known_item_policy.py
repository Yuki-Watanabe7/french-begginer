"""known-item policy（Issue #201）の domain テスト。"""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime, timedelta

import pytest

import app.domain.known_item_policy as known_item_policy
from app.domain.known_item_policy import (
    EXPLICIT_KNOWN_REMOVES_DUE_REVIEWS,
    MIN_CONFIRMATION_SPAN_DAYS,
    MIN_CORRECT_COUNT,
    decide_auto_skip,
    next_explicit_known,
    should_drop_today_candidate,
)
from app.domain.tutor import AnswerOutcome, ExerciseType, LearningEvent

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
ITEM_ID = "item-1"


def test_one_correct_answer_does_not_auto_skip() -> None:
    decision = decide_auto_skip(
        skill_direction="recognition",
        events=(_event("meaning_recognition", "correct", days=1),),
        now=NOW,
    )
    assert decision.skip_new is False
    assert decision.reason_code == "INSUFFICIENT_HISTORY"
    assert MIN_CORRECT_COUNT > 1


def test_same_session_burst_does_not_auto_skip() -> None:
    events = tuple(
        _event("meaning_recognition", "correct", hours=3 - offset)
        for offset in range(MIN_CORRECT_COUNT)
    )
    decision = decide_auto_skip(
        skill_direction="recognition",
        events=events,
        now=NOW,
    )
    assert decision.skip_new is False
    assert decision.reason_code == "INSUFFICIENT_HISTORY"


def test_sufficient_history_auto_skips_only_that_direction() -> None:
    recognition = _sufficient("meaning_recognition")
    production = (_event("ja_to_fr", "correct", days=1),)
    recognition_decision = decide_auto_skip(
        skill_direction="recognition",
        events=recognition,
        now=NOW,
    )
    production_decision = decide_auto_skip(
        skill_direction="production",
        events=production,
        now=NOW,
    )
    assert recognition_decision.skip_new is True
    assert recognition_decision.reason_code == "AUTO_SKIP"
    assert production_decision.skip_new is False
    assert production_decision.reason_code == "INSUFFICIENT_HISTORY"


def test_recent_incorrect_blocks_auto_skip() -> None:
    events = (
        _event("meaning_recognition", "correct", days=10),
        _event("meaning_recognition", "correct", days=6),
        _event("meaning_recognition", "correct", days=3),
        _event("meaning_recognition", "correct", days=2),
        _event("meaning_recognition", "incorrect", hours=12),
    )
    decision = decide_auto_skip(
        skill_direction="recognition",
        events=events,
        now=NOW,
    )
    assert decision.skip_new is False
    assert decision.reason_code == "RECENT_INCORRECT"


def test_same_history_and_now_returns_the_same_decision() -> None:
    events = _sufficient("ja_to_fr")
    first = decide_auto_skip(skill_direction="production", events=events, now=NOW)
    second = decide_auto_skip(skill_direction="production", events=events, now=NOW)
    assert first == second


def test_direction_mismatch_is_rejected() -> None:
    with pytest.raises(ValueError):
        decide_auto_skip(
            skill_direction="production",
            events=(_event("meaning_recognition", "correct", days=1),),
            now=NOW,
        )


def test_naive_now_is_rejected() -> None:
    with pytest.raises(ValueError):
        decide_auto_skip(
            skill_direction="recognition",
            events=(),
            now=datetime(2026, 10, 12, 12, 0),
        )


def test_explicit_known_mark_and_undo_are_idempotent() -> None:
    event, override = next_explicit_known(
        None,
        learning_item_id=ITEM_ID,
        action="mark_known",
        occurred_at=NOW,
        event_id="event-1",
    )
    assert event is not None
    assert override is not None
    assert override.active is True
    assert override.updated_at == NOW

    again_event, again = next_explicit_known(
        override,
        learning_item_id=ITEM_ID,
        action="mark_known",
        occurred_at=NOW + timedelta(days=1),
        event_id="event-2",
    )
    assert again_event is None
    assert again == override

    cleared_event, cleared = next_explicit_known(
        override,
        learning_item_id=ITEM_ID,
        action="clear_known",
        occurred_at=NOW + timedelta(days=1),
        event_id="event-3",
    )
    assert cleared_event is not None
    assert cleared is not None
    assert cleared.active is False
    assert cleared.updated_at == NOW + timedelta(days=1)

    idle_event, idle = next_explicit_known(
        cleared,
        learning_item_id=ITEM_ID,
        action="clear_known",
        occurred_at=NOW + timedelta(days=2),
        event_id="event-4",
    )
    assert idle_event is None
    assert idle == cleared


def test_known_does_not_drop_due_review() -> None:
    assert EXPLICIT_KNOWN_REMOVES_DUE_REVIEWS is False
    assert (
        should_drop_today_candidate(
            activity_kind="review",
            explicit_known=True,
            auto_skip_new=True,
        )
        is False
    )
    assert (
        should_drop_today_candidate(
            activity_kind="new_practice",
            explicit_known=True,
            auto_skip_new=False,
        )
        is True
    )
    assert (
        should_drop_today_candidate(
            activity_kind="new_practice",
            explicit_known=False,
            auto_skip_new=True,
        )
        is True
    )
    assert (
        should_drop_today_candidate(
            activity_kind="new_practice",
            explicit_known=False,
            auto_skip_new=False,
        )
        is False
    )


def test_confirmation_span_is_longer_than_a_single_moment() -> None:
    assert MIN_CONFIRMATION_SPAN_DAYS >= 2


def test_module_does_not_call_wall_clock_or_llm() -> None:
    source = inspect.getsource(known_item_policy)
    assert "datetime.now" not in source
    assert "utcnow" not in source
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".", 1)[0])
    assert not (names & {"openai", "anthropic", "langchain", "litellm"})


def _event(
    exercise_type: ExerciseType,
    result: AnswerOutcome,
    *,
    days: int = 0,
    hours: int = 0,
) -> LearningEvent:
    return LearningEvent(
        learning_item_id=ITEM_ID,
        exercise_type=exercise_type,
        result=result,
        occurred_at=NOW - timedelta(days=days, hours=hours),
    )


def _sufficient(exercise_type: ExerciseType) -> tuple[LearningEvent, ...]:
    span = MIN_CONFIRMATION_SPAN_DAYS + 4
    offsets = (span, span // 2, 0)
    return tuple(_event(exercise_type, "correct", days=days) for days in offsets)
