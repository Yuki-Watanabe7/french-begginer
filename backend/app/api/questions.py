from fastapi import APIRouter, HTTPException, Query

from app.domain.conjugation import Question, VerbGroup, VerbLevel, VerbPattern
from app.services.question_service import get_next_question, get_session_questions

router = APIRouter(prefix="/api/questions", tags=["questions"])


@router.get("/next", response_model=Question)
def next_question(
    group: VerbGroup = Query(default="all"),
    level: VerbLevel | None = Query(default=None),
    pattern: VerbPattern | None = Query(default=None),
) -> Question:
    try:
        return get_next_question(group=group, level=level, pattern=pattern)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/session", response_model=list[Question])
def session_questions(
    count: int = Query(default=10, ge=1, le=100),
    group: VerbGroup = Query(default="all"),
    level: VerbLevel | None = Query(default=None),
    pattern: VerbPattern | None = Query(default=None),
) -> list[Question]:
    try:
        return get_session_questions(
            count=count, group=group, level=level, pattern=pattern
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
