"""Practice Session 組み立て（Issue #150）の domain テスト。

検証方針:
  - source_id / item_ids / 未指定で対象 Item が変わる
  - active のみ練習対象。inactive は明示指定時だけ skip
  - question_count 上限と同一 item/exercise の非重複
  - recognition / production を可能な範囲で混在
  - unsupported Item は理由付き skip
  - seed 固定で deterministic
  - 0件でも Session 全体は失敗しない
  - due / mastery による優先順位を使わない
"""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime, timedelta

import pytest

from app.domain.practice_session import (
    MAX_QUESTION_COUNT,
    InvalidPracticeSessionRequestError,
    UnknownPracticeItemError,
    build_practice_session,
)
from app.domain.tutor import (
    EvidenceSpan,
    LearningItem,
    LearningItemStatus,
    LearningItemType,
    SourceDocument,
    SourceRef,
)

CREATED = datetime(2026, 1, 1, tzinfo=UTC)


def _item(
    *,
    item_id: str,
    item_type: LearningItemType = "vocabulary",
    canonical_form: str = "livre",
    meaning_ja: str = "本",
    status: LearningItemStatus = "active",
    created_at: datetime | None = None,
    source_id: str | None = None,
    fragment: str | None = None,
    source_content: str | None = None,
) -> LearningItem:
    refs: list[SourceRef] = []
    if source_id is not None:
        span = None
        if fragment is not None and source_content is not None:
            start = source_content.index(fragment)
            span = EvidenceSpan(start=start, end=start + len(fragment))
        refs.append(SourceRef(source_document_id=source_id, evidence_span=span))
    return LearningItem(
        id=item_id,
        item_type=item_type,
        canonical_form=canonical_form,
        meaning_ja=meaning_ja,
        status=status,
        created_at=created_at or CREATED,
        source_refs=refs,
    )


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


def _exercise_keys(session) -> list[tuple[str, str]]:
    return [
        (row.spec.learning_item_id, row.spec.exercise_type) for row in session.exercises
    ]


def test_item_ids_select_only_requested_items():
    pool = _vocab_pool()
    session = build_practice_session(
        pool,
        item_ids=["v-chat", "v-livre"],
        question_count=10,
        seed="fixed",
        session_id="s1",
    )
    item_ids = {item_id for item_id, _type in _exercise_keys(session)}
    assert item_ids == {"v-chat", "v-livre"}
    assert session.requested_count == 10
    assert session.generated_count == len(session.exercises)
    assert session.generated_count > 0


def test_source_id_selects_only_items_from_that_source():
    content_a = "Le livre est sur la table."
    content_b = "Le chat dort."
    source_a = SourceDocument(id="src-a", title="A", content=content_a)
    source_b = SourceDocument(id="src-b", title="B", content=content_b)
    items = [
        _item(
            item_id="v-livre",
            canonical_form="livre",
            meaning_ja="本",
            source_id="src-a",
            fragment="livre",
            source_content=content_a,
        ),
        _item(
            item_id="v-table",
            canonical_form="table",
            meaning_ja="テーブル",
            source_id="src-a",
            fragment="table",
            source_content=content_a,
            created_at=CREATED + timedelta(seconds=1),
        ),
        _item(
            item_id="v-chat",
            canonical_form="chat",
            meaning_ja="猫",
            source_id="src-b",
            fragment="chat",
            source_content=content_b,
            created_at=CREATED + timedelta(seconds=2),
        ),
        _item(
            item_id="v-maison",
            canonical_form="maison",
            meaning_ja="家",
            created_at=CREATED + timedelta(seconds=3),
        ),
    ]
    session = build_practice_session(
        items,
        sources=[source_a, source_b],
        source_id="src-a",
        question_count=20,
        seed="fixed",
        session_id="s1",
    )
    item_ids = {item_id for item_id, _type in _exercise_keys(session)}
    assert item_ids == {"v-livre", "v-table"}


def test_unfiltered_session_uses_active_items_only():
    pool = _vocab_pool()
    pool.append(
        _item(
            item_id="v-suspended",
            canonical_form="eau",
            meaning_ja="水",
            status="suspended",
            created_at=CREATED + timedelta(seconds=10),
        )
    )
    session = build_practice_session(
        pool, question_count=20, seed="fixed", session_id="s1"
    )
    item_ids = {item_id for item_id, _type in _exercise_keys(session)}
    assert "v-suspended" not in item_ids
    assert item_ids <= {item.id for item in pool if item.status == "active"}
    assert all(
        skipped.learning_item_id != "v-suspended" for skipped in session.skipped_items
    )


@pytest.mark.parametrize("status", ["suspended", "mastered"])
def test_explicit_inactive_item_is_skipped_with_reason(status: LearningItemStatus):
    pool = _vocab_pool()
    inactive = _item(
        item_id="v-inactive",
        canonical_form="eau",
        meaning_ja="水",
        status=status,
    )
    session = build_practice_session(
        [*pool, inactive],
        item_ids=["v-inactive", "v-livre"],
        question_count=5,
        seed="fixed",
        session_id="s1",
    )
    assert {item_id for item_id, _type in _exercise_keys(session)} == {"v-livre"}
    skipped = {row.learning_item_id: row for row in session.skipped_items}
    assert skipped["v-inactive"].skip_reason == "inactive_item"


def test_question_count_caps_session_without_padding_duplicates():
    pool = _vocab_pool()
    session = build_practice_session(
        pool, question_count=3, seed="fixed", session_id="s1"
    )
    keys = _exercise_keys(session)
    assert len(keys) == 3
    assert len(keys) == len(set(keys))
    assert session.requested_count == 3
    assert session.generated_count == 3


def test_does_not_duplicate_item_and_exercise_type_when_count_exceeds_slots():
    items = _vocab_pool()[:1]
    session = build_practice_session(
        items, question_count=MAX_QUESTION_COUNT, seed="fixed", session_id="s1"
    )
    keys = _exercise_keys(session)
    assert len(keys) == len(set(keys))
    assert session.generated_count == len(keys)
    assert session.generated_count < session.requested_count
    assert session.generated_count >= 1


def test_mixes_recognition_and_production_when_both_exist():
    pool = _vocab_pool()
    session = build_practice_session(
        pool, question_count=4, seed="fixed", session_id="s1"
    )
    directions = {row.spec.skill_direction for row in session.exercises}
    assert directions == {"recognition", "production"}
    # 交互: 先頭は recognition、次は production（両方ある場合）
    assert session.exercises[0].spec.skill_direction == "recognition"
    assert session.exercises[1].spec.skill_direction == "production"


def test_unsupported_item_is_skipped_without_failing_session():
    pool = _vocab_pool()
    grammar = _item(
        item_id="g-il-faut",
        item_type="grammar",
        canonical_form="il faut",
        meaning_ja="〜しなければならない",
    )
    session = build_practice_session(
        [*pool, grammar],
        item_ids=["g-il-faut", "v-livre"],
        question_count=5,
        seed="fixed",
        session_id="s1",
    )
    assert session.generated_count >= 1
    skipped = {row.learning_item_id: row for row in session.skipped_items}
    assert skipped["g-il-faut"].skip_reason == "missing_source_evidence"
    assert all(item_id != "g-il-faut" for item_id, _type in _exercise_keys(session))


def test_same_seed_is_deterministic():
    pool = _vocab_pool()
    first = build_practice_session(
        pool, question_count=6, seed="alpha", session_id="s1"
    )
    second = build_practice_session(
        pool, question_count=6, seed="alpha", session_id="s2"
    )
    assert _exercise_keys(first) == _exercise_keys(second)
    assert [row.spec.prompt for row in first.exercises] == [
        row.spec.prompt for row in second.exercises
    ]


def test_different_seeds_can_change_order():
    pool = _vocab_pool()
    orders = {
        tuple(_exercise_keys(build_practice_session(pool, question_count=6, seed=seed)))
        for seed in ("alpha", "bravo", "charlie", "delta", "echo")
    }
    assert len(orders) > 1


def test_empty_items_returns_empty_session():
    session = build_practice_session(
        [], question_count=5, seed="fixed", session_id="s1"
    )
    assert session.exercises == ()
    assert session.skipped_items == ()
    assert session.generated_count == 0
    assert session.requested_count == 5
    assert session.session_id == "s1"


def test_empty_item_ids_returns_empty_session():
    pool = _vocab_pool()
    session = build_practice_session(
        pool, item_ids=[], question_count=5, seed="fixed", session_id="s1"
    )
    assert session.exercises == ()
    assert session.generated_count == 0


def test_duplicate_item_ids_are_deduped():
    pool = _vocab_pool()
    session = build_practice_session(
        pool,
        item_ids=["v-livre", "v-livre"],
        question_count=10,
        seed="fixed",
        session_id="s1",
    )
    keys = _exercise_keys(session)
    assert all(item_id == "v-livre" for item_id, _type in keys)
    assert len(keys) == len(set(keys))


def test_unknown_item_id_raises():
    pool = _vocab_pool()
    with pytest.raises(UnknownPracticeItemError) as exc:
        build_practice_session(pool, item_ids=["missing"], session_id="s1")
    assert exc.value.item_id == "missing"


def test_source_id_and_item_ids_together_raise():
    pool = _vocab_pool()
    with pytest.raises(InvalidPracticeSessionRequestError):
        build_practice_session(
            pool, source_id="src-a", item_ids=["v-livre"], session_id="s1"
        )


def test_question_count_out_of_range_raises():
    with pytest.raises(InvalidPracticeSessionRequestError):
        build_practice_session([], question_count=0, session_id="s1")
    with pytest.raises(InvalidPracticeSessionRequestError):
        build_practice_session([], question_count=21, session_id="s1")


def test_public_exercises_omit_answers():
    pool = _vocab_pool()
    session = build_practice_session(
        pool, question_count=5, seed="fixed", session_id="s1"
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


def test_candidates_are_not_part_of_session_inputs():
    """Session は LearningItem だけを見る。Candidate 型を受け取らない。"""
    signature = inspect.signature(build_practice_session)
    assert "candidate" not in signature.parameters
    assert "candidates" not in signature.parameters


def test_selection_policy_does_not_use_due_or_review_schedule():
    import app.domain.practice_session as module

    tree = ast.parse(inspect.getsource(module))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert "app.domain.review_scheduler" not in imported
    assert "ReviewSchedule" not in imported
    signature = inspect.signature(build_practice_session)
    assert "due_at" not in signature.parameters
    assert "schedule" not in signature.parameters
    assert "schedules" not in signature.parameters
    assert "learner_state" not in signature.parameters


def test_domain_module_does_not_depend_on_fastapi_sqlalchemy_or_openai():
    import app.domain.practice_session as module

    tree = ast.parse(inspect.getsource(module))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".", 1)[0])
    assert names.isdisjoint({"fastapi", "sqlalchemy", "openai"}), names
