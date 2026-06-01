from fastapi import APIRouter, HTTPException

from app.domain.noun import (
    NounGenderAnswerCheck,
    NounGenderAnswerResult,
    NounGenderQuestion,
    check_noun_gender_answer,
)
from app.services.noun_service import get_random_noun_question

router = APIRouter(prefix="/api/nouns", tags=["nouns"])


@router.get("/next", response_model=NounGenderQuestion)
def next_noun_question() -> NounGenderQuestion:
    return get_random_noun_question()


@router.post("/check", response_model=NounGenderAnswerResult)
def check_noun_answer(req: NounGenderAnswerCheck) -> NounGenderAnswerResult:
    try:
        return check_noun_gender_answer(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
