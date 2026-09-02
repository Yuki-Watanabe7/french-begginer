"""due queue から Review Practice Session を組み立てる（Issue #164）。

TutorService の due queue と LearningItem / Source を読み、domain の
selection policy で Session を作る。Session 自体は保存しない。
未回答 / skip では ReviewSchedule を更新しない。
router は HTTP 変換だけ行う。
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.domain.review_queue import MAX_QUEUE_LIMIT
from app.domain.review_session import (
    DEFAULT_QUESTION_COUNT,
    DEFAULT_REVIEW_SESSION_SEED,
    InvalidReviewSessionRequestError,
    ReviewPracticeSession,
    build_review_practice_session,
)
from app.repositories.protocols import (
    LearningItemRepository,
    SourceDocumentRepository,
)
from app.services.exceptions import InvalidReviewSessionError
from app.services.tutor_service import TutorService


class _ReviewSessionStore(Protocol):
    source_documents: SourceDocumentRepository
    learning_items: LearningItemRepository


def build_review_session_service(
    store: _ReviewSessionStore,
    tutor: TutorService,
) -> ReviewSessionService:
    """repository と TutorService から ReviewSessionService を組み立てる。"""
    return ReviewSessionService(
        sources=store.source_documents,
        items=store.learning_items,
        tutor=tutor,
    )


class ReviewSessionService:
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

    def create_session(
        self,
        *,
        question_count: int = DEFAULT_QUESTION_COUNT,
        seed: str | int | None = None,
        now: datetime | None = None,
    ) -> ReviewPracticeSession:
        """due review queue から Review Practice Session を組み立てる。

        `now` 未指定時は TutorService の clock。HTTP から任意時刻は受け取らない。
        新規 / 未 due Item は混ぜない。Session は保存しない。
        """
        queue = self._tutor.list_review_queue(now, limit=MAX_QUEUE_LIMIT)
        try:
            return build_review_practice_session(
                queue.entries,
                pool=self._items.list(),
                sources=self._sources.list(),
                question_count=question_count,
                seed=DEFAULT_REVIEW_SESSION_SEED if seed is None else seed,
            )
        except InvalidReviewSessionRequestError as exc:
            raise InvalidReviewSessionError(str(exc)) from exc
