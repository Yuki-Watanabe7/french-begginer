"""Tutor Exercise の取得と回答記録（Issue #149）。

LearningItem / Source / 既存動詞 domain から Exercise を再構成し、
server-side で採点したあと既存の `record_review` パイプラインへ接続する。
router は HTTP 変換だけ行い、正解判定と永続化はここに置く。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.domain.exercise import exercise_event_metadata
from app.domain.exercise_evaluation import (
    ExerciseEvaluation,
    MalformedExerciseAnswerError,
    evaluate_exercise_answer,
)
from app.domain.exercise_generation import (
    DEFAULT_GENERATION_SEED,
    GeneratedExercise,
    generate_exercise,
)
from app.domain.tutor import (
    ExerciseType,
    LearnerState,
    LearningEvent,
    LearningItem,
    ReviewSchedule,
    SourceDocument,
    UtcDatetime,
)
from app.repositories.protocols import (
    LearningItemRepository,
    SourceDocumentRepository,
)
from app.services.exceptions import (
    TutorMalformedAnswerError,
    TutorNotFoundError,
    TutorUnsupportedExerciseError,
)
from app.services.tutor_service import ReviewRecord, TutorService


class _ExerciseStore(Protocol):
    source_documents: SourceDocumentRepository
    learning_items: LearningItemRepository


@dataclass(frozen=True)
class ExerciseAnswerRecord:
    """採点結果と、既存パイプラインが更新した学習状態。"""

    evaluation: ExerciseEvaluation
    explanation_ja: str | None
    source_context: str | None
    event: LearningEvent
    learner_state: LearnerState
    review_schedule: ReviewSchedule


def build_exercise_service(
    store: _ExerciseStore, tutor: TutorService
) -> ExerciseService:
    """repository と TutorService から ExerciseService を組み立てる。"""
    return ExerciseService(
        sources=store.source_documents,
        items=store.learning_items,
        tutor=tutor,
    )


class ExerciseService:
    def __init__(
        self,
        *,
        sources: SourceDocumentRepository,
        items: LearningItemRepository,
        tutor: TutorService,
    ) -> None:
        self._sources = sources
        self._items = items
        self._tutor = tutor

    def get_exercise(
        self, item_id: str, exercise_type: ExerciseType
    ) -> GeneratedExercise:
        """item から Exercise を再構成する。公開 DTO 化は API 層が行う。"""
        return self._generate(item_id, exercise_type)

    def submit_answer(
        self,
        item_id: str,
        exercise_type: ExerciseType,
        answer: str | list[str],
        *,
        event_id: str | None = None,
        occurred_at: UtcDatetime | None = None,
        response_time_ms: int | None = None,
    ) -> ExerciseAnswerRecord:
        """同じ Exercise を再構成して採点し、LearningEvent を記録する。"""
        item = self._require_item(item_id)
        generated = self._generate_for_item(item, exercise_type)
        try:
            evaluation = evaluate_exercise_answer(generated, answer)
        except MalformedExerciseAnswerError as exc:
            raise TutorMalformedAnswerError(str(exc)) from exc

        result = "correct" if evaluation.correct else "incorrect"
        metadata = exercise_event_metadata(generated.spec)
        record = self._tutor.record_review(
            item_id,
            exercise_type=exercise_type,
            result=result,
            occurred_at=occurred_at,
            response_time_ms=response_time_ms,
            event_id=event_id,
            metadata=metadata,
        )
        return self._to_answer_record(item, generated, evaluation, record)

    def _generate(self, item_id: str, exercise_type: ExerciseType) -> GeneratedExercise:
        item = self._require_item(item_id)
        return self._generate_for_item(item, exercise_type)

    def _generate_for_item(
        self, item: LearningItem, exercise_type: ExerciseType
    ) -> GeneratedExercise:
        result = generate_exercise(
            item,
            exercise_type,
            pool=self._items.list(),
            seed=DEFAULT_GENERATION_SEED,
            sources=self._sources_for(item),
        )
        if not result.eligible or result.exercise is None:
            raise TutorUnsupportedExerciseError(
                item.id,
                exercise_type,
                result.skip_reason or "unsupported_combination",
                result.detail or "unsupported exercise",
            )
        return result.exercise

    def _require_item(self, item_id: str) -> LearningItem:
        item = self._items.get(item_id)
        if item is None:
            raise TutorNotFoundError("LearningItem", item_id)
        return item

    def _sources_for(self, item: LearningItem) -> dict[str, SourceDocument]:
        sources: dict[str, SourceDocument] = {}
        for ref in item.source_refs:
            document = self._sources.get(ref.source_document_id)
            if document is not None:
                sources[document.id] = document
        return sources

    def _to_answer_record(
        self,
        item: LearningItem,
        generated: GeneratedExercise,
        evaluation: ExerciseEvaluation,
        record: ReviewRecord,
    ) -> ExerciseAnswerRecord:
        return ExerciseAnswerRecord(
            evaluation=evaluation,
            explanation_ja=item.explanation_ja,
            source_context=generated.spec.source_context,
            event=record.event,
            learner_state=record.learner_state,
            review_schedule=record.review_schedule,
        )
