from pydantic import BaseModel

CONJUGATIONS: dict[str, dict[str, dict[str, str]]] = {
    "être": {
        "présent": {
            "je": "suis",
            "tu": "es",
            "il/elle": "est",
            "nous": "sommes",
            "vous": "êtes",
            "ils/elles": "sont",
        }
    },
    "avoir": {
        "présent": {
            "je": "ai",
            "tu": "as",
            "il/elle": "a",
            "nous": "avons",
            "vous": "avez",
            "ils/elles": "ont",
        }
    },
    "aller": {
        "présent": {
            "je": "vais",
            "tu": "vas",
            "il/elle": "va",
            "nous": "allons",
            "vous": "allez",
            "ils/elles": "vont",
        }
    },
    "faire": {
        "présent": {
            "je": "fais",
            "tu": "fais",
            "il/elle": "fait",
            "nous": "faisons",
            "vous": "faites",
            "ils/elles": "font",
        }
    },
}


class Question(BaseModel):
    verb: str
    tense: str
    pronoun: str


class AnswerCheck(BaseModel):
    verb: str
    tense: str
    pronoun: str
    answer: str


class AnswerResult(BaseModel):
    correct: bool
    expected: str
    given: str


def get_correct_answer(verb: str, tense: str, pronoun: str) -> str | None:
    return CONJUGATIONS.get(verb, {}).get(tense, {}).get(pronoun)


def check_answer(req: AnswerCheck) -> AnswerResult:
    expected = get_correct_answer(req.verb, req.tense, req.pronoun)
    if expected is None:
        raise ValueError(
            f"No conjugation found for {req.verb}/{req.tense}/{req.pronoun}"
        )
    correct = req.answer.strip().lower() == expected.lower()
    return AnswerResult(correct=correct, expected=expected, given=req.answer.strip())
