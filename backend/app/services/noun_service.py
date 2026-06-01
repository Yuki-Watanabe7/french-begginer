import random

from app.domain.noun import NOUNS, NounCategory, NounGenderQuestion, NounLevel


def get_random_noun_question(
    level: NounLevel | None = None,
    category: NounCategory | None = None,
) -> NounGenderQuestion | None:
    candidates = {
        noun: data
        for noun, data in NOUNS.items()
        if (level is None or data["level"] == level)
        and (category is None or data["category"] == category)
    }
    if not candidates:
        return None
    noun = random.choice(list(candidates.keys()))
    return NounGenderQuestion(noun=noun, meaning_ja=candidates[noun]["meaning_ja"])
