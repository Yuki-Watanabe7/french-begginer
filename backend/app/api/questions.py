from fastapi import APIRouter, Query

from app.domain.conjugation import Question, VerbGroup
from app.services.question_service import get_next_question

router = APIRouter(prefix="/api/questions", tags=["questions"])


@router.get("/next", response_model=Question)
def next_question(group: VerbGroup | None = Query(default=None)) -> Question:
    return get_next_question(group)
