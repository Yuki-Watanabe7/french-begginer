from typing import Literal, TypedDict

from pydantic import BaseModel

VerbGroup = Literal["all", "er", "ir", "irregular"]

# How to add a new verb:
# 1. Add the verb and its group to VERB_GROUPS (er/ir/irregular)
# 2. Add all 6 présent conjugations to CONJUGATIONS
# 3. Add level + pattern metadata to VERB_METADATA
# 4. Add at least one test in tests/test_api.py


class VerbMeta(TypedDict):
    level: Literal["basic", "standard", "challenge"]
    pattern: Literal["regular", "stem_change", "spelling_change", "irregular"]


# level:   basic=最重要, standard=標準, challenge=応用
# pattern: regular=規則活用, stem_change=語幹変化,
#          spelling_change=綴り変化, irregular=不規則
VERB_METADATA: dict[str, VerbMeta] = {
    "parler": {"level": "basic", "pattern": "regular"},
    "aimer": {"level": "basic", "pattern": "regular"},
    "travailler": {"level": "basic", "pattern": "regular"},
    "finir": {"level": "basic", "pattern": "regular"},
    "choisir": {"level": "standard", "pattern": "regular"},
    "être": {"level": "basic", "pattern": "irregular"},
    "avoir": {"level": "basic", "pattern": "irregular"},
    "aller": {"level": "basic", "pattern": "irregular"},
    "faire": {"level": "standard", "pattern": "irregular"},
}

VERB_GROUPS: dict[str, Literal["er", "ir", "irregular"]] = {
    "parler": "er",
    "aimer": "er",
    "travailler": "er",
    "finir": "ir",
    "choisir": "ir",
    "être": "irregular",
    "avoir": "irregular",
    "aller": "irregular",
    "faire": "irregular",
}

CONJUGATIONS: dict[str, dict[str, dict[str, str]]] = {
    "parler": {
        "présent": {
            "je": "parle",
            "tu": "parles",
            "il/elle": "parle",
            "nous": "parlons",
            "vous": "parlez",
            "ils/elles": "parlent",
        }
    },
    "aimer": {
        "présent": {
            "je": "aime",
            "tu": "aimes",
            "il/elle": "aime",
            "nous": "aimons",
            "vous": "aimez",
            "ils/elles": "aiment",
        }
    },
    "travailler": {
        "présent": {
            "je": "travaille",
            "tu": "travailles",
            "il/elle": "travaille",
            "nous": "travaillons",
            "vous": "travaillez",
            "ils/elles": "travaillent",
        }
    },
    "finir": {
        "présent": {
            "je": "finis",
            "tu": "finis",
            "il/elle": "finit",
            "nous": "finissons",
            "vous": "finissez",
            "ils/elles": "finissent",
        }
    },
    "choisir": {
        "présent": {
            "je": "choisis",
            "tu": "choisis",
            "il/elle": "choisit",
            "nous": "choisissons",
            "vous": "choisissez",
            "ils/elles": "choisissent",
        }
    },
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
