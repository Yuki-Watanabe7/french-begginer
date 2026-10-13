"""複数 Source 文脈の context rotation（Issue #202）。

同じ LearningItem を別の出典で再提示し、直近の文脈を避け、
履歴が同じなら同じ文脈を選ぶ。正解判定の根拠は変えない。
"""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.domain.context_selection import (
    POLICY_VERSION,
    ContextUsage,
    context_usages_from_events,
    usages_for_exercise,
)
from app.domain.daily_learning_plan import DailyLearningPlan, DailyLearningPlanEntry
from app.domain.exercise_generation import generate_exercise
from app.domain.practice_session import build_practice_session
from app.domain.recommendation_signal import (
    FEATURE_VERSION,
    DirectionSignal,
    RecommendationSignalSnapshot,
)
from app.domain.review_queue import build_review_queue
from app.domain.review_session import build_review_practice_session
from app.domain.source_ingestion import SourceSegment
from app.domain.today_session import build_today_learning_session
from app.domain.tutor import (
    EvidenceSpan,
    LearningEvent,
    LearningItem,
    ReviewSchedule,
    SourceDocument,
    SourceRef,
)
from app.repositories.sqlite import TutorSqliteStore
from app.services.exercise_service import build_exercise_service
from app.services.practice_session_service import build_practice_session_service
from app.services.review_session_service import build_review_session_service
from app.services.tutor_service import build_tutor_service

NOW = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
ITEM_ID = "item-livre"


def _source(
    source_id: str,
    content: str,
    created_at: datetime,
    **overrides: object,
) -> SourceDocument:
    values: dict[str, object] = {
        "id": source_id,
        "title": source_id,
        "content": content,
        "created_at": created_at,
    }
    values.update(overrides)
    return SourceDocument(**values)  # type: ignore[arg-type]


def _ref(source: SourceDocument, fragment: str) -> SourceRef:
    start = source.content.index(fragment)
    return SourceRef(
        source_document_id=source.id,
        evidence_span=EvidenceSpan(start=start, end=start + len(fragment)),
    )


def _item(*refs: SourceRef, item_id: str = ITEM_ID) -> LearningItem:
    return LearningItem(
        id=item_id,
        item_type="vocabulary",
        canonical_form="livre",
        meaning_ja="本",
        source_refs=list(refs),
    )


def _usage(
    source: SourceDocument,
    fragment: str,
    *,
    at: datetime,
    event_id: str,
    exercise_type: str = "cloze",
    with_span: bool = True,
) -> ContextUsage:
    start = source.content.index(fragment)
    end = start + len(fragment)
    return ContextUsage(
        exercise_type=exercise_type,  # type: ignore[arg-type]
        source_document_id=source.id,
        evidence_start=start if with_span else None,
        evidence_end=end if with_span else None,
        exercise_version="exercise-v1",
        occurred_at=at,
        event_id=event_id,
    )


def _event(
    source: SourceDocument,
    fragment: str | None,
    *,
    at: datetime,
    event_id: str,
    exercise_type: str = "cloze",
) -> LearningEvent:
    metadata: dict[str, object] = {
        "source_document_id": source.id,
        "exercise_version": "exercise-v1",
    }
    if fragment is not None:
        start = source.content.index(fragment)
        end = start + len(fragment)
        metadata["evidence_start"] = start
        metadata["evidence_end"] = end
        metadata["source_evidence_id"] = f"{source.id}:{start}:{end}"
    return LearningEvent(
        id=event_id,
        learning_item_id=ITEM_ID,
        exercise_type=exercise_type,  # type: ignore[arg-type]
        result="correct",
        occurred_at=at,
        metadata=metadata,
    )


def _pair() -> tuple[SourceDocument, SourceDocument, LearningItem, str, str]:
    older_text = "Je lis un livre rouge aujourd'hui."
    newer_text = "Voici un petit livre pour toi."
    older = _source(
        "src-old",
        older_text,
        datetime(2026, 1, 1, tzinfo=UTC),
    )
    newer = _source(
        "src-new",
        newer_text,
        datetime(2026, 6, 1, tzinfo=UTC),
    )
    item = _item(_ref(older, "livre rouge"), _ref(newer, "petit livre"))
    return older, newer, item, "livre rouge", "petit livre"


def _cloze(
    item: LearningItem,
    sources: list[SourceDocument],
    usages: tuple[ContextUsage, ...] = (),
    *,
    seed: str = "fixed",
):
    result = generate_exercise(
        item,
        "cloze",
        sources=sources,
        context_usages=usages,
        seed=seed,
    )
    assert result.exercise is not None, result.skip_reason
    return result.exercise


def test_two_source_refs_rotate_away_from_the_recent_context() -> None:
    older, newer, item, old_fragment, new_fragment = _pair()
    sources = [newer, older]
    first = _cloze(item, sources)
    assert first.spec.metadata["source_document_id"] == older.id
    assert first.spec.metadata["context_selection_reason"] == "unused_context"
    assert first.spec.metadata["context_policy_version"] == POLICY_VERSION
    assert first.answer_key.expected_answers == (old_fragment,)
    assert "____" in first.spec.prompt
    assert new_fragment not in first.spec.prompt

    second = _cloze(
        item,
        sources,
        (_usage(older, old_fragment, at=NOW, event_id="evt-old"),),
    )
    assert second.spec.metadata["source_document_id"] == newer.id
    assert second.spec.metadata["context_selection_reason"] == "unused_context"
    assert second.answer_key.expected_answers == (new_fragment,)
    assert old_fragment not in second.spec.prompt

    third = _cloze(
        item,
        sources,
        (
            _usage(older, old_fragment, at=NOW, event_id="evt-old"),
            _usage(
                newer,
                new_fragment,
                at=NOW + timedelta(days=1),
                event_id="evt-new",
            ),
        ),
    )
    assert third.spec.metadata["source_document_id"] == older.id
    assert third.spec.metadata["context_selection_reason"] == "least_recent_context"
    assert third.answer_key.expected_answers == (old_fragment,)


def test_three_source_refs_avoid_the_most_recent_context() -> None:
    first_text = "Je lis un livre rouge."
    second_text = "Elle ouvre un livre bleu."
    third_text = "Il ferme un livre vert."
    created = (
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 2, 1, tzinfo=UTC),
        datetime(2026, 3, 1, tzinfo=UTC),
    )
    fragments = ("livre rouge", "livre bleu", "livre vert")
    sources = [
        _source(f"src-{index}", text, created[index])
        for index, text in enumerate((first_text, second_text, third_text))
    ]
    refs = [
        _ref(source, fragment)
        for source, fragment in zip(sources, fragments, strict=True)
    ]
    item = _item(*refs)
    usages: list[ContextUsage] = []
    for index, (source, fragment) in enumerate(zip(sources, fragments, strict=True)):
        exercise = _cloze(item, sources, tuple(usages))
        assert exercise.spec.metadata["source_document_id"] == source.id
        assert fragment.split()[1] in exercise.answer_key.expected_answers[0]
        usages.append(
            _usage(
                source,
                fragment,
                at=NOW + timedelta(days=index),
                event_id=f"evt-{index}",
            )
        )
    again = _cloze(item, sources, tuple(usages))
    assert again.spec.metadata["source_document_id"] == sources[0].id
    assert again.spec.metadata["context_selection_reason"] == "least_recent_context"


def test_single_source_ref_stays_on_that_context() -> None:
    content = "Je lis un livre rouge aujourd'hui."
    source = _source("src-only", content, datetime(2026, 1, 1, tzinfo=UTC))
    item = _item(_ref(source, "livre rouge"))
    usage = _usage(source, "livre rouge", at=NOW, event_id="evt-only")
    exercise = _cloze(item, [source], (usage,))
    assert exercise.spec.metadata["source_document_id"] == source.id
    assert exercise.spec.metadata["context_selection_reason"] == "single_valid_context"
    assert exercise.answer_key.expected_answers == ("livre rouge",)
    again = _cloze(item, [source])
    assert again.spec.prompt == exercise.spec.prompt


def test_invalid_evidence_is_not_selected() -> None:
    valid_text = "Je lis un livre rouge aujourd'hui."
    valid = _source("src-valid", valid_text, datetime(2026, 6, 1, tzinfo=UTC))
    item = LearningItem(
        id=ITEM_ID,
        item_type="vocabulary",
        canonical_form="livre",
        meaning_ja="本",
        source_refs=[
            SourceRef(
                source_document_id="src-missing",
                evidence_span=EvidenceSpan(start=0, end=4),
            ),
            SourceRef(
                source_document_id=valid.id,
                evidence_span=EvidenceSpan(start=0, end=len(valid_text)),
            ),
            _ref(valid, "livre rouge"),
        ],
    )
    usage = _usage(valid, "livre rouge", at=NOW, event_id="evt-valid")
    exercise = _cloze(item, [valid], (usage,))
    assert exercise.spec.metadata["source_document_id"] == valid.id
    assert exercise.spec.metadata["context_selection_reason"] == "single_valid_context"
    assert exercise.answer_key.expected_answers == ("livre rouge",)


def test_same_history_is_deterministic() -> None:
    older, newer, item, old_fragment, new_fragment = _pair()
    events = [
        _event(
            newer,
            new_fragment,
            at=NOW + timedelta(days=2),
            event_id="evt-new",
        ),
        _event(older, old_fragment, at=NOW, event_id="evt-old"),
    ]
    forward = context_usages_from_events(events)
    backward = context_usages_from_events(list(reversed(events)))
    assert [row.event_id for row in forward] == ["evt-old", "evt-new"]
    assert backward == forward
    sources = [newer, older]
    first = _cloze(item, sources, forward, seed="alpha")
    second = _cloze(item, sources, backward, seed="beta")
    assert first.spec.prompt == second.spec.prompt
    assert first.spec.metadata["source_document_id"] == older.id
    assert first.answer_key.expected_answers == second.answer_key.expected_answers


def test_legacy_event_without_span_still_avoids_that_source() -> None:
    older, newer, item, _old_fragment, new_fragment = _pair()
    usages = context_usages_from_events(
        [_event(older, None, at=NOW, event_id="evt-legacy")]
    )
    assert usages[0].evidence_start is None
    assert usages[0].exercise_version == "exercise-v1"
    exercise = _cloze(item, [older, newer], usages)
    assert exercise.spec.metadata["source_document_id"] == newer.id
    assert exercise.answer_key.expected_answers == (new_fragment,)


def test_same_source_uses_evidence_id_to_rotate_spans() -> None:
    content = "Je lis un livre rouge. Je lis un livre bleu."
    source = _source("src-same", content, datetime(2026, 1, 1, tzinfo=UTC))
    item = _item(_ref(source, "livre bleu"), _ref(source, "livre rouge"))
    first = _cloze(item, [source])
    assert first.answer_key.expected_answers == ("livre rouge",)
    second = _cloze(
        item,
        [source],
        (_usage(source, "livre rouge", at=NOW, event_id="evt-span"),),
    )
    assert second.answer_key.expected_answers == ("livre bleu",)
    blue_start = content.index("livre bleu")
    blue_end = blue_start + len("livre bleu")
    assert second.spec.metadata["source_evidence_id"] == (
        f"{source.id}:{blue_start}:{blue_end}"
    )


def test_pdf_page_and_transcript_timestamp_stay_on_the_selected_context() -> None:
    pdf_text = "Je lis un livre rouge aujourd'hui."
    transcript_text = "Voici un petit livre pour toi."
    pdf = _source(
        "src-pdf",
        pdf_text,
        datetime(2026, 1, 1, tzinfo=UTC),
        source_type="pdf",
        segments=[
            SourceSegment(
                normalized_start=0,
                normalized_end=len(pdf_text),
                page_number=4,
            )
        ],
    )
    transcript = _source(
        "src-transcript",
        transcript_text,
        datetime(2026, 6, 1, tzinfo=UTC),
        source_type="youtube_transcript",
        segments=[
            SourceSegment(
                normalized_start=0,
                normalized_end=len(transcript_text),
                start_seconds=12.0,
                end_seconds=15.5,
                timestamp="2026-03-01T00:00:12Z",
            )
        ],
    )
    item = _item(_ref(pdf, "livre rouge"), _ref(transcript, "petit livre"))
    first = _cloze(item, [transcript, pdf])
    assert first.spec.metadata["page_number"] == 4
    assert "timestamp" not in first.spec.metadata
    second = _cloze(
        item,
        [pdf, transcript],
        (_usage(pdf, "livre rouge", at=NOW, event_id="evt-pdf"),),
    )
    assert second.spec.metadata["source_document_id"] == transcript.id
    assert second.spec.metadata["timestamp"] == "2026-03-01T00:00:12Z"
    assert second.spec.metadata["start_seconds"] == 12.0
    assert second.spec.metadata["end_seconds"] == 15.5
    assert "page_number" not in second.spec.metadata


def test_other_items_source_is_not_mixed_into_the_canonical_item() -> None:
    older, newer, item, old_fragment, _new_fragment = _pair()
    foreign = _source(
        "src-foreign",
        "Un autre livre étranger est ici.",
        datetime(2020, 1, 1, tzinfo=UTC),
    )
    exercise = _cloze(item, [foreign, older, newer])
    assert exercise.spec.metadata["source_document_id"] == older.id
    assert exercise.answer_key.expected_answers == (old_fragment,)
    assert "étranger" not in exercise.spec.prompt


def test_ja_to_fr_answer_stays_canonical_form() -> None:
    older, newer, item, old_fragment, _new_fragment = _pair()
    usage = _usage(older, old_fragment, at=NOW, event_id="evt-old")
    result = generate_exercise(
        item,
        "ja_to_fr",
        sources=[older, newer],
        context_usages=(usage,),
        seed="fixed",
    )
    assert result.exercise is not None
    spec = result.exercise.spec
    assert result.exercise.answer_key.expected_answers == ("livre",)
    assert spec.source_context is None
    assert "source_document_id" not in spec.metadata
    assert "context_selection_reason" not in spec.metadata


def test_meaning_recognition_context_does_not_change_cloze_or_the_answer() -> None:
    older, newer, item, old_fragment, new_fragment = _pair()
    pool = (
        item,
        LearningItem(
            id="other",
            item_type="vocabulary",
            canonical_form="chat",
            meaning_ja="猫",
        ),
        LearningItem(
            id="maison",
            item_type="vocabulary",
            canonical_form="maison",
            meaning_ja="家",
        ),
    )
    meaning_usage = _usage(
        older,
        old_fragment,
        at=NOW,
        event_id="evt-meaning",
        exercise_type="meaning_recognition",
    )
    sources = [older, newer]
    cloze = _cloze(item, sources, (meaning_usage,))
    assert cloze.spec.metadata["source_document_id"] == older.id
    recognition = generate_exercise(
        item,
        "meaning_recognition",
        pool=pool,
        sources=sources,
        context_usages=(meaning_usage,),
        seed="fixed",
    )
    assert recognition.exercise is not None
    assert recognition.exercise.answer_key.expected_answers == ("本",)
    assert recognition.exercise.spec.prompt.endswith("livre")
    assert new_fragment in (recognition.exercise.spec.source_context or "")
    assert old_fragment not in (recognition.exercise.spec.source_context or "")
    cloze_usage = _usage(older, old_fragment, at=NOW, event_id="evt-cloze")
    still_first_context = generate_exercise(
        item,
        "meaning_recognition",
        pool=pool,
        sources=sources,
        context_usages=(cloze_usage,),
        seed="fixed",
    )
    assert still_first_context.exercise is not None
    assert old_fragment in (still_first_context.exercise.spec.source_context or "")


def test_missing_source_does_not_fail_the_session() -> None:
    older, newer, item, _old_fragment, new_fragment = _pair()
    usage = _usage(newer, new_fragment, at=NOW, event_id="evt-new")
    partial = build_practice_session(
        [item],
        sources=[newer],
        item_ids=[item.id],
        question_count=3,
        context_usages_by_item={item.id: (usage,)},
    )
    cloze = next(row for row in partial.exercises if row.spec.exercise_type == "cloze")
    assert cloze.spec.metadata["source_document_id"] == newer.id
    assert cloze.spec.metadata["context_selection_reason"] == "single_valid_context"
    assert any(row.spec.exercise_type == "ja_to_fr" for row in partial.exercises)

    empty = build_review_practice_session(
        build_review_queue(
            [
                ReviewSchedule(
                    learning_item_id=item.id,
                    skill_direction="production",
                    due_at=NOW - timedelta(days=1),
                    interval_days=1.0,
                    review_count=1,
                )
            ],
            items_by_id={item.id: item},
            now=NOW,
        ).entries,
        pool=(item,),
        sources=[],
        question_count=1,
    )
    assert empty.generated_count == 1
    assert empty.exercises[0].spec.exercise_type == "ja_to_fr"
    assert empty.exercises[0].answer_key.expected_answers == ("livre",)


def test_review_and_today_sessions_rotate_with_the_same_history() -> None:
    older, newer, item, old_fragment, new_fragment = _pair()
    usages = (_usage(older, old_fragment, at=NOW, event_id="evt-old"),)
    review = build_review_practice_session(
        build_review_queue(
            [
                ReviewSchedule(
                    learning_item_id=item.id,
                    skill_direction="production",
                    due_at=NOW - timedelta(days=1),
                    interval_days=1.0,
                    review_count=1,
                )
            ],
            items_by_id={item.id: item},
            now=NOW,
        ).entries,
        pool=(item,),
        sources=[older, newer],
        question_count=1,
        context_usages_by_item={item.id: usages},
    )
    assert review.exercises[0].spec.metadata["source_document_id"] == newer.id
    assert review.exercises[0].answer_key.expected_answers == (new_fragment,)

    snapshot = RecommendationSignalSnapshot(
        learning_item_id=item.id,
        computed_at=NOW,
        feature_version=FEATURE_VERSION,
        by_direction={
            "production": DirectionSignal(
                skill_direction="production",
                mastery_score=0.5,
                attempt_count=2,
                consecutive_correct=0,
                is_unseen=False,
                review_urgency="due",
                overdue_days=1.0,
                lapse_count=0,
                recent_error_rate=0.0,
                recent_incorrect_count=0,
                recent_correct_count=2,
            )
        },
        learner_level="B1",
        source_ref_count=2,
        interest_weight=1.0,
        importance_weight=1.0,
    )
    plan = DailyLearningPlan(
        generated_at=NOW,
        requested_count=1,
        review_count=1,
        new_count=0,
        entries=(
            DailyLearningPlanEntry(
                learning_item_id=item.id,
                skill_direction="production",
                activity_kind="review",
                selected_exercise_type="cloze",
                rank_score=1.0,
            ),
        ),
        deferred_due_count=0,
        explanation_summary="review",
    )
    today = build_today_learning_session(
        plan,
        items_by_id={item.id: item},
        snapshots_by_id={item.id: snapshot},
        sources=[older, newer],
        context_usages_by_item={item.id: usages},
    )
    assert today.generated_count == 1
    assert today.exercises[0].spec.metadata["source_document_id"] == newer.id


def test_recent_context_survives_reopen_and_changes_the_cloze_answer(
    tmp_path: Path,
) -> None:
    pdf_text = "Je lis un livre rouge aujourd'hui."
    transcript_text = "Voici un petit livre pour toi."
    url = f"sqlite:///{tmp_path / 'context.db'}"
    store = TutorSqliteStore(url)
    pdf = store.source_documents.create(
        _source(
            "src-pdf",
            pdf_text,
            datetime(2026, 1, 1, tzinfo=UTC),
            source_type="pdf",
            segments=[
                SourceSegment(
                    normalized_start=0,
                    normalized_end=len(pdf_text),
                    page_number=4,
                )
            ],
        )
    )
    transcript = store.source_documents.create(
        _source(
            "src-transcript",
            transcript_text,
            datetime(2026, 6, 1, tzinfo=UTC),
            source_type="youtube_transcript",
            segments=[
                SourceSegment(
                    normalized_start=0,
                    normalized_end=len(transcript_text),
                    start_seconds=12.0,
                    end_seconds=15.5,
                    timestamp="2026-03-01T00:00:12Z",
                )
            ],
        )
    )
    item = store.learning_items.create(
        _item(_ref(pdf, "livre rouge"), _ref(transcript, "petit livre"))
    )
    tutor = build_tutor_service(store, clock=lambda: NOW)
    exercises = build_exercise_service(store, tutor)
    first = exercises.get_exercise(item.id, "cloze")
    assert first.spec.metadata["page_number"] == 4
    recorded = exercises.submit_answer(
        item.id,
        "cloze",
        first.answer_key.expected_answers[0],
        event_id="evt-pdf",
    )
    assert recorded.evaluation.correct is True
    assert recorded.event.metadata["exercise_version"] == "exercise-v1"
    assert recorded.event.metadata["source_document_id"] == pdf.id
    rouge_start = pdf_text.index("livre rouge")
    rouge_end = rouge_start + len("livre rouge")
    assert recorded.event.metadata["source_evidence_id"].endswith(
        f":{rouge_start}:{rouge_end}"
    )
    assert recorded.event.metadata["context_policy_version"] == POLICY_VERSION
    assert recorded.event.metadata["page_number"] == 4
    assert "petit livre" not in (recorded.source_context or "")
    store.engine.dispose()

    reopened = TutorSqliteStore(url)
    try:
        reloaded = reopened.learning_events.list_by_item(item.id)
        assert len(reloaded) == 1
        assert reloaded[0].metadata["page_number"] == 4
        assert (
            reloaded[0].metadata["source_evidence_id"]
            == (recorded.event.metadata["source_evidence_id"])
        )
        service = build_exercise_service(
            reopened,
            build_tutor_service(reopened, clock=lambda: NOW + timedelta(days=3)),
        )
        second = service.get_exercise(item.id, "cloze")
        repeated = service.get_exercise(item.id, "cloze")
        assert second.spec.prompt == repeated.spec.prompt
        assert second.spec.metadata["source_document_id"] == transcript.id
        assert second.spec.metadata["timestamp"] == "2026-03-01T00:00:12Z"
        assert second.answer_key.expected_answers == ("petit livre",)
        assert second.answer_key.expected_answers != first.answer_key.expected_answers
        practice = build_practice_session_service(reopened).create_session(
            item_ids=[item.id],
            question_count=3,
        )
        practice_cloze = next(
            row for row in practice.exercises if row.spec.exercise_type == "cloze"
        )
        assert practice_cloze.spec.metadata["source_document_id"] == transcript.id
        wrong = service.submit_answer(
            item.id,
            "cloze",
            "livre rouge",
            event_id="evt-wrong-slice",
        )
        assert wrong.evaluation.correct is False
        assert wrong.evaluation.correct_answer == "petit livre"
    finally:
        reopened.engine.dispose()


def test_review_service_reads_persisted_context_history() -> None:
    store = TutorSqliteStore.in_memory()
    older, newer, _item_template, old_fragment, new_fragment = _pair()
    older = store.source_documents.create(older)
    newer = store.source_documents.create(newer)
    item = store.learning_items.create(
        _item(_ref(older, old_fragment), _ref(newer, new_fragment))
    )
    tutor = build_tutor_service(store, clock=lambda: NOW)
    exercises = build_exercise_service(store, tutor)
    first = exercises.get_exercise(item.id, "cloze")
    exercises.submit_answer(
        item.id,
        "cloze",
        first.answer_key.expected_answers[0],
        event_id="evt-old",
    )
    session = build_review_session_service(store, tutor).create_session(
        question_count=1,
        now=NOW + timedelta(days=30),
    )
    assert session.generated_count == 1
    assert session.exercises[0].spec.exercise_type == "cloze"
    assert session.exercises[0].spec.metadata["source_document_id"] == newer.id
    assert session.exercises[0].answer_key.expected_answers == (new_fragment,)
    store.engine.dispose()


def test_meaning_and_cloze_histories_stay_separate_in_usages() -> None:
    older, _newer, _item_template, old_fragment, _new_fragment = _pair()
    events = [
        _event(
            older,
            old_fragment,
            at=NOW,
            event_id="evt-meaning",
            exercise_type="meaning_recognition",
        ),
        _event(older, old_fragment, at=NOW, event_id="evt-cloze"),
    ]
    usages = context_usages_from_events(events)
    assert [row.exercise_type for row in usages_for_exercise(usages, "cloze")] == [
        "cloze"
    ]
    assert [
        row.exercise_type for row in usages_for_exercise(usages, "meaning_recognition")
    ] == ["meaning_recognition"]


def test_context_selection_does_not_import_random_or_llm() -> None:
    import app.domain.context_selection as module

    tree = ast.parse(inspect.getsource(module))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".", 1)[0])
    assert names.isdisjoint({"random", "openai", "fastapi", "sqlalchemy"})
