from fastapi import APIRouter, HTTPException, Query

from app.domain.conjugation import Question, VerbGroup, VerbLevel, VerbPattern
from app.services.question_service import get_next_question

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
