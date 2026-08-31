"""Tutorデータの Repository interface。

service / domain が SQLite や ORM に直接依存しないための境界。
Phase 0 で必要な操作だけを定義し、汎用 CRUD にはしない。

LearningItem の delete は意図的に持たない。履歴（LearningEvent）を
失う削除を安易に許可しないため。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from app.domain.tutor import (
    CandidateStatus,
    LearnerState,
    LearningEvent,
    LearningItem,
    LearningItemCandidate,
    ReviewSchedule,
    SkillDirection,
    SourceDocument,
)


class SourceDocumentRepository(Protocol):
    def create(self, document: SourceDocument) -> SourceDocument: ...
    def get(self, document_id: str) -> SourceDocument | None: ...
    def list(self, *, limit: int | None = None) -> list[SourceDocument]:
        """created_at 降順。同一時刻は id 昇順。limit 未指定なら全件。"""
        ...


class LearningItemRepository(Protocol):
    def create(self, item: LearningItem) -> LearningItem: ...
    def get(self, item_id: str) -> LearningItem | None: ...
    def list(self) -> list[LearningItem]: ...


class LearningItemCandidateRepository(Protocol):
    def create(self, candidate: LearningItemCandidate) -> LearningItemCandidate: ...
    def create_many(
        self, candidates: Sequence[LearningItemCandidate]
    ) -> list[LearningItemCandidate]:
        """複数 Candidate を同一トランザクションで保存する。空なら何もしない。"""
        ...

    def get(self, candidate_id: str) -> LearningItemCandidate | None: ...
    def list_by_source(self, source_id: str) -> list[LearningItemCandidate]:
        """同一 Source の Candidate。created_at 昇順、同一時刻は id 昇順。"""
        ...

    def update_status(
        self, candidate_id: str, status: CandidateStatus
    ) -> LearningItemCandidate:
        """status を candidate / accepted / rejected として更新する。

        存在しない Candidate や、accepted / rejected からの不正な遷移は拒否する。
        """
        ...


class CandidatePromotionRepository(Protocol):
    def persist_accept(
        self,
        candidate: LearningItemCandidate,
        item: LearningItem,
        *,
        create_item: bool,
    ) -> tuple[LearningItemCandidate, LearningItem]:
        """Candidate の accepted 化と LearningItem の create/update を同一 TX で行う。

        create_item=True なら LearningItem を新規作成し、False なら既存を更新する。
        どちらかが失敗したら Candidate も元の status のまま残る。
        """
        ...


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
    def get(self, item_id: str, direction: SkillDirection) -> ReviewSchedule | None: ...
    def upsert(self, schedule: ReviewSchedule) -> ReviewSchedule: ...
    def list_for_item(self, item_id: str) -> list[ReviewSchedule]:
        """同一 LearningItem の direction 別予定。recognition → production 順。"""
        ...

    def list_due(
        self, now: datetime, direction: SkillDirection | None = None
    ) -> list[ReviewSchedule]:
        """due_at <= now かつ LearningItem.status == active の予定を返す。

        direction を指定するとその方向だけ。未指定なら両方向。
        返却順は due_at 昇順、同じ due_at なら learning_item_id、skill_direction 昇順。
        suspended / mastered は due でも含めない。
        """
        ...
