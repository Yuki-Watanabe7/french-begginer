"""due queue から Review Practice Session を組み立てる（Issue #164）の domain テスト。

検証方針:
  - due entry だけ Session へ入る。future / 未スケジュールは入らない
  - recognition due は recognition Exercise、production due は production
  - 両方向 due を別々に扱える
  - question_count 上限。overdue 順を尊重
  - unsupported entry は理由付き skip。Session 全体は失敗しない
  - production は cloze を優先し、無ければ ja_to_fr 等へ落とす
  - seed 固定で deterministic。0件でも empty Session
  - mastery / personalization では並べ替えない
  - FastAPI 等に依存しない
"""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime, timedelta

import pytest

from app.domain.exercise import skill_direction_for
from app.domain.review_queue import build_review_queue
from app.domain.review_session import (
    MAX_QUESTION_COUNT,
    REVIEW_EXERCISE_PRIORITY,
    InvalidReviewSessionRequestError,
    build_review_practice_session,
)
from app.domain.tutor import (
    EvidenceSpan,
    LearningItem,
    ReviewSchedule,
    SourceDocument,
    SourceRef,
)

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
CREATED = NOW - timedelta(days=10)


def _item(item_id: str, **overrides) -> LearningItem:
    values = {
        "id": item_id,
        "item_type": "vocabulary",
        "canonical_form": "livre",
        "meaning_ja": "本",
        "status": "active",
        "created_at": CREATED,
    }
    values.update(overrides)
    return LearningItem(**values)


def _schedule(item_id: str, due_at: datetime, **overrides) -> ReviewSchedule:
    values = {
        "learning_item_id": item_id,
        "skill_direction": "recognition",
        "due_at": due_at,
        "interval_days": 1.0,
        "review_count": 1,
    }
    values.update(overrides)
    return ReviewSchedule(**values)


def _vocab_pool() -> list[LearningItem]:
    specs = (
        ("v-livre", "livre", "本"),
        ("v-maison", "maison", "家"),
        ("v-chat", "chat", "猫"),
        ("v-chien", "chien", "犬"),
    )
    return [
        _item(
            item_id=item_id,
            canonical_form=form,
            meaning_ja=meaning,
            created_at=CREATED + timedelta(seconds=index),
        )
        for index, (item_id, form, meaning) in enumerate(specs)
    ]


def _entries(schedules, items, *, now=NOW):
    return build_review_queue(
        schedules,
        items_by_id={item.id: item for item in items},
        now=now,
    ).entries


def _exercise_keys(session) -> list[tuple[str, str]]:
    return [
        (row.spec.learning_item_id, row.spec.exercise_type) for row in session.exercises
    ]


def test_due_entries_only_enter_the_session():
    pool = _vocab_pool()
    due = pool[0]
    future = pool[1]
    unscheduled = pool[2]
    entries = _entries(
        [
            _schedule(due.id, NOW - timedelta(days=1), skill_direction="production"),
            _schedule(future.id, NOW + timedelta(days=1), skill_direction="production"),
        ],
        pool,
    )
    session = build_review_practice_session(
        entries,
        pool=pool,
        question_count=10,
        seed="fixed",
        session_id="s1",
    )
    item_ids = {item_id for item_id, _type in _exercise_keys(session)}
    assert item_ids == {due.id}
    assert unscheduled.id not in item_ids
    assert future.id not in item_ids
    assert all(row.spec.skill_direction == "production" for row in session.exercises)


def test_future_entry_is_excluded():
    pool = _vocab_pool()
    item = pool[0]
    entries = _entries(
        [_schedule(item.id, NOW + timedelta(seconds=1), skill_direction="production")],
        pool,
    )
    session = build_review_practice_session(
        entries, pool=pool, question_count=5, seed="fixed", session_id="s1"
    )
    assert session.exercises == ()
    assert session.generated_count == 0


def test_recognition_due_selects_recognition_exercise():
    pool = _vocab_pool()
    item = pool[0]
    entries = _entries(
        [_schedule(item.id, NOW, skill_direction="recognition")],
        pool,
    )
    session = build_review_practice_session(
        entries, pool=pool, question_count=5, seed="fixed", session_id="s1"
    )
    assert session.generated_count == 1
    exercise = session.exercises[0]
    assert exercise.spec.learning_item_id == item.id
    assert exercise.spec.skill_direction == "recognition"
    assert skill_direction_for(exercise.spec.exercise_type) == "recognition"
    assert exercise.spec.exercise_type == "meaning_recognition"


def test_production_due_selects_production_exercise():
    pool = _vocab_pool()
    item = pool[0]
    entries = _entries(
        [_schedule(item.id, NOW, skill_direction="production")],
        pool,
    )
    session = build_review_practice_session(
        entries, pool=pool, question_count=5, seed="fixed", session_id="s1"
    )
    assert session.generated_count == 1
    exercise = session.exercises[0]
    assert exercise.spec.skill_direction == "production"
    assert skill_direction_for(exercise.spec.exercise_type) == "production"
    assert exercise.spec.exercise_type == "ja_to_fr"


def test_both_directions_are_separate_session_entries():
    pool = _vocab_pool()
    item = pool[0]
    entries = _entries(
        [
            _schedule(item.id, NOW - timedelta(hours=2), skill_direction="recognition"),
            _schedule(item.id, NOW - timedelta(hours=1), skill_direction="production"),
        ],
        pool,
    )
    session = build_review_practice_session(
        entries, pool=pool, question_count=10, seed="fixed", session_id="s1"
    )
    directions = [row.spec.skill_direction for row in session.exercises]
    types = [row.spec.exercise_type for row in session.exercises]
    assert directions == ["recognition", "production"]
    assert types == ["meaning_recognition", "ja_to_fr"]
    assert {row.spec.learning_item_id for row in session.exercises} == {item.id}


def test_question_count_caps_without_padding():
    pool = _vocab_pool()
    schedules = [
        _schedule(item.id, NOW - timedelta(minutes=index), skill_direction="production")
        for index, item in enumerate(pool)
    ]
    entries = _entries(schedules, pool)
    session = build_review_practice_session(
        entries, pool=pool, question_count=2, seed="fixed", session_id="s1"
    )
    assert session.requested_count == 2
    assert session.generated_count == 2
    assert len(session.exercises) == 2
    keys = _exercise_keys(session)
    assert len(keys) == len(set(keys))


def test_overdue_order_is_respected():
    pool = _vocab_pool()
    older = pool[3]
    newer = pool[0]
    entries = _entries(
        [
            _schedule(newer.id, NOW - timedelta(hours=1), skill_direction="production"),
            _schedule(older.id, NOW - timedelta(days=2), skill_direction="production"),
        ],
        pool,
    )
    session = build_review_practice_session(
        entries, pool=pool, question_count=5, seed="fixed", session_id="s1"
    )
    assert [row.spec.learning_item_id for row in session.exercises] == [
        older.id,
        newer.id,
    ]


def test_unsupported_entry_is_skipped_without_failing_session():
    pool = _vocab_pool()
    grammar = _item(
        "g-il-faut",
        item_type="grammar",
        canonical_form="il faut",
        meaning_ja="〜しなければならない",
    )
    items = [*pool, grammar]
    entries = _entries(
        [
            _schedule(
                grammar.id, NOW - timedelta(days=2), skill_direction="production"
            ),
            _schedule(
                pool[0].id, NOW - timedelta(days=1), skill_direction="production"
            ),
        ],
        items,
    )
    session = build_review_practice_session(
        entries, pool=items, question_count=5, seed="fixed", session_id="s1"
    )
    skipped = {row.learning_item_id: row for row in session.skipped_entries}
    assert skipped[grammar.id].skip_reason == "missing_source_evidence"
    assert skipped[grammar.id].skill_direction == "production"
    assert all(row.spec.learning_item_id != grammar.id for row in session.exercises)
    assert session.generated_count >= 1


def test_production_prefers_cloze_when_source_evidence_exists():
    content = "Le livre est sur la table."
    fragment = "livre"
    start = content.index(fragment)
    source = SourceDocument(id="src-a", title="A", content=content)
    item = _item(
        "v-livre",
        source_refs=[
            SourceRef(
                source_document_id=source.id,
                evidence_span=EvidenceSpan(start=start, end=start + len(fragment)),
            )
        ],
    )
    pool = [item, *_vocab_pool()[1:]]
    entries = _entries(
        [_schedule(item.id, NOW, skill_direction="production")],
        pool,
    )
    session = build_review_practice_session(
        entries,
        pool=pool,
        sources=[source],
        question_count=5,
        seed="fixed",
        session_id="s1",
    )
    assert session.generated_count == 1
    assert session.exercises[0].spec.exercise_type == "cloze"
    assert session.exercises[0].spec.skill_direction == "production"


def test_same_seed_is_deterministic():
    pool = _vocab_pool()
    schedules = [
        _schedule(item.id, NOW - timedelta(minutes=index), skill_direction="production")
        for index, item in enumerate(pool)
    ]
    entries = _entries(schedules, pool)
    first = build_review_practice_session(
        entries, pool=pool, question_count=5, seed="alpha", session_id="s1"
    )
    second = build_review_practice_session(
        entries, pool=pool, question_count=5, seed="alpha", session_id="s2"
    )
    assert _exercise_keys(first) == _exercise_keys(second)


def test_empty_queue_returns_empty_session():
    session = build_review_practice_session(
        (), pool=_vocab_pool(), question_count=5, seed="fixed", session_id="s1"
    )
    assert session.exercises == ()
    assert session.skipped_entries == ()
    assert session.generated_count == 0
    assert session.requested_count == 5


def test_question_count_out_of_range_raises():
    with pytest.raises(InvalidReviewSessionRequestError):
        build_review_practice_session((), question_count=0, session_id="s1")
    with pytest.raises(InvalidReviewSessionRequestError):
        build_review_practice_session(
            (), question_count=MAX_QUESTION_COUNT + 1, session_id="s1"
        )


def test_public_exercises_omit_answers():
    pool = _vocab_pool()
    entries = _entries(
        [_schedule(pool[0].id, NOW, skill_direction="production")],
        pool,
    )
    session = build_review_practice_session(
        entries, pool=pool, question_count=5, seed="fixed", session_id="s1"
    )
    leaked = {
        "expected",
        "expected_answer",
        "answer_key",
        "correct",
        "correct_answer",
        "metadata",
    }
    for public in session.to_public_exercises():
        dumped = public.model_dump()
        assert leaked.isdisjoint(dumped)


def test_review_exercise_priority_keeps_direction_contract():
    for direction, types in REVIEW_EXERCISE_PRIORITY.items():
        assert types
        for exercise_type in types:
            assert skill_direction_for(exercise_type) == direction


def test_mastery_does_not_reorder_overdue_entries():
    import app.domain.review_session as module

    signature = inspect.signature(build_review_practice_session)
    assert "mastery_score" not in signature.parameters
    assert "learner_state" not in signature.parameters
    source = inspect.getsource(build_review_practice_session)
    assert "mastery_score" not in source
    module_source = inspect.getsource(module)
    assert "FSRS" not in module_source
    assert "SM-2" not in module_source
    assert "SM2" not in module_source


def test_domain_module_does_not_depend_on_fastapi_sqlalchemy_or_openai():
    import app.domain.review_session as module

    tree = ast.parse(inspect.getsource(module))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".", 1)[0])
    assert names.isdisjoint({"fastapi", "sqlalchemy", "openai"}), names
    assert "datetime.now" not in inspect.getsource(module)
