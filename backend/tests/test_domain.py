import pytest

from app.domain.conjugation import AnswerCheck, check_answer, get_correct_answer

# --- get_correct_answer ---


def test_get_correct_answer_known_verb():
    assert get_correct_answer("parler", "présent", "je") == "parle"


def test_get_correct_answer_unknown_verb():
    assert get_correct_answer("inconnu", "présent", "je") is None


def test_get_correct_answer_unknown_tense():
    assert get_correct_answer("parler", "imparfait", "je") is None


def test_get_correct_answer_unknown_pronoun():
    assert get_correct_answer("parler", "présent", "on") is None


# --- check_answer: basic correct / incorrect ---


def test_check_answer_correct():
    req = AnswerCheck(verb="parler", tense="présent", pronoun="je", answer="parle")
    result = check_answer(req)
    assert result.correct is True
    assert result.expected == "parle"


def test_check_answer_incorrect():
    req = AnswerCheck(verb="parler", tense="présent", pronoun="je", answer="parles")
    result = check_answer(req)
    assert result.correct is False
    assert result.expected == "parle"


# --- check_answer: input normalisation ---


def test_check_answer_case_insensitive():
    req = AnswerCheck(verb="être", tense="présent", pronoun="je", answer="SUIS")
    result = check_answer(req)
    assert result.correct is True


def test_check_answer_strips_leading_trailing_whitespace():
    req = AnswerCheck(verb="avoir", tense="présent", pronoun="nous", answer="  avons  ")
    result = check_answer(req)
    assert result.correct is True


def test_check_answer_given_field_is_stripped():
    req = AnswerCheck(verb="aller", tense="présent", pronoun="je", answer="  vais  ")
    result = check_answer(req)
    assert result.given == "vais"


def test_check_answer_empty_string_is_incorrect():
    req = AnswerCheck(verb="parler", tense="présent", pronoun="je", answer="")
    result = check_answer(req)
    assert result.correct is False


# --- check_answer: accented characters ---


def test_check_answer_accented_answer_correct():
    req = AnswerCheck(verb="être", tense="présent", pronoun="vous", answer="êtes")
    result = check_answer(req)
    assert result.correct is True


def test_check_answer_missing_accent_is_incorrect():
    req = AnswerCheck(verb="être", tense="présent", pronoun="vous", answer="etes")
    result = check_answer(req)
    assert result.correct is False


def test_check_answer_accentuated_verb_correct():
    req = AnswerCheck(verb="écouter", tense="présent", pronoun="je", answer="écoute")
    result = check_answer(req)
    assert result.correct is True


# --- check_answer: unsupported input raises ValueError ---


def test_check_answer_unknown_verb_raises():
    req = AnswerCheck(verb="unknown", tense="présent", pronoun="je", answer="foo")
    with pytest.raises(ValueError):
        check_answer(req)


def test_check_answer_unknown_tense_raises():
    req = AnswerCheck(verb="parler", tense="imparfait", pronoun="je", answer="parlais")
    with pytest.raises(ValueError):
        check_answer(req)


def test_check_answer_unknown_pronoun_raises():
    req = AnswerCheck(verb="parler", tense="présent", pronoun="on", answer="parle")
    with pytest.raises(ValueError):
        check_answer(req)


# --- per-pronoun conjugation: representative verbs ---


@pytest.mark.parametrize(
    "pronoun,expected",
    [
        ("je", "parle"),
        ("tu", "parles"),
        ("il/elle", "parle"),
        ("nous", "parlons"),
        ("vous", "parlez"),
        ("ils/elles", "parlent"),
    ],
)
def test_parler_all_pronouns(pronoun: str, expected: str) -> None:
    req = AnswerCheck(verb="parler", tense="présent", pronoun=pronoun, answer=expected)
    assert check_answer(req).correct is True


@pytest.mark.parametrize(
    "pronoun,expected",
    [
        ("je", "suis"),
        ("tu", "es"),
        ("il/elle", "est"),
        ("nous", "sommes"),
        ("vous", "êtes"),
        ("ils/elles", "sont"),
    ],
)
def test_etre_all_pronouns(pronoun: str, expected: str) -> None:
    req = AnswerCheck(verb="être", tense="présent", pronoun=pronoun, answer=expected)
    assert check_answer(req).correct is True


@pytest.mark.parametrize(
    "pronoun,expected",
    [
        ("je", "ai"),
        ("tu", "as"),
        ("il/elle", "a"),
        ("nous", "avons"),
        ("vous", "avez"),
        ("ils/elles", "ont"),
    ],
)
def test_avoir_all_pronouns(pronoun: str, expected: str) -> None:
    req = AnswerCheck(verb="avoir", tense="présent", pronoun=pronoun, answer=expected)
    assert check_answer(req).correct is True


@pytest.mark.parametrize(
    "pronoun,expected",
    [
        ("je", "vais"),
        ("tu", "vas"),
        ("il/elle", "va"),
        ("nous", "allons"),
        ("vous", "allez"),
        ("ils/elles", "vont"),
    ],
)
def test_aller_all_pronouns(pronoun: str, expected: str) -> None:
    req = AnswerCheck(verb="aller", tense="présent", pronoun=pronoun, answer=expected)
    assert check_answer(req).correct is True


@pytest.mark.parametrize(
    "pronoun,expected",
    [
        ("je", "fais"),
        ("tu", "fais"),
        ("il/elle", "fait"),
        ("nous", "faisons"),
        ("vous", "faites"),
        ("ils/elles", "font"),
    ],
)
def test_faire_all_pronouns(pronoun: str, expected: str) -> None:
    req = AnswerCheck(verb="faire", tense="présent", pronoun=pronoun, answer=expected)
    assert check_answer(req).correct is True


@pytest.mark.parametrize(
    "pronoun,expected",
    [
        ("je", "finis"),
        ("tu", "finis"),
        ("il/elle", "finit"),
        ("nous", "finissons"),
        ("vous", "finissez"),
        ("ils/elles", "finissent"),
    ],
)
def test_finir_all_pronouns(pronoun: str, expected: str) -> None:
    req = AnswerCheck(verb="finir", tense="présent", pronoun=pronoun, answer=expected)
    assert check_answer(req).correct is True
