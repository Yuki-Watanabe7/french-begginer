"""Tutor Repository の SQLite 実装。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.domain.tutor import (
    LearnerState,
    LearningEvent,
    LearningItem,
    ReviewSchedule,
    SourceDocument,
)
from app.persistence.datetime_codec import dump_utc, require_aware
from app.persistence.db import create_initialized_engine
from app.persistence.models import (
    LearnerStateRow,
    LearningEventRow,
    LearningItemRow,
    ReviewScheduleRow,
    SourceDocumentRow,
)
from app.repositories.exceptions import DuplicateEntityError, ReferentialIntegrityError


class SqliteSourceDocumentRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def create(self, document: SourceDocument) -> SourceDocument:
        with self._sessions() as session:
            session.add(SourceDocumentRow.from_domain(document))
            _commit_or_duplicate(session, "SourceDocument", document.id)
        return document

    def get(self, document_id: str) -> SourceDocument | None:
        with self._sessions() as session:
            row = session.get(SourceDocumentRow, document_id)
            return row.to_domain() if row is not None else None

    def list(self) -> list[SourceDocument]:
        with self._sessions() as session:
            rows = session.scalars(
                select(SourceDocumentRow).order_by(
                    SourceDocumentRow.created_at, SourceDocumentRow.id
                )
            ).all()
            return [row.to_domain() for row in rows]


class SqliteLearningItemRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def create(self, item: LearningItem) -> LearningItem:
        with self._sessions() as session:
            session.add(LearningItemRow.from_domain(item))
            _commit_or_duplicate(session, "LearningItem", item.id)
        return item

    def get(self, item_id: str) -> LearningItem | None:
        with self._sessions() as session:
            row = session.get(LearningItemRow, item_id)
            return row.to_domain() if row is not None else None

    def list(self) -> list[LearningItem]:
        with self._sessions() as session:
            rows = session.scalars(
                select(LearningItemRow).order_by(
                    LearningItemRow.created_at, LearningItemRow.id
                )
            ).all()
            return [row.to_domain() for row in rows]


class SqliteLearningEventRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def append(self, event: LearningEvent) -> LearningEvent:
        with self._sessions() as session:
            _require_learning_item(session, event.learning_item_id)
            session.add(LearningEventRow.from_domain(event))
            _commit_or_duplicate(session, "LearningEvent", event.id)
        return event

    def list_by_item(self, item_id: str) -> list[LearningEvent]:
        with self._sessions() as session:
            rows = session.scalars(
                select(LearningEventRow)
                .where(LearningEventRow.learning_item_id == item_id)
                .order_by(LearningEventRow.occurred_at, LearningEventRow.id)
            ).all()
            return [row.to_domain() for row in rows]


class SqliteLearnerStateRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def get(self, item_id: str) -> LearnerState | None:
        with self._sessions() as session:
            row = session.get(LearnerStateRow, item_id)
            return row.to_domain() if row is not None else None

    def upsert(self, state: LearnerState) -> LearnerState:
        with self._sessions() as session:
            _require_learning_item(session, state.learning_item_id)
            session.merge(LearnerStateRow.from_domain(state))
            session.commit()
        return state


class SqliteLearningProgressRepository:
    """event 保存と state 更新を 1 トランザクションに閉じる。"""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def append_event_and_upsert_state(
        self, event: LearningEvent, state: LearnerState
    ) -> tuple[LearningEvent, LearnerState]:
        if event.learning_item_id != state.learning_item_id:
            raise ValueError(
                "LearningEvent と LearnerState の learning_item_id が一致しない: "
                f"event={event.learning_item_id}, state={state.learning_item_id}"
            )
        with self._sessions() as session:
            _require_learning_item(session, event.learning_item_id)
            try:
                session.add(LearningEventRow.from_domain(event))
                session.merge(LearnerStateRow.from_domain(state))
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise DuplicateEntityError("LearningEvent", event.id) from exc
        return event, state


class SqliteReviewScheduleRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def get(self, item_id: str) -> ReviewSchedule | None:
        with self._sessions() as session:
            row = session.get(ReviewScheduleRow, item_id)
            return row.to_domain() if row is not None else None

    def upsert(self, schedule: ReviewSchedule) -> ReviewSchedule:
        with self._sessions() as session:
            _require_learning_item(session, schedule.learning_item_id)
            session.merge(ReviewScheduleRow.from_domain(schedule))
            session.commit()
        return schedule

    def list_due(self, now: datetime) -> list[ReviewSchedule]:
        now_iso = dump_utc(require_aware(now))
        with self._sessions() as session:
            rows = session.scalars(
                select(ReviewScheduleRow)
                .where(ReviewScheduleRow.due_at <= now_iso)
                .order_by(ReviewScheduleRow.due_at, ReviewScheduleRow.learning_item_id)
            ).all()
            return [row.to_domain() for row in rows]


@dataclass(frozen=True)
class TutorRepositories:
    source_documents: SqliteSourceDocumentRepository
    learning_items: SqliteLearningItemRepository
    learning_events: SqliteLearningEventRepository
    learner_states: SqliteLearnerStateRepository
    learning_progress: SqliteLearningProgressRepository
    review_schedules: SqliteReviewScheduleRepository


class TutorSqliteStore:
    """1つの SQLite DB に対する Tutor repository 一式。"""

    def __init__(self, database_url: str | None = None) -> None:
        self.engine = create_initialized_engine(database_url)
        self._sessions: sessionmaker[Session] = sessionmaker(
            bind=self.engine, expire_on_commit=False
        )
        self.source_documents = SqliteSourceDocumentRepository(self._sessions)
        self.learning_items = SqliteLearningItemRepository(self._sessions)
        self.learning_events = SqliteLearningEventRepository(self._sessions)
        self.learner_states = SqliteLearnerStateRepository(self._sessions)
        self.learning_progress = SqliteLearningProgressRepository(self._sessions)
        self.review_schedules = SqliteReviewScheduleRepository(self._sessions)

    def repositories(self) -> TutorRepositories:
        return TutorRepositories(
            source_documents=self.source_documents,
            learning_items=self.learning_items,
            learning_events=self.learning_events,
            learner_states=self.learner_states,
            learning_progress=self.learning_progress,
            review_schedules=self.review_schedules,
        )

    @classmethod
    def from_env(cls) -> TutorSqliteStore:
        return cls()

    @classmethod
    def in_memory(cls) -> TutorSqliteStore:
        return cls("sqlite:///:memory:")


def _require_learning_item(session: Session, item_id: str) -> None:
    if session.get(LearningItemRow, item_id) is None:
        raise ReferentialIntegrityError(f"LearningItem が存在しない: id={item_id}")


def _commit_or_duplicate(session: Session, entity_type: str, entity_id: str) -> None:
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise DuplicateEntityError(entity_type, entity_id) from exc
