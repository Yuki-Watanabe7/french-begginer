from typing import Literal, TypedDict

from pydantic import BaseModel

NounGender = Literal["masculine", "feminine"]


class NounData(TypedDict):
    gender: Literal["masculine", "feminine"]
    meaning_ja: str


NOUNS: dict[str, NounData] = {
    "livre": {"gender": "masculine", "meaning_ja": "本"},
    "maison": {"gender": "feminine", "meaning_ja": "家"},
    "chat": {"gender": "masculine", "meaning_ja": "猫"},
    "voiture": {"gender": "feminine", "meaning_ja": "車"},
    "chien": {"gender": "masculine", "meaning_ja": "犬"},
    "fleur": {"gender": "feminine", "meaning_ja": "花"},
    "arbre": {"gender": "masculine", "meaning_ja": "木"},
    "eau": {"gender": "feminine", "meaning_ja": "水"},
    "pain": {"gender": "masculine", "meaning_ja": "パン"},
    "table": {"gender": "feminine", "meaning_ja": "テーブル"},
    "soleil": {"gender": "masculine", "meaning_ja": "太陽"},
    "lune": {"gender": "feminine", "meaning_ja": "月"},
    "jardin": {"gender": "masculine", "meaning_ja": "庭"},
    "cuisine": {"gender": "feminine", "meaning_ja": "台所"},
    "stylo": {"gender": "masculine", "meaning_ja": "ペン"},
    "fenêtre": {"gender": "feminine", "meaning_ja": "窓"},
    "bureau": {"gender": "masculine", "meaning_ja": "机・事務所"},
    "porte": {"gender": "feminine", "meaning_ja": "ドア"},
    "film": {"gender": "masculine", "meaning_ja": "映画"},
    "musique": {"gender": "feminine", "meaning_ja": "音楽"},
    "temps": {"gender": "masculine", "meaning_ja": "時間・天気"},
    "nuit": {"gender": "feminine", "meaning_ja": "夜"},
    "matin": {"gender": "masculine", "meaning_ja": "朝"},
    "ville": {"gender": "feminine", "meaning_ja": "町・都市"},
    "pays": {"gender": "masculine", "meaning_ja": "国"},
    "rue": {"gender": "feminine", "meaning_ja": "通り"},
    "ami": {"gender": "masculine", "meaning_ja": "友人（男）"},
    "école": {"gender": "feminine", "meaning_ja": "学校"},
}


class NounGenderQuestion(BaseModel):
    noun: str
    meaning_ja: str | None = None


class NounGenderAnswerCheck(BaseModel):
    noun: str
    answer: NounGender


class NounGenderAnswerResult(BaseModel):
    correct: bool
    expected: NounGender
    given: NounGender


def get_noun_gender(noun: str) -> NounGender | None:
    data = NOUNS.get(noun)
    if data is None:
        return None
    return data["gender"]


def check_noun_gender_answer(req: NounGenderAnswerCheck) -> NounGenderAnswerResult:
    expected = get_noun_gender(req.noun)
    if expected is None:
        raise ValueError(f"Unknown noun: {req.noun}")
    correct = req.answer == expected
    return NounGenderAnswerResult(correct=correct, expected=expected, given=req.answer)
