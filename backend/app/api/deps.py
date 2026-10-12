"""Tutor API の依存性注入。

router は service だけを受け取り、SQLite / OpenAI を直接見ない。
テストは `get_tutor_store` と `get_learning_item_extractor` を差し替える。
"""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from app.ingestion.audio import TranscriptionProvider
from app.ingestion.audio_api import OpenAITranscriptionProvider
from app.ingestion.fetcher import WebPageFetcher
from app.ingestion.pdf_parser import PypdfTextParser
from app.ingestion.pdf_text import PdfTextParser
from app.ingestion.stdlib_http import build_web_page_fetcher
from app.ingestion.youtube import YoutubeTranscriptProvider
from app.ingestion.youtube_api import YoutubeTranscriptApiProvider
from app.repositories.sqlite import TutorSqliteStore
from app.services.audio_ingestion import AudioIngestionService
from app.services.candidate_service import CandidateService, build_candidate_service
from app.services.conversation_ingestion import ConversationIngestionService
from app.services.exercise_service import ExerciseService, build_exercise_service
from app.services.extraction_service import ExtractionService
from app.services.extractors import LearningItemExtractor
from app.services.openai_extractor import OpenAILearningItemExtractor
from app.services.pdf_ingestion import PdfIngestionService
from app.services.practice_session_service import (
    PracticeSessionService,
    build_practice_session_service,
)
from app.services.review_session_service import (
    ReviewSessionService,
    build_review_session_service,
)
from app.services.subtitle_ingestion import SubtitleIngestionService
from app.services.text_file_ingestion import TextFileIngestionService
from app.services.today_learning_service import (
    TodayLearningService,
    build_today_learning_service,
)
from app.services.tutor_service import TutorService, build_tutor_service
from app.services.web_url_ingestion import WebUrlIngestionService
from app.services.youtube_ingestion import YoutubeIngestionService


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


def get_review_session_service(
    store: Annotated[TutorSqliteStore, Depends(get_tutor_store)],
    tutor: Annotated[TutorService, Depends(get_tutor_service)],
) -> ReviewSessionService:
    return build_review_session_service(store, tutor)


def get_today_learning_service(
    store: Annotated[TutorSqliteStore, Depends(get_tutor_store)],
) -> TodayLearningService:
    return build_today_learning_service(store)


def get_web_page_fetcher() -> WebPageFetcher:
    """本番の URL 取得。テストは fake fetcher で上書きし、ネットワークを使わない。"""

    return build_web_page_fetcher()


def get_web_url_ingestion_service(
    store: Annotated[TutorSqliteStore, Depends(get_tutor_store)],
    fetcher: Annotated[WebPageFetcher, Depends(get_web_page_fetcher)],
) -> WebUrlIngestionService:
    return WebUrlIngestionService(store.source_documents, fetcher)


def get_pdf_text_parser() -> PdfTextParser:
    """本番の PDF 解析。テストは別実装で上書きし、OCR も外部 API も使わない。"""

    return PypdfTextParser()


def get_pdf_ingestion_service(
    store: Annotated[TutorSqliteStore, Depends(get_tutor_store)],
    parser: Annotated[PdfTextParser, Depends(get_pdf_text_parser)],
) -> PdfIngestionService:
    return PdfIngestionService(store.source_documents, parser)


def get_youtube_transcript_provider() -> YoutubeTranscriptProvider:
    """本番の公開字幕取得。テストは fake provider で上書きする。"""

    return YoutubeTranscriptApiProvider()


def get_youtube_ingestion_service(
    store: Annotated[TutorSqliteStore, Depends(get_tutor_store)],
    provider: Annotated[
        YoutubeTranscriptProvider, Depends(get_youtube_transcript_provider)
    ],
) -> YoutubeIngestionService:
    return YoutubeIngestionService(store.source_documents, provider)


def get_subtitle_ingestion_service(
    store: Annotated[TutorSqliteStore, Depends(get_tutor_store)],
) -> SubtitleIngestionService:
    return SubtitleIngestionService(store.source_documents)


def get_text_file_ingestion_service(
    store: Annotated[TutorSqliteStore, Depends(get_tutor_store)],
) -> TextFileIngestionService:
    return TextFileIngestionService(store.source_documents)


def get_conversation_ingestion_service(
    store: Annotated[TutorSqliteStore, Depends(get_tutor_store)],
) -> ConversationIngestionService:
    return ConversationIngestionService(store.source_documents)


def get_transcription_provider() -> TranscriptionProvider:
    """本番の文字起こし。テストは fake provider で上書きし、API key も使わない。"""

    return OpenAITranscriptionProvider()


def get_audio_ingestion_service(
    store: Annotated[TutorSqliteStore, Depends(get_tutor_store)],
    provider: Annotated[TranscriptionProvider, Depends(get_transcription_provider)],
) -> AudioIngestionService:
    return AudioIngestionService(store.source_documents, provider)
