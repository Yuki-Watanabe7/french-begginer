import random

from app.domain.noun import NOUNS, NounGenderQuestion


def get_random_noun_question() -> NounGenderQuestion:
    if not NOUNS:
        raise ValueError("No nouns available")
    noun = random.choice(list(NOUNS.keys()))
    return NounGenderQuestion(noun=noun, meaning_ja=NOUNS[noun]["meaning_ja"])
