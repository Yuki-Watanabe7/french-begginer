"""Tutorデータの SQLAlchemy テーブル定義。

domain の Pydantic モデルとは別に持つ。service / domain はこのモジュールに
依存せず、repository 実装だけがマッピングを知る。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    JSON,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.domain.tutor import (
    LearnerState,
    LearningEvent,
    LearningItem,
    LearningItemCandidate,
    ReviewSchedule,
    SourceDocument,
)
from app.persistence.datetime_codec import dump_utc, load_utc


class Base(DeclarativeBase):
    pass


class SchemaMigrationRow(Base):
    __tablename__ = "schema_migrations"

    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    applied_at: Mapped[str] = mapped_column(String, nullable=False)


class SourceDocumentRow(Base):
    __tablename__ = "source_documents"
    __table_args__ = (
        Index(
            "ix_source_documents_ingestion_identity",
            "canonical_locator",
            "source_type",
            "content_hash",
            "ingestion_version",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_type: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata_json", JSON, nullable=False
    )
    content_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    ingestion_version: Mapped[str | None] = mapped_column(String, nullable=True)
    canonical_locator: Mapped[str | None] = mapped_column(String, nullable=True)
    provenance_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    segments_json: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)

    @classmethod
    def from_domain(cls, document: SourceDocument) -> SourceDocumentRow:
        provenance = document.provenance
        return cls(
            id=document.id,
            source_type=document.source_type,
            title=document.title,
            content=document.content,
            language=document.language,
            created_at=dump_utc(document.created_at),
            extra_metadata=document.metadata,
            content_hash=document.content_hash,
            ingestion_version=document.ingestion_version,
            canonical_locator=(
                None if provenance is None else provenance.canonical_locator
            ),
            provenance_json=(
                None if provenance is None else provenance.model_dump(mode="json")
            ),
            segments_json=[
                segment.model_dump(mode="json") for segment in document.segments
            ],
        )

    def to_domain(self) -> SourceDocument:
        return SourceDocument.model_validate(
            {
                "id": self.id,
                "source_type": self.source_type,
                "title": self.title,
                "content": self.content,
                "language": self.language,
                "created_at": load_utc(self.created_at),
                "metadata": self.extra_metadata,
                "content_hash": self.content_hash,
                "ingestion_version": self.ingestion_version,
                "provenance": self.provenance_json,
                "segments": self.segments_json or [],
            }
        )


class LearningItemRow(Base):
    __tablename__ = "learning_items"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    item_type: Mapped[str] = mapped_column(String, nullable=False)
    canonical_form: Mapped[str] = mapped_column(String, nullable=False)
    meaning_ja: Mapped[str] = mapped_column(String, nullable=False)
    explanation_ja: Mapped[str | None] = mapped_column(Text, nullable=True)
    level: Mapped[str | None] = mapped_column(String, nullable=True)
    source_refs: Mapped[list[dict[str, Any]]] = mapped_column(
        "source_refs_json", JSON, nullable=False
    )
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata_json", JSON, nullable=False
    )

    @classmethod
    def from_domain(cls, item: LearningItem) -> LearningItemRow:
        return cls(
            id=item.id,
            item_type=item.item_type,
            canonical_form=item.canonical_form,
            meaning_ja=item.meaning_ja,
            explanation_ja=item.explanation_ja,
            level=item.level,
            source_refs=[ref.model_dump(mode="json") for ref in item.source_refs],
            created_at=dump_utc(item.created_at),
            status=item.status,
            extra_metadata=item.metadata,
        )

    def to_domain(self) -> LearningItem:
        return LearningItem.model_validate(
            {
                "id": self.id,
                "item_type": self.item_type,
                "canonical_form": self.canonical_form,
                "meaning_ja": self.meaning_ja,
                "explanation_ja": self.explanation_ja,
                "level": self.level,
                "source_refs": self.source_refs,
                "created_at": load_utc(self.created_at),
                "status": self.status,
                "metadata": self.extra_metadata,
            }
        )


class LearningItemCandidateRow(Base):
    __tablename__ = "learning_item_candidates"
    __table_args__ = (
        Index(
            "ix_learning_item_candidates_source_created",
            "source_document_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_document_id: Mapped[str] = mapped_column(
        ForeignKey("source_documents.id", ondelete="RESTRICT"),
        nullable=False,
    )
    item_type: Mapped[str] = mapped_column(String, nullable=False)
    canonical_form: Mapped[str] = mapped_column(String, nullable=False)
    meaning_ja: Mapped[str] = mapped_column(String, nullable=False)
    explanation_ja: Mapped[str | None] = mapped_column(Text, nullable=True)
    level: Mapped[str | None] = mapped_column(String, nullable=True)
    evidence_span: Mapped[dict[str, Any]] = mapped_column(
        "evidence_span_json", JSON, nullable=False
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    extraction_version: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata_json", JSON, nullable=False
    )

    @classmethod
    def from_domain(cls, candidate: LearningItemCandidate) -> LearningItemCandidateRow:
        return cls(
            id=candidate.id,
            source_document_id=candidate.source_document_id,
            item_type=candidate.item_type,
            canonical_form=candidate.canonical_form,
            meaning_ja=candidate.meaning_ja,
            explanation_ja=candidate.explanation_ja,
            level=candidate.level,
            evidence_span=candidate.evidence_span.model_dump(mode="json"),
            confidence=candidate.confidence,
            status=candidate.status,
            extraction_version=candidate.extraction_version,
            created_at=dump_utc(candidate.created_at),
            extra_metadata=candidate.metadata,
        )

    def to_domain(self) -> LearningItemCandidate:
        return LearningItemCandidate.model_validate(
            {
                "id": self.id,
                "source_document_id": self.source_document_id,
                "item_type": self.item_type,
                "canonical_form": self.canonical_form,
                "meaning_ja": self.meaning_ja,
                "explanation_ja": self.explanation_ja,
                "level": self.level,
                "evidence_span": self.evidence_span,
                "confidence": self.confidence,
                "status": self.status,
                "extraction_version": self.extraction_version,
                "created_at": load_utc(self.created_at),
                "metadata": self.extra_metadata,
            }
        )


class LearningEventRow(Base):
    __tablename__ = "learning_events"
    __table_args__ = (
        Index(
            "ix_learning_events_item_occurred",
            "learning_item_id",
            "occurred_at",
            "id",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    learning_item_id: Mapped[str] = mapped_column(
        ForeignKey("learning_items.id", ondelete="RESTRICT"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    exercise_type: Mapped[str] = mapped_column(String, nullable=False)
    result: Mapped[str] = mapped_column(String, nullable=False)
    occurred_at: Mapped[str] = mapped_column(String, nullable=False)
    response_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata_json", JSON, nullable=False
    )

    @classmethod
    def from_domain(cls, event: LearningEvent) -> LearningEventRow:
        return cls(
            id=event.id,
            learning_item_id=event.learning_item_id,
            event_type=event.event_type,
            exercise_type=event.exercise_type,
            result=event.result,
            occurred_at=dump_utc(event.occurred_at),
            response_time_ms=event.response_time_ms,
            extra_metadata=event.metadata,
        )

    def to_domain(self) -> LearningEvent:
        return LearningEvent.model_validate(
            {
                "id": self.id,
                "learning_item_id": self.learning_item_id,
                "event_type": self.event_type,
                "exercise_type": self.exercise_type,
                "result": self.result,
                "occurred_at": load_utc(self.occurred_at),
                "response_time_ms": self.response_time_ms,
                "metadata": self.extra_metadata,
            }
        )


class LearnerStateRow(Base):
    __tablename__ = "learner_states"

    learning_item_id: Mapped[str] = mapped_column(
        ForeignKey("learning_items.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    correct_count: Mapped[int] = mapped_column(Integer, nullable=False)
    incorrect_count: Mapped[int] = mapped_column(Integer, nullable=False)
    consecutive_correct: Mapped[int] = mapped_column(Integer, nullable=False)
    last_reviewed_at: Mapped[str | None] = mapped_column(String, nullable=True)
    mastery_score: Mapped[float] = mapped_column(Float, nullable=False)
    by_direction: Mapped[dict[str, Any]] = mapped_column(
        "by_direction_json", JSON, nullable=False
    )

    @classmethod
    def from_domain(cls, state: LearnerState) -> LearnerStateRow:
        return cls(
            learning_item_id=state.learning_item_id,
            attempt_count=state.attempt_count,
            correct_count=state.correct_count,
            incorrect_count=state.incorrect_count,
            consecutive_correct=state.consecutive_correct,
            last_reviewed_at=(
                dump_utc(state.last_reviewed_at)
                if state.last_reviewed_at is not None
                else None
            ),
            mastery_score=state.mastery_score,
            by_direction={
                direction: stats.model_dump(mode="json")
                for direction, stats in state.by_direction.items()
            },
        )

    def to_domain(self) -> LearnerState:
        return LearnerState(
            learning_item_id=self.learning_item_id,
            attempt_count=self.attempt_count,
            correct_count=self.correct_count,
            incorrect_count=self.incorrect_count,
            consecutive_correct=self.consecutive_correct,
            last_reviewed_at=(
                load_utc(self.last_reviewed_at)
                if self.last_reviewed_at is not None
                else None
            ),
            mastery_score=self.mastery_score,
            by_direction=self.by_direction,
        )


class ReviewScheduleRow(Base):
    __tablename__ = "review_schedules"
    __table_args__ = (
        UniqueConstraint(
            "learning_item_id",
            "skill_direction",
            name="uq_review_schedules_item_direction",
        ),
        Index("ix_review_schedules_due_at", "due_at"),
    )

    learning_item_id: Mapped[str] = mapped_column(
        ForeignKey("learning_items.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    skill_direction: Mapped[str] = mapped_column(String, primary_key=True)
    due_at: Mapped[str] = mapped_column(String, nullable=False)
    interval_days: Mapped[float] = mapped_column(Float, nullable=False)
    review_count: Mapped[int] = mapped_column(Integer, nullable=False)
    lapse_count: Mapped[int] = mapped_column(Integer, nullable=False)
    scheduler_version: Mapped[str] = mapped_column(String, nullable=False)
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata_json", JSON, nullable=False
    )

    @classmethod
    def from_domain(cls, schedule: ReviewSchedule) -> ReviewScheduleRow:
        return cls(
            learning_item_id=schedule.learning_item_id,
            skill_direction=schedule.skill_direction,
            due_at=dump_utc(schedule.due_at),
            interval_days=schedule.interval_days,
            review_count=schedule.review_count,
            lapse_count=schedule.lapse_count,
            scheduler_version=schedule.scheduler_version,
            extra_metadata=schedule.metadata,
        )

    def to_domain(self) -> ReviewSchedule:
        return ReviewSchedule(
            learning_item_id=self.learning_item_id,
            skill_direction=self.skill_direction,
            due_at=load_utc(self.due_at),
            interval_days=self.interval_days,
            review_count=self.review_count,
            lapse_count=self.lapse_count,
            scheduler_version=self.scheduler_version,
            metadata=self.extra_metadata,
        )
