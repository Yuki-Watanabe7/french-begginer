"""Tutorデータの Repository interface。

service / domain が SQLite や ORM に直接依存しないための境界。
Phase 0 で必要な操作だけを定義し、汎用 CRUD にはしない。

LearningItem の delete は意図的に持たない。履歴（LearningEvent）を
失う削除を安易に許可しないため。
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.domain.tutor import (
    LearnerState,
    LearningEvent,
    LearningItem,
    ReviewSchedule,
    SourceDocument,
)


class SourceDocumentRepository(Protocol):
    def create(self, document: SourceDocument) -> SourceDocument: ...
    def get(self, document_id: str) -> SourceDocument | None: ...
    def list(self) -> list[SourceDocument]: ...


class LearningItemRepository(Protocol):
    def create(self, item: LearningItem) -> LearningItem: ...
    def get(self, item_id: str) -> LearningItem | None: ...
    def list(self) -> list[LearningItem]: ...


class LearningEventRepository(Protocol):
    def append(self, event: LearningEvent) -> LearningEvent: ...
    def list_by_item(self, item_id: str) -> list[LearningEvent]: ...


class LearnerStateRepository(Protocol):
    def get(self, item_id: str) -> LearnerState | None: ...
    def upsert(self, state: LearnerState) -> LearnerState: ...


class LearningProgressRepository(Protocol):
    """event の append と state の upsert を同一トランザクションで行う。"""

    def append_event_and_upsert_state(
        self, event: LearningEvent, state: LearnerState
    ) -> tuple[LearningEvent, LearnerState]: ...


class ReviewScheduleRepository(Protocol):
    def get(self, item_id: str) -> ReviewSchedule | None: ...
    def upsert(self, schedule: ReviewSchedule) -> ReviewSchedule: ...
    def list_due(self, now: datetime) -> list[ReviewSchedule]:
        """due_at <= now かつ LearningItem.status == active の予定を返す。

        返却順は due_at 昇順、同じ due_at なら learning_item_id 昇順。
        suspended / mastered は due でも含めない。
        """
        ...
