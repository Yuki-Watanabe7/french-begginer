from fastapi import APIRouter, HTTPException

from app.domain.conjugation import AnswerCheck, AnswerResult, check_answer

router = APIRouter(prefix="/api/answers", tags=["answers"])


@router.post("/check", response_model=AnswerResult)
def check(req: AnswerCheck) -> AnswerResult:
    try:
        return check_answer(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
