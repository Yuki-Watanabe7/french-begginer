import random

from app.domain.conjugation import CONJUGATIONS, Question


def get_next_question() -> Question:
    verb = random.choice(list(CONJUGATIONS.keys()))
    tense = random.choice(list(CONJUGATIONS[verb].keys()))
    pronoun = random.choice(list(CONJUGATIONS[verb][tense].keys()))
    return Question(verb=verb, tense=tense, pronoun=pronoun)
