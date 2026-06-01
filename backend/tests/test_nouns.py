import pytest
from fastapi.testclient import TestClient

from app.domain.noun import (
    NOUNS,
    NounGenderAnswerCheck,
    check_noun_gender_answer,
    get_noun_gender,
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
