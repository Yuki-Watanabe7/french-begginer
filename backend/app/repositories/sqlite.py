"""Tutor Repository の SQLite 実装。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.domain.review_scheduler import DIRECTION_ORDER, DUE_ITEM_STATUS
from app.domain.tutor import (
    CandidateStatus,
    LearnerState,
    LearningEvent,
    LearningItem,
    LearningItemCandidate,
    ReviewSchedule,
    SkillDirection,
    SourceDocument,
    apply_candidate_status,
)
from app.persistence.datetime_codec import dump_utc, require_aware
from app.persistence.db import create_initialized_engine
from app.persistence.models import (
    LearnerStateRow,
    LearningEventRow,
    LearningItemCandidateRow,
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

    def list(self, *, limit: int | None = None) -> list[SourceDocument]:
        stmt = select(SourceDocumentRow).order_by(
            SourceDocumentRow.created_at.desc(), SourceDocumentRow.id
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        with self._sessions() as session:
            rows = session.scalars(stmt).all()
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


class SqliteLearningItemCandidateRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def create(self, candidate: LearningItemCandidate) -> LearningItemCandidate:
        self.create_many([candidate])
        return candidate

    def create_many(
        self, candidates: Sequence[LearningItemCandidate]
    ) -> list[LearningItemCandidate]:
        if not candidates:
            return []
        with self._sessions() as session:
            for candidate in candidates:
                _require_source_document(session, candidate.source_document_id)
                session.add(LearningItemCandidateRow.from_domain(candidate))
            _commit_or_duplicate(session, "LearningItemCandidate", candidates[0].id)
        return list(candidates)

    def get(self, candidate_id: str) -> LearningItemCandidate | None:
        with self._sessions() as session:
            row = session.get(LearningItemCandidateRow, candidate_id)
            return row.to_domain() if row is not None else None

    def list_by_source(self, source_id: str) -> list[LearningItemCandidate]:
        with self._sessions() as session:
            rows = session.scalars(
                select(LearningItemCandidateRow)
                .where(LearningItemCandidateRow.source_document_id == source_id)
                .order_by(
                    LearningItemCandidateRow.created_at,
                    LearningItemCandidateRow.id,
                )
            ).all()
            return [row.to_domain() for row in rows]

    def update_status(
        self, candidate_id: str, status: CandidateStatus
    ) -> LearningItemCandidate:
        with self._sessions() as session:
            row = session.get(LearningItemCandidateRow, candidate_id)
            if row is None:
                raise ReferentialIntegrityError(
                    f"LearningItemCandidate が存在しない: id={candidate_id}"
                )
            updated = apply_candidate_status(row.to_domain(), status)
            session.merge(LearningItemCandidateRow.from_domain(updated))
            session.commit()
        return updated


class SqliteCandidatePromotionRepository:
    """Candidate accepted 化と LearningItem 書き込みを同一トランザクションにする。"""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def persist_accept(
        self,
        candidate: LearningItemCandidate,
        item: LearningItem,
        *,
        create_item: bool,
    ) -> tuple[LearningItemCandidate, LearningItem]:
        with self._sessions() as session:
            row = session.get(LearningItemCandidateRow, candidate.id)
            if row is None:
                raise ReferentialIntegrityError(
                    f"LearningItemCandidate が存在しない: id={candidate.id}"
                )
            updated = apply_candidate_status(row.to_domain(), candidate.status)
            session.merge(LearningItemCandidateRow.from_domain(updated))
            if create_item:
                session.add(LearningItemRow.from_domain(item))
                _commit_or_duplicate(session, "LearningItem", item.id)
            else:
                if session.get(LearningItemRow, item.id) is None:
                    raise ReferentialIntegrityError(
                        f"LearningItem が存在しない: id={item.id}"
                    )
                session.merge(LearningItemRow.from_domain(item))
                session.commit()
        return updated, item


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

    def append_event_upsert_state_and_schedule(
        self,
        event: LearningEvent,
        state: LearnerState,
        schedule: ReviewSchedule,
    ) -> tuple[LearningEvent, LearnerState, ReviewSchedule]:
        if event.learning_item_id != state.learning_item_id:
            raise ValueError(
                "LearningEvent と LearnerState の learning_item_id が一致しない: "
                f"event={event.learning_item_id}, state={state.learning_item_id}"
            )
        if event.learning_item_id != schedule.learning_item_id:
            raise ValueError(
                "LearningEvent と ReviewSchedule の learning_item_id が一致しない: "
                f"event={event.learning_item_id}, schedule={schedule.learning_item_id}"
            )
        with self._sessions() as session:
            _require_learning_item(session, event.learning_item_id)
            try:
                session.add(LearningEventRow.from_domain(event))
                session.merge(LearnerStateRow.from_domain(state))
                session.merge(ReviewScheduleRow.from_domain(schedule))
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise DuplicateEntityError("LearningEvent", event.id) from exc
        return event, state, schedule


class SqliteReviewScheduleRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def get(self, item_id: str, direction: SkillDirection) -> ReviewSchedule | None:
        with self._sessions() as session:
            row = session.get(ReviewScheduleRow, (item_id, direction))
            return row.to_domain() if row is not None else None

    def upsert(self, schedule: ReviewSchedule) -> ReviewSchedule:
        with self._sessions() as session:
            _require_learning_item(session, schedule.learning_item_id)
            session.merge(ReviewScheduleRow.from_domain(schedule))
            session.commit()
        return schedule

    def list_for_item(self, item_id: str) -> list[ReviewSchedule]:
        with self._sessions() as session:
            rows = session.scalars(
                select(ReviewScheduleRow).where(
                    ReviewScheduleRow.learning_item_id == item_id
                )
            ).all()
        return _sort_schedules_for_item([row.to_domain() for row in rows])

    def list_due(
        self, now: datetime, direction: SkillDirection | None = None
    ) -> list[ReviewSchedule]:
        now_iso = dump_utc(require_aware(now))
        stmt = (
            select(ReviewScheduleRow)
            .join(
                LearningItemRow,
                ReviewScheduleRow.learning_item_id == LearningItemRow.id,
            )
            .where(ReviewScheduleRow.due_at <= now_iso)
            .where(LearningItemRow.status == DUE_ITEM_STATUS)
        )
        if direction is not None:
            stmt = stmt.where(ReviewScheduleRow.skill_direction == direction)
        stmt = stmt.order_by(
            ReviewScheduleRow.due_at,
            ReviewScheduleRow.learning_item_id,
            ReviewScheduleRow.skill_direction,
        )
        with self._sessions() as session:
            rows = session.scalars(stmt).all()
            return [row.to_domain() for row in rows]

    def replace_for_item(
        self, item_id: str, schedules: Sequence[ReviewSchedule]
    ) -> list[ReviewSchedule]:
        schedule_list = list(schedules)
        seen_directions: set[str] = set()
        for schedule in schedule_list:
            if schedule.learning_item_id != item_id:
                raise ValueError(
                    "replace_for_item の schedule が item_id と一致しない: "
                    f"item_id={item_id}, schedule={schedule.learning_item_id}"
                )
            if schedule.skill_direction in seen_directions:
                raise ValueError(
                    "replace_for_item に同一 skill_direction が重複している: "
                    f"item_id={item_id}, direction={schedule.skill_direction}"
                )
            seen_directions.add(schedule.skill_direction)
        with self._sessions() as session:
            _require_learning_item(session, item_id)
            session.execute(
                delete(ReviewScheduleRow).where(
                    ReviewScheduleRow.learning_item_id == item_id
                )
            )
            session.flush()
            for schedule in schedule_list:
                session.add(ReviewScheduleRow.from_domain(schedule))
            session.commit()
        return _sort_schedules_for_item(schedule_list)


@dataclass(frozen=True)
class TutorRepositories:
    source_documents: SqliteSourceDocumentRepository
    learning_items: SqliteLearningItemRepository
    learning_item_candidates: SqliteLearningItemCandidateRepository
    candidate_promotions: SqliteCandidatePromotionRepository
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
        self.learning_item_candidates = SqliteLearningItemCandidateRepository(
            self._sessions
        )
        self.candidate_promotions = SqliteCandidatePromotionRepository(self._sessions)
        self.learning_events = SqliteLearningEventRepository(self._sessions)
        self.learner_states = SqliteLearnerStateRepository(self._sessions)
        self.learning_progress = SqliteLearningProgressRepository(self._sessions)
        self.review_schedules = SqliteReviewScheduleRepository(self._sessions)

    def repositories(self) -> TutorRepositories:
        return TutorRepositories(
            source_documents=self.source_documents,
            learning_items=self.learning_items,
            learning_item_candidates=self.learning_item_candidates,
            candidate_promotions=self.candidate_promotions,
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


def _sort_schedules_for_item(schedules: list[ReviewSchedule]) -> list[ReviewSchedule]:
    order = {direction: index for index, direction in enumerate(DIRECTION_ORDER)}
    return sorted(schedules, key=lambda schedule: order[schedule.skill_direction])


def _require_learning_item(session: Session, item_id: str) -> None:
    if session.get(LearningItemRow, item_id) is None:
        raise ReferentialIntegrityError(f"LearningItem が存在しない: id={item_id}")


def _require_source_document(session: Session, source_id: str) -> None:
    if session.get(SourceDocumentRow, source_id) is None:
        raise ReferentialIntegrityError(f"SourceDocument が存在しない: id={source_id}")


def _commit_or_duplicate(session: Session, entity_type: str, entity_id: str) -> None:
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise DuplicateEntityError(entity_type, entity_id) from exc
