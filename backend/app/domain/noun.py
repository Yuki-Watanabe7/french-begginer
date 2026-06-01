from typing import Literal, TypedDict

from pydantic import BaseModel

NounGender = Literal["masculine", "feminine"]
NounLevel = Literal["basic", "standard", "challenge"]
NounCategory = Literal[
    "person",
    "home",
    "food",
    "place",
    "time",
    "school",
    "nature",
    "abstract",
]


class NounData(TypedDict):
    gender: Literal["masculine", "feminine"]
    meaning_ja: str
    level: NounLevel
    category: NounCategory


NOUNS: dict[str, NounData] = {
    "livre": {
        "gender": "masculine",
        "meaning_ja": "本",
        "level": "basic",
        "category": "school",
    },
    "maison": {
        "gender": "feminine",
        "meaning_ja": "家",
        "level": "basic",
        "category": "home",
    },
    "chat": {
        "gender": "masculine",
        "meaning_ja": "猫",
        "level": "basic",
        "category": "nature",
    },
    "voiture": {
        "gender": "feminine",
        "meaning_ja": "車",
        "level": "basic",
        "category": "place",
    },
    "chien": {
        "gender": "masculine",
        "meaning_ja": "犬",
        "level": "basic",
        "category": "nature",
    },
    "fleur": {
        "gender": "feminine",
        "meaning_ja": "花",
        "level": "basic",
        "category": "nature",
    },
    "arbre": {
        "gender": "masculine",
        "meaning_ja": "木",
        "level": "basic",
        "category": "nature",
    },
    "eau": {
        "gender": "feminine",
        "meaning_ja": "水",
        "level": "basic",
        "category": "food",
    },
    "pain": {
        "gender": "masculine",
        "meaning_ja": "パン",
        "level": "basic",
        "category": "food",
    },
    "table": {
        "gender": "feminine",
        "meaning_ja": "テーブル",
        "level": "basic",
        "category": "home",
    },
    "soleil": {
        "gender": "masculine",
        "meaning_ja": "太陽",
        "level": "basic",
        "category": "nature",
    },
    "lune": {
        "gender": "feminine",
        "meaning_ja": "月",
        "level": "standard",
        "category": "nature",
    },
    "jardin": {
        "gender": "masculine",
        "meaning_ja": "庭",
        "level": "standard",
        "category": "home",
    },
    "cuisine": {
        "gender": "feminine",
        "meaning_ja": "台所",
        "level": "basic",
        "category": "home",
    },
    "stylo": {
        "gender": "masculine",
        "meaning_ja": "ペン",
        "level": "basic",
        "category": "school",
    },
    "fenêtre": {
        "gender": "feminine",
        "meaning_ja": "窓",
        "level": "standard",
        "category": "home",
    },
    "bureau": {
        "gender": "masculine",
        "meaning_ja": "机・事務所",
        "level": "standard",
        "category": "home",
    },
    "porte": {
        "gender": "feminine",
        "meaning_ja": "ドア",
        "level": "basic",
        "category": "home",
    },
    "film": {
        "gender": "masculine",
        "meaning_ja": "映画",
        "level": "standard",
        "category": "abstract",
    },
    "musique": {
        "gender": "feminine",
        "meaning_ja": "音楽",
        "level": "standard",
        "category": "abstract",
    },
    "temps": {
        "gender": "masculine",
        "meaning_ja": "時間・天気",
        "level": "basic",
        "category": "time",
    },
    "nuit": {
        "gender": "feminine",
        "meaning_ja": "夜",
        "level": "basic",
        "category": "time",
    },
    "matin": {
        "gender": "masculine",
        "meaning_ja": "朝",
        "level": "basic",
        "category": "time",
    },
    "ville": {
        "gender": "feminine",
        "meaning_ja": "町・都市",
        "level": "basic",
        "category": "place",
    },
    "pays": {
        "gender": "masculine",
        "meaning_ja": "国",
        "level": "basic",
        "category": "place",
    },
    "rue": {
        "gender": "feminine",
        "meaning_ja": "通り",
        "level": "standard",
        "category": "place",
    },
    "ami": {
        "gender": "masculine",
        "meaning_ja": "友人（男）",
        "level": "basic",
        "category": "person",
    },
    "école": {
        "gender": "feminine",
        "meaning_ja": "学校",
        "level": "basic",
        "category": "school",
    },
    # person
    "père": {
        "gender": "masculine",
        "meaning_ja": "父",
        "level": "basic",
        "category": "person",
    },
    "mère": {
        "gender": "feminine",
        "meaning_ja": "母",
        "level": "basic",
        "category": "person",
    },
    "homme": {
        "gender": "masculine",
        "meaning_ja": "男性",
        "level": "basic",
        "category": "person",
    },
    "femme": {
        "gender": "feminine",
        "meaning_ja": "女性",
        "level": "basic",
        "category": "person",
    },
    "frère": {
        "gender": "masculine",
        "meaning_ja": "兄弟",
        "level": "basic",
        "category": "person",
    },
    "sœur": {
        "gender": "feminine",
        "meaning_ja": "姉妹",
        "level": "basic",
        "category": "person",
    },
    # home
    "chambre": {
        "gender": "feminine",
        "meaning_ja": "部屋",
        "level": "basic",
        "category": "home",
    },
    "lit": {
        "gender": "masculine",
        "meaning_ja": "ベッド",
        "level": "basic",
        "category": "home",
    },
    "chaise": {
        "gender": "feminine",
        "meaning_ja": "椅子",
        "level": "standard",
        "category": "home",
    },
    "téléphone": {
        "gender": "masculine",
        "meaning_ja": "電話",
        "level": "basic",
        "category": "home",
    },
    # food
    "café": {
        "gender": "masculine",
        "meaning_ja": "コーヒー",
        "level": "basic",
        "category": "food",
    },
    "thé": {
        "gender": "masculine",
        "meaning_ja": "紅茶",
        "level": "basic",
        "category": "food",
    },
    "lait": {
        "gender": "masculine",
        "meaning_ja": "牛乳",
        "level": "basic",
        "category": "food",
    },
    "pomme": {
        "gender": "feminine",
        "meaning_ja": "りんご",
        "level": "basic",
        "category": "food",
    },
    "fromage": {
        "gender": "masculine",
        "meaning_ja": "チーズ",
        "level": "standard",
        "category": "food",
    },
    "poisson": {
        "gender": "masculine",
        "meaning_ja": "魚",
        "level": "basic",
        "category": "food",
    },
    # place
    "gare": {
        "gender": "feminine",
        "meaning_ja": "駅",
        "level": "basic",
        "category": "place",
    },
    "restaurant": {
        "gender": "masculine",
        "meaning_ja": "レストラン",
        "level": "basic",
        "category": "place",
    },
    "hôtel": {
        "gender": "masculine",
        "meaning_ja": "ホテル",
        "level": "standard",
        "category": "place",
    },
    "parc": {
        "gender": "masculine",
        "meaning_ja": "公園",
        "level": "basic",
        "category": "place",
    },
    "mer": {
        "gender": "feminine",
        "meaning_ja": "海",
        "level": "basic",
        "category": "place",
    },
    # time
    "jour": {
        "gender": "masculine",
        "meaning_ja": "日",
        "level": "basic",
        "category": "time",
    },
    "semaine": {
        "gender": "feminine",
        "meaning_ja": "週",
        "level": "basic",
        "category": "time",
    },
    "heure": {
        "gender": "feminine",
        "meaning_ja": "時間・時刻",
        "level": "basic",
        "category": "time",
    },
    "soir": {
        "gender": "masculine",
        "meaning_ja": "晩",
        "level": "basic",
        "category": "time",
    },
    # school
    "classe": {
        "gender": "feminine",
        "meaning_ja": "クラス・教室",
        "level": "basic",
        "category": "school",
    },
    "professeur": {
        "gender": "masculine",
        "meaning_ja": "先生",
        "level": "basic",
        "category": "school",
    },
    "cahier": {
        "gender": "masculine",
        "meaning_ja": "ノート",
        "level": "basic",
        "category": "school",
    },
    "crayon": {
        "gender": "masculine",
        "meaning_ja": "鉛筆",
        "level": "standard",
        "category": "school",
    },
    # abstract
    "idée": {
        "gender": "feminine",
        "meaning_ja": "考え",
        "level": "standard",
        "category": "abstract",
    },
    "question": {
        "gender": "feminine",
        "meaning_ja": "質問",
        "level": "basic",
        "category": "abstract",
    },
    "travail": {
        "gender": "masculine",
        "meaning_ja": "仕事",
        "level": "basic",
        "category": "abstract",
    },
    "nom": {
        "gender": "masculine",
        "meaning_ja": "名前",
        "level": "basic",
        "category": "abstract",
    },
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
