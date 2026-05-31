from typing import Literal, TypedDict

from pydantic import BaseModel

VerbGroup = Literal["all", "er", "ir", "irregular"]
VerbLevel = Literal["basic", "standard", "challenge"]
VerbPattern = Literal["regular", "stem_change", "spelling_change", "irregular"]

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
    "habiter": {"level": "basic", "pattern": "regular"},
    "regarder": {"level": "basic", "pattern": "regular"},
    "écouter": {"level": "basic", "pattern": "regular"},
    "travailler": {"level": "basic", "pattern": "regular"},
    "étudier": {"level": "standard", "pattern": "regular"},
    "chercher": {"level": "standard", "pattern": "regular"},
    "donner": {"level": "basic", "pattern": "regular"},
    "demander": {"level": "basic", "pattern": "regular"},
    "finir": {"level": "basic", "pattern": "regular"},
    "choisir": {"level": "standard", "pattern": "regular"},
    "réussir": {"level": "standard", "pattern": "regular"},
    "remplir": {"level": "standard", "pattern": "regular"},
    "grandir": {"level": "standard", "pattern": "regular"},
    "être": {"level": "basic", "pattern": "irregular"},
    "avoir": {"level": "basic", "pattern": "irregular"},
    "aller": {"level": "basic", "pattern": "irregular"},
    "faire": {"level": "basic", "pattern": "irregular"},
    "venir": {"level": "basic", "pattern": "irregular"},
    "prendre": {"level": "basic", "pattern": "irregular"},
    "pouvoir": {"level": "basic", "pattern": "irregular"},
    "vouloir": {"level": "basic", "pattern": "irregular"},
    "devoir": {"level": "basic", "pattern": "irregular"},
    "savoir": {"level": "basic", "pattern": "irregular"},
    "commencer": {"level": "standard", "pattern": "spelling_change"},
    "manger": {"level": "standard", "pattern": "spelling_change"},
    "acheter": {"level": "standard", "pattern": "stem_change"},
    "appeler": {"level": "standard", "pattern": "stem_change"},
    "préférer": {"level": "standard", "pattern": "stem_change"},
    "espérer": {"level": "standard", "pattern": "stem_change"},
    "envoyer": {"level": "standard", "pattern": "stem_change"},
    "dire": {"level": "basic", "pattern": "irregular"},
    "lire": {"level": "standard", "pattern": "irregular"},
    "écrire": {"level": "standard", "pattern": "irregular"},
    "voir": {"level": "basic", "pattern": "irregular"},
    "mettre": {"level": "basic", "pattern": "irregular"},
    "partir": {"level": "standard", "pattern": "irregular"},
    "sortir": {"level": "standard", "pattern": "irregular"},
    "dormir": {"level": "standard", "pattern": "irregular"},
    "attendre": {"level": "standard", "pattern": "irregular"},
    "répondre": {"level": "standard", "pattern": "irregular"},
}

VERB_GROUPS: dict[str, Literal["er", "ir", "irregular"]] = {
    "parler": "er",
    "aimer": "er",
    "habiter": "er",
    "regarder": "er",
    "écouter": "er",
    "travailler": "er",
    "étudier": "er",
    "chercher": "er",
    "donner": "er",
    "demander": "er",
    "finir": "ir",
    "choisir": "ir",
    "réussir": "ir",
    "remplir": "ir",
    "grandir": "ir",
    "être": "irregular",
    "avoir": "irregular",
    "aller": "irregular",
    "faire": "irregular",
    "venir": "irregular",
    "prendre": "irregular",
    "pouvoir": "irregular",
    "vouloir": "irregular",
    "devoir": "irregular",
    "savoir": "irregular",
    "commencer": "er",
    "manger": "er",
    "acheter": "er",
    "appeler": "er",
    "préférer": "er",
    "espérer": "er",
    "envoyer": "er",
    "dire": "irregular",
    "lire": "irregular",
    "écrire": "irregular",
    "voir": "irregular",
    "mettre": "irregular",
    "partir": "irregular",
    "sortir": "irregular",
    "dormir": "irregular",
    "attendre": "irregular",
    "répondre": "irregular",
}

CONJUGATIONS: dict[str, dict[str, dict[str, str]]] = {
    "habiter": {
        "présent": {
            "je": "habite",
            "tu": "habites",
            "il/elle": "habite",
            "nous": "habitons",
            "vous": "habitez",
            "ils/elles": "habitent",
        }
    },
    "regarder": {
        "présent": {
            "je": "regarde",
            "tu": "regardes",
            "il/elle": "regarde",
            "nous": "regardons",
            "vous": "regardez",
            "ils/elles": "regardent",
        }
    },
    "écouter": {
        "présent": {
            "je": "écoute",
            "tu": "écoutes",
            "il/elle": "écoute",
            "nous": "écoutons",
            "vous": "écoutez",
            "ils/elles": "écoutent",
        }
    },
    "étudier": {
        "présent": {
            "je": "étudie",
            "tu": "étudies",
            "il/elle": "étudie",
            "nous": "étudions",
            "vous": "étudiez",
            "ils/elles": "étudient",
        }
    },
    "chercher": {
        "présent": {
            "je": "cherche",
            "tu": "cherches",
            "il/elle": "cherche",
            "nous": "cherchons",
            "vous": "cherchez",
            "ils/elles": "cherchent",
        }
    },
    "donner": {
        "présent": {
            "je": "donne",
            "tu": "donnes",
            "il/elle": "donne",
            "nous": "donnons",
            "vous": "donnez",
            "ils/elles": "donnent",
        }
    },
    "demander": {
        "présent": {
            "je": "demande",
            "tu": "demandes",
            "il/elle": "demande",
            "nous": "demandons",
            "vous": "demandez",
            "ils/elles": "demandent",
        }
    },
    "réussir": {
        "présent": {
            "je": "réussis",
            "tu": "réussis",
            "il/elle": "réussit",
            "nous": "réussissons",
            "vous": "réussissez",
            "ils/elles": "réussissent",
        }
    },
    "remplir": {
        "présent": {
            "je": "remplis",
            "tu": "remplis",
            "il/elle": "remplit",
            "nous": "remplissons",
            "vous": "remplissez",
            "ils/elles": "remplissent",
        }
    },
    "grandir": {
        "présent": {
            "je": "grandis",
            "tu": "grandis",
            "il/elle": "grandit",
            "nous": "grandissons",
            "vous": "grandissez",
            "ils/elles": "grandissent",
        }
    },
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
    "venir": {
        "présent": {
            "je": "viens",
            "tu": "viens",
            "il/elle": "vient",
            "nous": "venons",
            "vous": "venez",
            "ils/elles": "viennent",
        }
    },
    "prendre": {
        "présent": {
            "je": "prends",
            "tu": "prends",
            "il/elle": "prend",
            "nous": "prenons",
            "vous": "prenez",
            "ils/elles": "prennent",
        }
    },
    "pouvoir": {
        "présent": {
            "je": "peux",
            "tu": "peux",
            "il/elle": "peut",
            "nous": "pouvons",
            "vous": "pouvez",
            "ils/elles": "peuvent",
        }
    },
    "vouloir": {
        "présent": {
            "je": "veux",
            "tu": "veux",
            "il/elle": "veut",
            "nous": "voulons",
            "vous": "voulez",
            "ils/elles": "veulent",
        }
    },
    "devoir": {
        "présent": {
            "je": "dois",
            "tu": "dois",
            "il/elle": "doit",
            "nous": "devons",
            "vous": "devez",
            "ils/elles": "doivent",
        }
    },
    "savoir": {
        "présent": {
            "je": "sais",
            "tu": "sais",
            "il/elle": "sait",
            "nous": "savons",
            "vous": "savez",
            "ils/elles": "savent",
        }
    },
    "commencer": {
        "présent": {
            "je": "commence",
            "tu": "commences",
            "il/elle": "commence",
            "nous": "commençons",
            "vous": "commencez",
            "ils/elles": "commencent",
        }
    },
    "manger": {
        "présent": {
            "je": "mange",
            "tu": "manges",
            "il/elle": "mange",
            "nous": "mangeons",
            "vous": "mangez",
            "ils/elles": "mangent",
        }
    },
    "acheter": {
        "présent": {
            "je": "achète",
            "tu": "achètes",
            "il/elle": "achète",
            "nous": "achetons",
            "vous": "achetez",
            "ils/elles": "achètent",
        }
    },
    "appeler": {
        "présent": {
            "je": "appelle",
            "tu": "appelles",
            "il/elle": "appelle",
            "nous": "appelons",
            "vous": "appelez",
            "ils/elles": "appellent",
        }
    },
    "préférer": {
        "présent": {
            "je": "préfère",
            "tu": "préfères",
            "il/elle": "préfère",
            "nous": "préférons",
            "vous": "préférez",
            "ils/elles": "préfèrent",
        }
    },
    "espérer": {
        "présent": {
            "je": "espère",
            "tu": "espères",
            "il/elle": "espère",
            "nous": "espérons",
            "vous": "espérez",
            "ils/elles": "espèrent",
        }
    },
    "envoyer": {
        "présent": {
            "je": "envoie",
            "tu": "envoies",
            "il/elle": "envoie",
            "nous": "envoyons",
            "vous": "envoyez",
            "ils/elles": "envoient",
        }
    },
    "dire": {
        "présent": {
            "je": "dis",
            "tu": "dis",
            "il/elle": "dit",
            "nous": "disons",
            "vous": "dites",
            "ils/elles": "disent",
        }
    },
    "lire": {
        "présent": {
            "je": "lis",
            "tu": "lis",
            "il/elle": "lit",
            "nous": "lisons",
            "vous": "lisez",
            "ils/elles": "lisent",
        }
    },
    "écrire": {
        "présent": {
            "je": "écris",
            "tu": "écris",
            "il/elle": "écrit",
            "nous": "écrivons",
            "vous": "écrivez",
            "ils/elles": "écrivent",
        }
    },
    "voir": {
        "présent": {
            "je": "vois",
            "tu": "vois",
            "il/elle": "voit",
            "nous": "voyons",
            "vous": "voyez",
            "ils/elles": "voient",
        }
    },
    "mettre": {
        "présent": {
            "je": "mets",
            "tu": "mets",
            "il/elle": "met",
            "nous": "mettons",
            "vous": "mettez",
            "ils/elles": "mettent",
        }
    },
    "partir": {
        "présent": {
            "je": "pars",
            "tu": "pars",
            "il/elle": "part",
            "nous": "partons",
            "vous": "partez",
            "ils/elles": "partent",
        }
    },
    "sortir": {
        "présent": {
            "je": "sors",
            "tu": "sors",
            "il/elle": "sort",
            "nous": "sortons",
            "vous": "sortez",
            "ils/elles": "sortent",
        }
    },
    "dormir": {
        "présent": {
            "je": "dors",
            "tu": "dors",
            "il/elle": "dort",
            "nous": "dormons",
            "vous": "dormez",
            "ils/elles": "dorment",
        }
    },
    "attendre": {
        "présent": {
            "je": "attends",
            "tu": "attends",
            "il/elle": "attend",
            "nous": "attendons",
            "vous": "attendez",
            "ils/elles": "attendent",
        }
    },
    "répondre": {
        "présent": {
            "je": "réponds",
            "tu": "réponds",
            "il/elle": "répond",
            "nous": "répondons",
            "vous": "répondez",
            "ils/elles": "répondent",
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
