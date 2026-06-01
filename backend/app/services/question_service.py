import random

from app.domain.conjugation import (
    CONJUGATIONS,
    VERB_GROUPS,
    VERB_METADATA,
    Question,
    VerbGroup,
    VerbLevel,
    VerbPattern,
)


def get_next_question(
    group: VerbGroup = "all",
    level: VerbLevel | None = None,
    pattern: VerbPattern | None = None,
) -> Question:
    if group == "all":
        verbs = list(CONJUGATIONS.keys())
    else:
        verbs = [v for v, g in VERB_GROUPS.items() if g == group]

    if level is not None:
        verbs = [v for v in verbs if VERB_METADATA.get(v, {}).get("level") == level]

    if pattern is not None:
        verbs = [v for v in verbs if VERB_METADATA.get(v, {}).get("pattern") == pattern]

    if not verbs:
        raise ValueError(
            f"No verbs found for filters: "
            f"group={group}, level={level}, pattern={pattern}"
        )

    verb = random.choice(verbs)
    tense = random.choice(list(CONJUGATIONS[verb].keys()))
    pronoun = random.choice(list(CONJUGATIONS[verb][tense].keys()))
    return Question(verb=verb, tense=tense, pronoun=pronoun)


def get_session_questions(
    count: int,
    group: VerbGroup = "all",
    level: VerbLevel | None = None,
    pattern: VerbPattern | None = None,
) -> list[Question]:
    """Return up to `count` unique (verb, tense, pronoun) questions for a session.

    If available candidates are fewer than `count`, all candidates are returned
    without duplication rather than repeating questions.
    """
    candidates: list[Question] = []
    for verb, tenses in CONJUGATIONS.items():
        if group != "all" and VERB_GROUPS.get(verb) != group:
            continue
        if level is not None and VERB_METADATA.get(verb, {}).get("level") != level:
            continue
        verb_pattern = VERB_METADATA.get(verb, {}).get("pattern")
        if pattern is not None and verb_pattern != pattern:
            continue
        for tense, pronouns in tenses.items():
            for pronoun in pronouns:
                candidates.append(Question(verb=verb, tense=tense, pronoun=pronoun))

    if not candidates:
        raise ValueError(
            f"No verbs found for filters: "
            f"group={group}, level={level}, pattern={pattern}"
        )

    random.shuffle(candidates)
    return candidates[:count]
