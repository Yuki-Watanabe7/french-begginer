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
