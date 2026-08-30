"""Tutor API の依存性注入。

router は service だけを受け取り、SQLite / OpenAI を直接見ない。
テストは `get_tutor_store` と `get_learning_item_extractor` を差し替える。
"""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from app.repositories.sqlite import TutorSqliteStore
from app.services.candidate_service import CandidateService, build_candidate_service
from app.services.exercise_service import ExerciseService, build_exercise_service
from app.services.extraction_service import ExtractionService
from app.services.extractors import LearningItemExtractor
from app.services.openai_extractor import OpenAILearningItemExtractor
from app.services.practice_session_service import (
    PracticeSessionService,
    build_practice_session_service,
)
from app.services.tutor_service import TutorService, build_tutor_service


@lru_cache(maxsize=1)
def get_tutor_store() -> TutorSqliteStore:
    return TutorSqliteStore.from_env()


def get_learning_item_extractor() -> LearningItemExtractor:
    return OpenAILearningItemExtractor()


def get_extraction_service(
    extractor: Annotated[LearningItemExtractor, Depends(get_learning_item_extractor)],
) -> ExtractionService:
    return ExtractionService(extractor)


def get_tutor_service(
    store: Annotated[TutorSqliteStore, Depends(get_tutor_store)],
) -> TutorService:
    return build_tutor_service(store)


def get_candidate_service(
    store: Annotated[TutorSqliteStore, Depends(get_tutor_store)],
    extraction: Annotated[ExtractionService, Depends(get_extraction_service)],
) -> CandidateService:
    return build_candidate_service(store, extraction)


def get_exercise_service(
    store: Annotated[TutorSqliteStore, Depends(get_tutor_store)],
    tutor: Annotated[TutorService, Depends(get_tutor_service)],
) -> ExerciseService:
    return build_exercise_service(store, tutor)


def get_practice_session_service(
    store: Annotated[TutorSqliteStore, Depends(get_tutor_store)],
) -> PracticeSessionService:
    return build_practice_session_service(store)
