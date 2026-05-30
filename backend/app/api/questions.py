from fastapi import APIRouter

from app.domain.conjugation import Question
from app.services.question_service import get_next_question

router = APIRouter(prefix="/api/questions", tags=["questions"])


@router.get("/next", response_model=Question)
def next_question() -> Question:
    return get_next_question()
