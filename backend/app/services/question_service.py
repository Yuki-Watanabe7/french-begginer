import random

from app.domain.conjugation import CONJUGATIONS, VERB_GROUPS, Question, VerbGroup


def get_next_question(group: VerbGroup = "all") -> Question:
    if group == "all":
        verbs = list(CONJUGATIONS.keys())
    else:
        verbs = [v for v, g in VERB_GROUPS.items() if g == group]

    verb = random.choice(verbs)
    tense = random.choice(list(CONJUGATIONS[verb].keys()))
    pronoun = random.choice(list(CONJUGATIONS[verb][tense].keys()))
    return Question(verb=verb, tense=tense, pronoun=pronoun)
