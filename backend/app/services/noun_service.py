import random

from app.domain.noun import (
    NOUNS,
    NounArticleQuestion,
    NounCategory,
    NounGenderQuestion,
    NounLevel,
)


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
    return NounGenderQuestion(
        noun=noun,
        meaning_ja=candidates[noun]["meaning_ja"],
        article_indefinite=candidates[noun]["article_indefinite"],
    )


def get_random_noun_article_question(
    level: NounLevel | None = None,
    category: NounCategory | None = None,
) -> NounArticleQuestion | None:
    candidates = {
        noun: data
        for noun, data in NOUNS.items()
        if (level is None or data["level"] == level)
        and (category is None or data["category"] == category)
    }
    if not candidates:
        return None
    noun = random.choice(list(candidates.keys()))
    return NounArticleQuestion(noun=noun, meaning_ja=candidates[noun]["meaning_ja"])


def get_noun_session_questions(
    count: int,
    level: NounLevel | None = None,
    category: NounCategory | None = None,
) -> list[NounGenderQuestion]:
    """Return up to `count` unique noun gender questions for a session.

    If available candidates are fewer than `count`, all candidates are returned
    without duplication rather than repeating questions.
    """
    candidates = [
        NounGenderQuestion(
            noun=noun,
            meaning_ja=data["meaning_ja"],
            article_indefinite=data["article_indefinite"],
        )
        for noun, data in NOUNS.items()
        if (level is None or data["level"] == level)
        and (category is None or data["category"] == category)
    ]
    if not candidates:
        return []
    random.shuffle(candidates)
    return candidates[:count]


def get_noun_article_session_questions(
    count: int,
    level: NounLevel | None = None,
    category: NounCategory | None = None,
) -> list[NounArticleQuestion]:
    """Return up to `count` unique noun article questions for a session.

    If available candidates are fewer than `count`, all candidates are returned
    without duplication rather than repeating questions.
    """
    candidates = [
        NounArticleQuestion(noun=noun, meaning_ja=data["meaning_ja"])
        for noun, data in NOUNS.items()
        if (level is None or data["level"] == level)
        and (category is None or data["category"] == category)
    ]
    if not candidates:
        return []
    random.shuffle(candidates)
    return candidates[:count]
