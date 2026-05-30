import random

from app.domain.conjugation import CONJUGATIONS, VERB_GROUPS, Question, VerbGroup


def get_next_question(group: VerbGroup | None = None) -> Question:
    if group is not None:
        verbs = [v for v in CONJUGATIONS if VERB_GROUPS.get(v) == group]
    else:
        verbs = list(CONJUGATIONS.keys())
    verb = random.choice(verbs)
    tense = random.choice(list(CONJUGATIONS[verb].keys()))
    pronoun = random.choice(list(CONJUGATIONS[verb][tense].keys()))
    return Question(verb=verb, tense=tense, pronoun=pronoun)
