from fastapi import APIRouter, HTTPException

from app.domain.noun import (
    NounCategory,
    NounGenderAnswerCheck,
    NounGenderAnswerResult,
    NounGenderQuestion,
    NounLevel,
    check_noun_gender_answer,
)
from app.services.noun_service import get_random_noun_question

router = APIRouter(prefix="/api/nouns", tags=["nouns"])


@router.get("/next", response_model=NounGenderQuestion)
def next_noun_question(
    level: NounLevel | None = None,
    category: NounCategory | None = None,
) -> NounGenderQuestion:
    question = get_random_noun_question(level=level, category=category)
    if question is None:
        raise HTTPException(
            status_code=404, detail="No nouns found for the given filters"
        )
    return question


@router.post("/check", response_model=NounGenderAnswerResult)
def check_noun_answer(req: NounGenderAnswerCheck) -> NounGenderAnswerResult:
    try:
        return check_noun_gender_answer(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
