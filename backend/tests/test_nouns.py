import pytest
from fastapi.testclient import TestClient

from app.domain.noun import (
    NOUNS,
    NounArticleAnswerCheck,
    NounGenderAnswerCheck,
    check_noun_article_answer,
    check_noun_gender_answer,
    get_noun_article_answer,
    get_noun_gender,
    normalize_article_answer,
    validate_noun_data,
)
from app.main import app

client = TestClient(app)


# --- API tests ---


def test_next_noun_question():
    res = client.get("/api/nouns/next")
    assert res.status_code == 200
    data = res.json()
    assert "noun" in data
    assert data["noun"] in NOUNS


def test_next_noun_question_returns_meaning():
    res = client.get("/api/nouns/next")
    assert res.status_code == 200
    data = res.json()
    assert "meaning_ja" in data
    assert isinstance(data["meaning_ja"], str)


def test_next_noun_question_repeated_calls():
    for _ in range(20):
        res = client.get("/api/nouns/next")
        assert res.status_code == 200
        assert res.json()["noun"] in NOUNS


def test_check_noun_answer_correct_masculine():
    res = client.post(
        "/api/nouns/check",
        json={"noun": "livre", "answer": "masculine"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["correct"] is True
    assert data["expected"] == "masculine"
    assert data["given"] == "masculine"


def test_check_noun_answer_correct_feminine():
    res = client.post(
        "/api/nouns/check",
        json={"noun": "maison", "answer": "feminine"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["correct"] is True
    assert data["expected"] == "feminine"
    assert data["given"] == "feminine"


def test_check_noun_answer_incorrect():
    res = client.post(
        "/api/nouns/check",
        json={"noun": "livre", "answer": "feminine"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["correct"] is False
    assert data["expected"] == "masculine"
    assert data["given"] == "feminine"


def test_check_noun_answer_unknown_noun_returns_400():
    res = client.post(
        "/api/nouns/check",
        json={"noun": "unknown_word_xyz", "answer": "masculine"},
    )
    assert res.status_code == 400


def test_check_noun_answer_invalid_gender_returns_422():
    res = client.post(
        "/api/nouns/check",
        json={"noun": "livre", "answer": "neuter"},
    )
    assert res.status_code == 422


def test_check_noun_answer_missing_field_returns_422():
    res = client.post(
        "/api/nouns/check",
        json={"noun": "livre"},
    )
    assert res.status_code == 422


# --- data integrity tests ---


def test_all_nouns_have_valid_gender():
    valid = {"masculine", "feminine"}
    for noun, data in NOUNS.items():
        assert data["gender"] in valid, f"{noun}: invalid gender"


def test_all_nouns_have_meaning():
    for noun, data in NOUNS.items():
        assert "meaning_ja" in data, f"{noun}: missing meaning_ja"
        assert isinstance(data["meaning_ja"], str), f"{noun}: meaning_ja should be str"
        assert data["meaning_ja"] != "", f"{noun}: meaning_ja should not be empty"


def test_noun_count():
    assert 55 <= len(NOUNS) <= 70, f"Should have 55–70 nouns, got {len(NOUNS)}"


def test_all_nouns_have_level():
    for noun, data in NOUNS.items():
        assert "level" in data, f"{noun}: missing level"
        assert isinstance(data["level"], str), f"{noun}: level should be str"


def test_all_nouns_have_category():
    for noun, data in NOUNS.items():
        assert "category" in data, f"{noun}: missing category"
        assert isinstance(data["category"], str), f"{noun}: category should be str"


def test_all_nouns_level_valid():
    valid_levels: set[str] = {"basic", "standard", "challenge"}
    for noun, data in NOUNS.items():
        assert data["level"] in valid_levels, f"{noun}: invalid level '{data['level']}'"


def test_all_nouns_category_valid():
    valid_categories: set[str] = {
        "person",
        "home",
        "food",
        "place",
        "time",
        "school",
        "nature",
        "abstract",
    }
    for noun, data in NOUNS.items():
        assert data["category"] in valid_categories, (
            f"{noun}: invalid category '{data['category']}'"
        )


# --- domain unit tests ---


def test_get_noun_gender_masculine():
    assert get_noun_gender("livre") == "masculine"


def test_get_noun_gender_feminine():
    assert get_noun_gender("maison") == "feminine"


def test_get_noun_gender_unknown():
    assert get_noun_gender("unknown_xyz") is None


def test_check_noun_gender_answer_correct():
    req = NounGenderAnswerCheck(noun="livre", answer="masculine")
    result = check_noun_gender_answer(req)
    assert result.correct is True
    assert result.expected == "masculine"
    assert result.given == "masculine"


def test_check_noun_gender_answer_incorrect():
    req = NounGenderAnswerCheck(noun="livre", answer="feminine")
    result = check_noun_gender_answer(req)
    assert result.correct is False
    assert result.expected == "masculine"
    assert result.given == "feminine"


def test_check_noun_gender_answer_unknown_raises():
    req = NounGenderAnswerCheck(noun="unknown_xyz", answer="masculine")
    with pytest.raises(ValueError, match="Unknown noun"):
        check_noun_gender_answer(req)


def test_check_feminine_correct():
    req = NounGenderAnswerCheck(noun="maison", answer="feminine")
    result = check_noun_gender_answer(req)
    assert result.correct is True


def test_check_feminine_incorrect():
    req = NounGenderAnswerCheck(noun="maison", answer="masculine")
    result = check_noun_gender_answer(req)
    assert result.correct is False
    assert result.expected == "feminine"


# --- tests for expanded vocabulary ---


@pytest.mark.parametrize(
    "noun,expected_gender",
    [
        ("père", "masculine"),
        ("mère", "feminine"),
        ("homme", "masculine"),
        ("femme", "feminine"),
        ("frère", "masculine"),
        ("sœur", "feminine"),
        ("chambre", "feminine"),
        ("lit", "masculine"),
        ("café", "masculine"),
        ("pomme", "feminine"),
        ("gare", "feminine"),
        ("restaurant", "masculine"),
        ("mer", "feminine"),
        ("jour", "masculine"),
        ("semaine", "feminine"),
        ("heure", "feminine"),
        ("classe", "feminine"),
        ("professeur", "masculine"),
        ("idée", "feminine"),
        ("travail", "masculine"),
        ("fils", "masculine"),
        ("fille", "feminine"),
        ("oiseau", "masculine"),
        ("lapin", "masculine"),
        ("montagne", "feminine"),
        ("vin", "masculine"),
    ],
)
def test_check_expanded_nouns_via_api(noun: str, expected_gender: str):
    res = client.post(
        "/api/nouns/check",
        json={"noun": noun, "answer": expected_gender},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["correct"] is True, f"{noun}: expected {expected_gender}"
    assert data["expected"] == expected_gender


def test_basic_level_count_not_too_low():
    basic_nouns = [n for n, d in NOUNS.items() if d["level"] == "basic"]
    assert len(basic_nouns) >= 35, f"Too few basic nouns: {len(basic_nouns)}"


def test_standard_level_count_not_too_low():
    standard_nouns = [n for n, d in NOUNS.items() if d["level"] == "standard"]
    assert len(standard_nouns) >= 5, f"Too few standard nouns: {len(standard_nouns)}"


def test_all_main_categories_have_multiple_nouns():
    from collections import Counter

    counts = Counter(d["category"] for d in NOUNS.values())
    for cat in ("person", "home", "food", "place", "time", "school", "abstract"):
        assert counts[cat] >= 2, f"Category '{cat}' has only {counts[cat]} noun(s)"


# --- filter API tests ---


def test_next_noun_question_filter_level_basic():
    res = client.get("/api/nouns/next?level=basic")
    assert res.status_code == 200
    noun = res.json()["noun"]
    assert NOUNS[noun]["level"] == "basic"


def test_next_noun_question_filter_level_standard():
    res = client.get("/api/nouns/next?level=standard")
    assert res.status_code == 200
    noun = res.json()["noun"]
    assert NOUNS[noun]["level"] == "standard"


def test_next_noun_question_filter_category_food():
    res = client.get("/api/nouns/next?category=food")
    assert res.status_code == 200
    noun = res.json()["noun"]
    assert NOUNS[noun]["category"] == "food"


def test_next_noun_question_filter_level_and_category():
    res = client.get("/api/nouns/next?level=basic&category=home")
    assert res.status_code == 200
    data = res.json()
    noun = data["noun"]
    assert NOUNS[noun]["level"] == "basic"
    assert NOUNS[noun]["category"] == "home"


def test_next_noun_question_filter_no_params_returns_any():
    res = client.get("/api/nouns/next")
    assert res.status_code == 200
    assert res.json()["noun"] in NOUNS


def test_next_noun_question_filter_no_match_returns_404():
    # No challenge-level nouns exist in current data
    res = client.get("/api/nouns/next?level=challenge")
    assert res.status_code == 404


def test_next_noun_question_invalid_level_returns_422():
    res = client.get("/api/nouns/next?level=unknown")
    assert res.status_code == 422


def test_next_noun_question_invalid_category_returns_422():
    res = client.get("/api/nouns/next?category=invalid_cat")
    assert res.status_code == 422


def test_next_noun_question_filter_repeated_basic_food():
    for _ in range(10):
        res = client.get("/api/nouns/next?level=basic&category=food")
        assert res.status_code == 200
        noun = res.json()["noun"]
        assert NOUNS[noun]["level"] == "basic"
        assert NOUNS[noun]["category"] == "food"


# --- new field data integrity tests ---


def test_all_nouns_have_article_indefinite():
    for noun, data in NOUNS.items():
        assert "article_indefinite" in data, f"{noun}: missing article_indefinite"
        assert data["article_indefinite"] in ("un", "une"), (
            f"{noun}: invalid article_indefinite '{data['article_indefinite']}'"
        )


def test_all_nouns_have_article_definite():
    for noun, data in NOUNS.items():
        assert "article_definite" in data, f"{noun}: missing article_definite"
        assert data["article_definite"] in ("le", "la", "l'"), (
            f"{noun}: invalid article_definite '{data['article_definite']}'"
        )


def test_all_nouns_have_plural():
    for noun, data in NOUNS.items():
        assert "plural" in data, f"{noun}: missing plural"
        assert isinstance(data["plural"], str), f"{noun}: plural should be str"
        assert data["plural"] != "", f"{noun}: plural should not be empty"


def test_article_indefinite_matches_gender():
    for noun, data in NOUNS.items():
        expected = "un" if data["gender"] == "masculine" else "une"
        assert data["article_indefinite"] == expected, (
            f"{noun}: article_indefinite '{data['article_indefinite']}' "
            f"does not match gender '{data['gender']}'"
        )


def test_validate_noun_data_passes_all_nouns():
    for noun, data in NOUNS.items():
        validate_noun_data(noun, data)


def test_validate_noun_data_catches_wrong_article_indefinite():
    with pytest.raises(ValueError, match="article_indefinite"):
        validate_noun_data(
            "livre",
            {
                "gender": "masculine",
                "meaning_ja": "本",
                "level": "basic",
                "category": "school",
                "article_indefinite": "une",
                "article_definite": "le",
                "plural": "livres",
            },
        )


def test_nature_category_has_sufficient_nouns():
    nature_nouns = [n for n, d in NOUNS.items() if d["category"] == "nature"]
    assert len(nature_nouns) >= 6, f"Too few nature nouns: {len(nature_nouns)}"


def test_no_empty_french_noun_keys():
    for noun in NOUNS:
        assert noun != "", "NOUNS dict has an empty string key"
        assert noun.strip() == noun, (
            f"Noun key has leading/trailing whitespace: '{noun}'"
        )


def test_validate_noun_data_catches_empty_plural():
    with pytest.raises(ValueError, match="plural"):
        validate_noun_data(
            "livre",
            {
                "gender": "masculine",
                "meaning_ja": "本",
                "level": "basic",
                "category": "school",
                "article_indefinite": "un",
                "article_definite": "le",
                "plural": "",
            },
        )


def test_validate_noun_data_catches_invalid_article_definite():
    with pytest.raises(ValueError, match="article_definite"):
        validate_noun_data(
            "livre",
            {
                "gender": "masculine",
                "meaning_ja": "本",
                "level": "basic",
                "category": "school",
                "article_indefinite": "un",
                "article_definite": "les",
                "plural": "livres",
            },
        )


# --- vowel elision tests ---

_FRENCH_VOWELS = set("aeiouàâäéèêëîïôùûüœæ")

# Nouns in NOUNS that start with a mute h (require l' elision).
# Aspirate-h nouns would use le/la; all current h-nouns in the data are mute.
_MUTE_H_NOUNS = {"homme", "hôtel", "heure"}


def _starts_with_vowel_letter(word: str) -> bool:
    return bool(word) and word[0].lower() in _FRENCH_VOWELS


def test_vowel_starting_nouns_use_elision():
    """Vowel-starting nouns must use article_definite=\"l'\"."""
    for noun, data in NOUNS.items():
        if _starts_with_vowel_letter(noun):
            assert data["article_definite"] == "l'", (
                f"{noun}: starts with '{noun[0]}' but "
                f"article_definite='{data['article_definite']}' (expected \"l'\")"
            )


def test_mute_h_nouns_use_elision():
    """Known mute-h nouns must use article_definite=\"l'\"."""
    for noun in _MUTE_H_NOUNS:
        assert noun in NOUNS, f"Expected mute-h noun '{noun}' in NOUNS"
        art = NOUNS[noun]["article_definite"]
        assert art == "l'", (
            f"{noun}: mute-h noun but article_definite='{art}' (expected \"l'\")"
        )


def test_le_la_nouns_do_not_start_with_vowel():
    """Nouns with article_definite='le'/'la' must not start with a vowel."""
    for noun, data in NOUNS.items():
        if data["article_definite"] in ("le", "la"):
            assert not _starts_with_vowel_letter(noun), (
                f"{noun}: article_definite='{data['article_definite']}' "
                f"but starts with vowel '{noun[0]}' (should be \"l'\")"
            )


@pytest.mark.parametrize(
    "noun,expected_indef,expected_def,expected_plural",
    [
        ("livre", "un", "le", "livres"),
        ("maison", "une", "la", "maisons"),
        ("arbre", "un", "l'", "arbres"),
        ("eau", "une", "l'", "eaux"),
        ("ami", "un", "l'", "amis"),
        ("école", "une", "l'", "écoles"),
        ("homme", "un", "l'", "hommes"),
        ("hôtel", "un", "l'", "hôtels"),
        ("heure", "une", "l'", "heures"),
        ("idée", "une", "l'", "idées"),
        ("bureau", "un", "le", "bureaux"),
        ("travail", "un", "le", "travaux"),
        ("fils", "un", "le", "fils"),
        ("fille", "une", "la", "filles"),
        ("oiseau", "un", "l'", "oiseaux"),
        ("lapin", "un", "le", "lapins"),
        ("montagne", "une", "la", "montagnes"),
        ("vin", "un", "le", "vins"),
    ],
)
def test_specific_noun_new_fields(
    noun: str,
    expected_indef: str,
    expected_def: str,
    expected_plural: str,
):
    data = NOUNS[noun]
    assert data["article_indefinite"] == expected_indef, (
        f"{noun}: expected article_indefinite '{expected_indef}'"
    )
    assert data["article_definite"] == expected_def, (
        f"{noun}: expected article_definite '{expected_def}'"
    )
    assert data["plural"] == expected_plural, (
        f"{noun}: expected plural '{expected_plural}'"
    )


# --- noun article domain tests ---


def test_normalize_article_answer_strips_whitespace():
    assert normalize_article_answer("  un livre  ") == "un livre"


def test_normalize_article_answer_collapses_spaces():
    assert normalize_article_answer("un  livre") == "un livre"


def test_normalize_article_answer_lowercases():
    assert normalize_article_answer("Un Livre") == "un livre"


def test_normalize_article_answer_combined():
    assert normalize_article_answer("  UNE   MAISON  ") == "une maison"


def test_get_noun_article_answer_masculine():
    assert get_noun_article_answer("livre") == "un livre"


def test_get_noun_article_answer_feminine():
    assert get_noun_article_answer("maison") == "une maison"


def test_get_noun_article_answer_unknown():
    assert get_noun_article_answer("unknown_xyz") is None


def test_check_noun_article_answer_correct_masculine():
    req = NounArticleAnswerCheck(noun="livre", answer="un livre")
    result = check_noun_article_answer(req)
    assert result.correct is True
    assert result.expected == "un livre"
    assert result.given == "un livre"


def test_check_noun_article_answer_correct_feminine():
    req = NounArticleAnswerCheck(noun="maison", answer="une maison")
    result = check_noun_article_answer(req)
    assert result.correct is True
    assert result.expected == "une maison"


def test_check_noun_article_answer_wrong_article():
    req = NounArticleAnswerCheck(noun="maison", answer="un maison")
    result = check_noun_article_answer(req)
    assert result.correct is False
    assert result.expected == "une maison"
    assert result.given == "un maison"


def test_check_noun_article_answer_wrong_noun():
    req = NounArticleAnswerCheck(noun="livre", answer="un chat")
    result = check_noun_article_answer(req)
    assert result.correct is False
    assert result.expected == "un livre"


def test_check_noun_article_answer_case_insensitive():
    req = NounArticleAnswerCheck(noun="livre", answer="UN LIVRE")
    result = check_noun_article_answer(req)
    assert result.correct is True


def test_check_noun_article_answer_leading_trailing_spaces():
    req = NounArticleAnswerCheck(noun="maison", answer="  une maison  ")
    result = check_noun_article_answer(req)
    assert result.correct is True


def test_check_noun_article_answer_extra_spaces():
    req = NounArticleAnswerCheck(noun="livre", answer="un  livre")
    result = check_noun_article_answer(req)
    assert result.correct is True


def test_check_noun_article_answer_unknown_raises():
    req = NounArticleAnswerCheck(noun="unknown_xyz", answer="un unknown_xyz")
    with pytest.raises(ValueError, match="Unknown noun"):
        check_noun_article_answer(req)


# --- noun article API tests ---


def test_next_noun_article_question():
    res = client.get("/api/nouns/article/next")
    assert res.status_code == 200
    data = res.json()
    assert "noun" in data
    assert data["noun"] in NOUNS


def test_next_noun_article_question_returns_meaning():
    res = client.get("/api/nouns/article/next")
    assert res.status_code == 200
    data = res.json()
    assert "meaning_ja" in data
    assert isinstance(data["meaning_ja"], str)


def test_next_noun_article_question_repeated_calls():
    for _ in range(20):
        res = client.get("/api/nouns/article/next")
        assert res.status_code == 200
        assert res.json()["noun"] in NOUNS


def test_next_noun_article_question_filter_level_basic():
    res = client.get("/api/nouns/article/next?level=basic")
    assert res.status_code == 200
    noun = res.json()["noun"]
    assert NOUNS[noun]["level"] == "basic"


def test_next_noun_article_question_filter_category_food():
    res = client.get("/api/nouns/article/next?category=food")
    assert res.status_code == 200
    noun = res.json()["noun"]
    assert NOUNS[noun]["category"] == "food"


def test_next_noun_article_question_no_match_returns_404():
    res = client.get("/api/nouns/article/next?level=challenge")
    assert res.status_code == 404


def test_next_noun_article_question_invalid_level_returns_422():
    res = client.get("/api/nouns/article/next?level=unknown")
    assert res.status_code == 422


def test_check_noun_article_correct_masculine():
    res = client.post(
        "/api/nouns/article/check",
        json={"noun": "livre", "answer": "un livre"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["correct"] is True
    assert data["expected"] == "un livre"
    assert data["given"] == "un livre"


def test_check_noun_article_correct_feminine():
    res = client.post(
        "/api/nouns/article/check",
        json={"noun": "maison", "answer": "une maison"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["correct"] is True
    assert data["expected"] == "une maison"


def test_check_noun_article_wrong_article():
    res = client.post(
        "/api/nouns/article/check",
        json={"noun": "maison", "answer": "un maison"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["correct"] is False
    assert data["expected"] == "une maison"
    assert data["given"] == "un maison"


def test_check_noun_article_wrong_noun():
    res = client.post(
        "/api/nouns/article/check",
        json={"noun": "livre", "answer": "un stylo"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["correct"] is False
    assert data["expected"] == "un livre"


def test_check_noun_article_case_insensitive():
    res = client.post(
        "/api/nouns/article/check",
        json={"noun": "livre", "answer": "UN LIVRE"},
    )
    assert res.status_code == 200
    assert res.json()["correct"] is True


def test_check_noun_article_leading_trailing_spaces():
    res = client.post(
        "/api/nouns/article/check",
        json={"noun": "maison", "answer": "  une maison  "},
    )
    assert res.status_code == 200
    assert res.json()["correct"] is True


def test_check_noun_article_extra_spaces():
    res = client.post(
        "/api/nouns/article/check",
        json={"noun": "livre", "answer": "un  livre"},
    )
    assert res.status_code == 200
    assert res.json()["correct"] is True


def test_check_noun_article_unknown_noun_returns_400():
    res = client.post(
        "/api/nouns/article/check",
        json={"noun": "unknown_word_xyz", "answer": "un unknown_word_xyz"},
    )
    assert res.status_code == 400


def test_check_noun_article_missing_field_returns_422():
    res = client.post(
        "/api/nouns/article/check",
        json={"noun": "livre"},
    )
    assert res.status_code == 422


@pytest.mark.parametrize(
    "noun,expected_answer",
    [
        ("livre", "un livre"),
        ("maison", "une maison"),
        ("chat", "un chat"),
        ("fleur", "une fleur"),
        ("arbre", "un arbre"),
        ("eau", "une eau"),
    ],
)
def test_check_noun_article_via_api_parametrized(noun: str, expected_answer: str):
    res = client.post(
        "/api/nouns/article/check",
        json={"noun": noun, "answer": expected_answer},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["correct"] is True, f"{noun}: expected correct answer"
    assert data["expected"] == expected_answer
