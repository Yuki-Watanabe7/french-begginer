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
ArticleIndefinite = Literal["un", "une"]
ArticleDefinite = Literal["le", "la", "l'"]


class NounData(TypedDict):
    gender: Literal["masculine", "feminine"]
    meaning_ja: str
    level: NounLevel
    category: NounCategory
    article_indefinite: ArticleIndefinite
    article_definite: ArticleDefinite
    plural: str


NOUNS: dict[str, NounData] = {
    "livre": {
        "gender": "masculine",
        "meaning_ja": "本",
        "level": "basic",
        "category": "school",
        "article_indefinite": "un",
        "article_definite": "le",
        "plural": "livres",
    },
    "maison": {
        "gender": "feminine",
        "meaning_ja": "家",
        "level": "basic",
        "category": "home",
        "article_indefinite": "une",
        "article_definite": "la",
        "plural": "maisons",
    },
    "chat": {
        "gender": "masculine",
        "meaning_ja": "猫",
        "level": "basic",
        "category": "nature",
        "article_indefinite": "un",
        "article_definite": "le",
        "plural": "chats",
    },
    "voiture": {
        "gender": "feminine",
        "meaning_ja": "車",
        "level": "basic",
        "category": "place",
        "article_indefinite": "une",
        "article_definite": "la",
        "plural": "voitures",
    },
    "chien": {
        "gender": "masculine",
        "meaning_ja": "犬",
        "level": "basic",
        "category": "nature",
        "article_indefinite": "un",
        "article_definite": "le",
        "plural": "chiens",
    },
    "fleur": {
        "gender": "feminine",
        "meaning_ja": "花",
        "level": "basic",
        "category": "nature",
        "article_indefinite": "une",
        "article_definite": "la",
        "plural": "fleurs",
    },
    "arbre": {
        "gender": "masculine",
        "meaning_ja": "木",
        "level": "basic",
        "category": "nature",
        "article_indefinite": "un",
        "article_definite": "l'",
        "plural": "arbres",
    },
    "eau": {
        "gender": "feminine",
        "meaning_ja": "水",
        "level": "basic",
        "category": "food",
        "article_indefinite": "une",
        "article_definite": "l'",
        "plural": "eaux",
    },
    "pain": {
        "gender": "masculine",
        "meaning_ja": "パン",
        "level": "basic",
        "category": "food",
        "article_indefinite": "un",
        "article_definite": "le",
        "plural": "pains",
    },
    "table": {
        "gender": "feminine",
        "meaning_ja": "テーブル",
        "level": "basic",
        "category": "home",
        "article_indefinite": "une",
        "article_definite": "la",
        "plural": "tables",
    },
    "soleil": {
        "gender": "masculine",
        "meaning_ja": "太陽",
        "level": "basic",
        "category": "nature",
        "article_indefinite": "un",
        "article_definite": "le",
        "plural": "soleils",
    },
    "lune": {
        "gender": "feminine",
        "meaning_ja": "月",
        "level": "standard",
        "category": "nature",
        "article_indefinite": "une",
        "article_definite": "la",
        "plural": "lunes",
    },
    "jardin": {
        "gender": "masculine",
        "meaning_ja": "庭",
        "level": "standard",
        "category": "home",
        "article_indefinite": "un",
        "article_definite": "le",
        "plural": "jardins",
    },
    "cuisine": {
        "gender": "feminine",
        "meaning_ja": "台所",
        "level": "basic",
        "category": "home",
        "article_indefinite": "une",
        "article_definite": "la",
        "plural": "cuisines",
    },
    "stylo": {
        "gender": "masculine",
        "meaning_ja": "ペン",
        "level": "basic",
        "category": "school",
        "article_indefinite": "un",
        "article_definite": "le",
        "plural": "stylos",
    },
    "fenêtre": {
        "gender": "feminine",
        "meaning_ja": "窓",
        "level": "standard",
        "category": "home",
        "article_indefinite": "une",
        "article_definite": "la",
        "plural": "fenêtres",
    },
    "bureau": {
        "gender": "masculine",
        "meaning_ja": "机・事務所",
        "level": "standard",
        "category": "home",
        "article_indefinite": "un",
        "article_definite": "le",
        "plural": "bureaux",
    },
    "porte": {
        "gender": "feminine",
        "meaning_ja": "ドア",
        "level": "basic",
        "category": "home",
        "article_indefinite": "une",
        "article_definite": "la",
        "plural": "portes",
    },
    "film": {
        "gender": "masculine",
        "meaning_ja": "映画",
        "level": "standard",
        "category": "abstract",
        "article_indefinite": "un",
        "article_definite": "le",
        "plural": "films",
    },
    "musique": {
        "gender": "feminine",
        "meaning_ja": "音楽",
        "level": "standard",
        "category": "abstract",
        "article_indefinite": "une",
        "article_definite": "la",
        "plural": "musiques",
    },
    "temps": {
        "gender": "masculine",
        "meaning_ja": "時間・天気",
        "level": "basic",
        "category": "time",
        "article_indefinite": "un",
        "article_definite": "le",
        "plural": "temps",
    },
    "nuit": {
        "gender": "feminine",
        "meaning_ja": "夜",
        "level": "basic",
        "category": "time",
        "article_indefinite": "une",
        "article_definite": "la",
        "plural": "nuits",
    },
    "matin": {
        "gender": "masculine",
        "meaning_ja": "朝",
        "level": "basic",
        "category": "time",
        "article_indefinite": "un",
        "article_definite": "le",
        "plural": "matins",
    },
    "ville": {
        "gender": "feminine",
        "meaning_ja": "町・都市",
        "level": "basic",
        "category": "place",
        "article_indefinite": "une",
        "article_definite": "la",
        "plural": "villes",
    },
    "pays": {
        "gender": "masculine",
        "meaning_ja": "国",
        "level": "basic",
        "category": "place",
        "article_indefinite": "un",
        "article_definite": "le",
        "plural": "pays",
    },
    "rue": {
        "gender": "feminine",
        "meaning_ja": "通り",
        "level": "standard",
        "category": "place",
        "article_indefinite": "une",
        "article_definite": "la",
        "plural": "rues",
    },
    "ami": {
        "gender": "masculine",
        "meaning_ja": "友人（男）",
        "level": "basic",
        "category": "person",
        "article_indefinite": "un",
        "article_definite": "l'",
        "plural": "amis",
    },
    "école": {
        "gender": "feminine",
        "meaning_ja": "学校",
        "level": "basic",
        "category": "school",
        "article_indefinite": "une",
        "article_definite": "l'",
        "plural": "écoles",
    },
    # person
    "père": {
        "gender": "masculine",
        "meaning_ja": "父",
        "level": "basic",
        "category": "person",
        "article_indefinite": "un",
        "article_definite": "le",
        "plural": "pères",
    },
    "mère": {
        "gender": "feminine",
        "meaning_ja": "母",
        "level": "basic",
        "category": "person",
        "article_indefinite": "une",
        "article_definite": "la",
        "plural": "mères",
    },
    "homme": {
        "gender": "masculine",
        "meaning_ja": "男性",
        "level": "basic",
        "category": "person",
        "article_indefinite": "un",
        "article_definite": "l'",
        "plural": "hommes",
    },
    "femme": {
        "gender": "feminine",
        "meaning_ja": "女性",
        "level": "basic",
        "category": "person",
        "article_indefinite": "une",
        "article_definite": "la",
        "plural": "femmes",
    },
    "frère": {
        "gender": "masculine",
        "meaning_ja": "兄弟",
        "level": "basic",
        "category": "person",
        "article_indefinite": "un",
        "article_definite": "le",
        "plural": "frères",
    },
    "sœur": {
        "gender": "feminine",
        "meaning_ja": "姉妹",
        "level": "basic",
        "category": "person",
        "article_indefinite": "une",
        "article_definite": "la",
        "plural": "sœurs",
    },
    # home
    "chambre": {
        "gender": "feminine",
        "meaning_ja": "部屋",
        "level": "basic",
        "category": "home",
        "article_indefinite": "une",
        "article_definite": "la",
        "plural": "chambres",
    },
    "lit": {
        "gender": "masculine",
        "meaning_ja": "ベッド",
        "level": "basic",
        "category": "home",
        "article_indefinite": "un",
        "article_definite": "le",
        "plural": "lits",
    },
    "chaise": {
        "gender": "feminine",
        "meaning_ja": "椅子",
        "level": "standard",
        "category": "home",
        "article_indefinite": "une",
        "article_definite": "la",
        "plural": "chaises",
    },
    "téléphone": {
        "gender": "masculine",
        "meaning_ja": "電話",
        "level": "basic",
        "category": "home",
        "article_indefinite": "un",
        "article_definite": "le",
        "plural": "téléphones",
    },
    # food
    "café": {
        "gender": "masculine",
        "meaning_ja": "コーヒー",
        "level": "basic",
        "category": "food",
        "article_indefinite": "un",
        "article_definite": "le",
        "plural": "cafés",
    },
    "thé": {
        "gender": "masculine",
        "meaning_ja": "紅茶",
        "level": "basic",
        "category": "food",
        "article_indefinite": "un",
        "article_definite": "le",
        "plural": "thés",
    },
    "lait": {
        "gender": "masculine",
        "meaning_ja": "牛乳",
        "level": "basic",
        "category": "food",
        "article_indefinite": "un",
        "article_definite": "le",
        "plural": "laits",
    },
    "pomme": {
        "gender": "feminine",
        "meaning_ja": "りんご",
        "level": "basic",
        "category": "food",
        "article_indefinite": "une",
        "article_definite": "la",
        "plural": "pommes",
    },
    "fromage": {
        "gender": "masculine",
        "meaning_ja": "チーズ",
        "level": "standard",
        "category": "food",
        "article_indefinite": "un",
        "article_definite": "le",
        "plural": "fromages",
    },
    "poisson": {
        "gender": "masculine",
        "meaning_ja": "魚",
        "level": "basic",
        "category": "food",
        "article_indefinite": "un",
        "article_definite": "le",
        "plural": "poissons",
    },
    # place
    "gare": {
        "gender": "feminine",
        "meaning_ja": "駅",
        "level": "basic",
        "category": "place",
        "article_indefinite": "une",
        "article_definite": "la",
        "plural": "gares",
    },
    "restaurant": {
        "gender": "masculine",
        "meaning_ja": "レストラン",
        "level": "basic",
        "category": "place",
        "article_indefinite": "un",
        "article_definite": "le",
        "plural": "restaurants",
    },
    "hôtel": {
        "gender": "masculine",
        "meaning_ja": "ホテル",
        "level": "standard",
        "category": "place",
        "article_indefinite": "un",
        "article_definite": "l'",
        "plural": "hôtels",
    },
    "parc": {
        "gender": "masculine",
        "meaning_ja": "公園",
        "level": "basic",
        "category": "place",
        "article_indefinite": "un",
        "article_definite": "le",
        "plural": "parcs",
    },
    "mer": {
        "gender": "feminine",
        "meaning_ja": "海",
        "level": "basic",
        "category": "place",
        "article_indefinite": "une",
        "article_definite": "la",
        "plural": "mers",
    },
    # time
    "jour": {
        "gender": "masculine",
        "meaning_ja": "日",
        "level": "basic",
        "category": "time",
        "article_indefinite": "un",
        "article_definite": "le",
        "plural": "jours",
    },
    "semaine": {
        "gender": "feminine",
        "meaning_ja": "週",
        "level": "basic",
        "category": "time",
        "article_indefinite": "une",
        "article_definite": "la",
        "plural": "semaines",
    },
    "heure": {
        "gender": "feminine",
        "meaning_ja": "時間・時刻",
        "level": "basic",
        "category": "time",
        "article_indefinite": "une",
        "article_definite": "l'",
        "plural": "heures",
    },
    "soir": {
        "gender": "masculine",
        "meaning_ja": "晩",
        "level": "basic",
        "category": "time",
        "article_indefinite": "un",
        "article_definite": "le",
        "plural": "soirs",
    },
    # school
    "classe": {
        "gender": "feminine",
        "meaning_ja": "クラス・教室",
        "level": "basic",
        "category": "school",
        "article_indefinite": "une",
        "article_definite": "la",
        "plural": "classes",
    },
    "professeur": {
        "gender": "masculine",
        "meaning_ja": "先生",
        "level": "basic",
        "category": "school",
        "article_indefinite": "un",
        "article_definite": "le",
        "plural": "professeurs",
    },
    "cahier": {
        "gender": "masculine",
        "meaning_ja": "ノート",
        "level": "basic",
        "category": "school",
        "article_indefinite": "un",
        "article_definite": "le",
        "plural": "cahiers",
    },
    "crayon": {
        "gender": "masculine",
        "meaning_ja": "鉛筆",
        "level": "standard",
        "category": "school",
        "article_indefinite": "un",
        "article_definite": "le",
        "plural": "crayons",
    },
    # abstract
    "idée": {
        "gender": "feminine",
        "meaning_ja": "考え",
        "level": "standard",
        "category": "abstract",
        "article_indefinite": "une",
        "article_definite": "l'",
        "plural": "idées",
    },
    "question": {
        "gender": "feminine",
        "meaning_ja": "質問",
        "level": "basic",
        "category": "abstract",
        "article_indefinite": "une",
        "article_definite": "la",
        "plural": "questions",
    },
    "travail": {
        "gender": "masculine",
        "meaning_ja": "仕事",
        "level": "basic",
        "category": "abstract",
        "article_indefinite": "un",
        "article_definite": "le",
        "plural": "travaux",
    },
    "nom": {
        "gender": "masculine",
        "meaning_ja": "名前",
        "level": "basic",
        "category": "abstract",
        "article_indefinite": "un",
        "article_definite": "le",
        "plural": "noms",
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


def validate_noun_data(noun: str, data: NounData) -> None:
    """Validate internal consistency of noun data fields."""
    expected_indef = "un" if data["gender"] == "masculine" else "une"
    if data["article_indefinite"] != expected_indef:
        raise ValueError(
            f"{noun}: article_indefinite '{data['article_indefinite']}' "
            f"inconsistent with gender '{data['gender']}'"
        )
    valid_definite = {"le", "la", "l'"}
    if data["article_definite"] not in valid_definite:
        raise ValueError(
            f"{noun}: article_definite '{data['article_definite']}' "
            f"must be one of {valid_definite}"
        )
    if not data["plural"]:
        raise ValueError(f"{noun}: plural must not be empty")
