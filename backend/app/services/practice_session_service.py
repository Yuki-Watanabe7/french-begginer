"""Tutor Practice Session の組み立て（Issue #150）。

repository から LearningItem / Source を読み、domain の selection policy で
Session を作る。Session 自体は保存しない。router は HTTP 変換だけ行う。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from app.domain.practice_session import (
    DEFAULT_QUESTION_COUNT,
    DEFAULT_SESSION_SEED,
    InvalidPracticeSessionRequestError,
    PracticeSession,
    UnknownPracticeItemError,
    build_practice_session,
)
from app.domain.tutor import LearningItem, SourceDocument
from app.repositories.protocols import (
    LearningItemRepository,
    SourceDocumentRepository,
)
from app.services.exceptions import (
    InvalidPracticeFilterError,
    TutorNotFoundError,
)


class _PracticeStore(Protocol):
    source_documents: SourceDocumentRepository
    learning_items: LearningItemRepository


def build_practice_session_service(store: _PracticeStore) -> PracticeSessionService:
    """repository から PracticeSessionService を組み立てる。"""
    return PracticeSessionService(
        sources=store.source_documents,
        items=store.learning_items,
    )


class PracticeSessionService:
    def __init__(
        self,
        *,
        sources: SourceDocumentRepository,
        items: LearningItemRepository,
    ) -> None:
        self._sources = sources
        self._items = items

    def create_session(
        self,
        *,
        source_id: str | None = None,
        item_ids: Sequence[str] | None = None,
        question_count: int = DEFAULT_QUESTION_COUNT,
        seed: str | int | None = None,
    ) -> PracticeSession:
        """active LearningItem から Practice Session を組み立てる。

        source_id と item_ids は同時指定しない。どちらも無ければ
        保存済み LearningItem 全体から選ぶ。
        """
        if source_id is not None and item_ids is not None:
            raise InvalidPracticeFilterError(
                "source_id と item_ids は同時に指定できない"
            )
        if source_id is not None:
            self._require_source(source_id)
        all_items = self._items.list()
        if item_ids is not None:
            self._require_items(item_ids, all_items)

        try:
            return build_practice_session(
                all_items,
                sources=self._sources.list(),
                source_id=source_id,
                item_ids=item_ids,
                question_count=question_count,
                seed=DEFAULT_SESSION_SEED if seed is None else seed,
            )
        except UnknownPracticeItemError as exc:
            raise TutorNotFoundError("LearningItem", exc.item_id) from exc
        except InvalidPracticeSessionRequestError as exc:
            raise InvalidPracticeFilterError(str(exc)) from exc

    def _require_source(self, source_id: str) -> SourceDocument:
        document = self._sources.get(source_id)
        if document is None:
            raise TutorNotFoundError("SourceDocument", source_id)
        return document

    def _require_items(
        self, item_ids: Sequence[str], items: Sequence[LearningItem]
    ) -> None:
        known = {item.id for item in items}
        for item_id in item_ids:
            if item_id not in known:
                raise TutorNotFoundError("LearningItem", item_id)
