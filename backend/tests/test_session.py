import pytest
from fastapi.testclient import TestClient

from app.domain.conjugation import CONJUGATIONS, VERB_GROUPS
from app.domain.noun import NOUNS
from app.main import app
from app.services.noun_service import (
    get_noun_article_session_questions,
    get_noun_session_questions,
)
from app.services.question_service import get_session_questions

client = TestClient(app)


# --- get_session_questions (verb) ---


def test_get_session_questions_returns_requested_count():
    questions = get_session_questions(count=5)
    assert len(questions) == 5


def test_get_session_questions_no_duplicates_sufficient_candidates():
    # all group has 38+ verbs × 6 pronouns = 200+ candidates; 10 << total
    questions = get_session_questions(count=10)
    keys = [(q.verb, q.tense, q.pronoun) for q in questions]
    assert len(keys) == len(set(keys)), "Duplicate questions found in session"


def test_get_session_questions_insufficient_candidates_returns_all_without_duplicates():
    # ir group: 5 verbs × 6 pronouns = 30 candidates; request 1000 → get 30
    ir_verbs = {v for v, g in VERB_GROUPS.items() if g == "ir"}
    total_ir_candidates = sum(
        len(pronouns)
        for verb in ir_verbs
        for _tense, pronouns in CONJUGATIONS[verb].items()
    )
    questions = get_session_questions(count=1000, group="ir")
    assert len(questions) == total_ir_candidates
    keys = [(q.verb, q.tense, q.pronoun) for q in questions]
    assert len(keys) == len(set(keys)), (
        "Duplicate questions found when returning all candidates"
    )


def test_get_session_questions_exact_candidate_count_no_duplicates():
    ir_verbs = {v for v, g in VERB_GROUPS.items() if g == "ir"}
    total_ir_candidates = sum(
        len(pronouns)
        for verb in ir_verbs
        for _tense, pronouns in CONJUGATIONS[verb].items()
    )
    questions = get_session_questions(count=total_ir_candidates, group="ir")
    assert len(questions) == total_ir_candidates
    keys = [(q.verb, q.tense, q.pronoun) for q in questions]
    assert len(keys) == len(set(keys))


def test_get_session_questions_group_filter_respected():
    er_verbs = {v for v, g in VERB_GROUPS.items() if g == "er"}
    questions = get_session_questions(count=5, group="er")
    assert all(q.verb in er_verbs for q in questions)


def test_get_session_questions_no_candidates_raises_value_error():
    # ir + spelling_change パターンの組み合わせは存在しない
    with pytest.raises(ValueError):
        get_session_questions(count=5, group="ir", pattern="spelling_change")


# --- /api/questions/session endpoint ---


def test_session_questions_api_returns_list():
    res = client.get("/api/questions/session?count=5")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    assert len(data) == 5


def test_session_questions_api_no_duplicates():
    res = client.get("/api/questions/session?count=10")
    assert res.status_code == 200
    data = res.json()
    keys = [(q["verb"], q["tense"], q["pronoun"]) for q in data]
    assert len(keys) == len(set(keys)), "API returned duplicate questions"


def test_session_questions_api_group_filter():
    er_verbs = {v for v, g in VERB_GROUPS.items() if g == "er"}
    res = client.get("/api/questions/session?count=5&group=er")
    assert res.status_code == 200
    for q in res.json():
        assert q["verb"] in er_verbs


def test_session_questions_api_no_match_returns_404():
    res = client.get("/api/questions/session?count=5&group=ir&pattern=spelling_change")
    assert res.status_code == 404


def test_session_questions_api_invalid_group_returns_422():
    res = client.get("/api/questions/session?count=5&group=invalid")
    assert res.status_code == 422


# --- get_noun_session_questions ---


def test_get_noun_session_questions_no_duplicates():
    questions = get_noun_session_questions(count=10)
    nouns = [q.noun for q in questions]
    assert len(nouns) == len(set(nouns)), "Duplicate nouns found in session"


def test_get_noun_session_questions_insufficient_returns_all_without_duplicates():
    # Request more than total nouns → should return all without duplicates
    questions = get_noun_session_questions(count=10000)
    assert len(questions) == len(NOUNS)
    nouns = [q.noun for q in questions]
    assert len(nouns) == len(set(nouns))


def test_get_noun_session_questions_no_candidates_returns_empty():
    # challenge レベルの名詞は存在しない
    questions = get_noun_session_questions(count=5, level="challenge")
    assert questions == []


# --- get_noun_article_session_questions ---


def test_get_noun_article_session_questions_no_duplicates():
    questions = get_noun_article_session_questions(count=10)
    nouns = [q.noun for q in questions]
    assert len(nouns) == len(set(nouns)), "Duplicate nouns found in article session"


def test_get_noun_article_session_questions_insufficient_returns_all():
    questions = get_noun_article_session_questions(count=10000)
    assert len(questions) == len(NOUNS)
    nouns = [q.noun for q in questions]
    assert len(nouns) == len(set(nouns))


# --- /api/nouns/session endpoint ---


def test_noun_session_api_returns_list():
    res = client.get("/api/nouns/session?count=5")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    assert len(data) == 5


def test_noun_session_api_no_duplicates():
    res = client.get("/api/nouns/session?count=10")
    assert res.status_code == 200
    data = res.json()
    nouns = [q["noun"] for q in data]
    assert len(nouns) == len(set(nouns)), "API returned duplicate nouns"


def test_noun_session_api_no_match_returns_404():
    res = client.get("/api/nouns/session?count=5&level=challenge")
    assert res.status_code == 404


# --- /api/nouns/article/session endpoint ---


def test_noun_article_session_api_no_duplicates():
    res = client.get("/api/nouns/article/session?count=10")
    assert res.status_code == 200
    data = res.json()
    nouns = [q["noun"] for q in data]
    assert len(nouns) == len(set(nouns)), (
        "API returned duplicate nouns in article session"
    )


def test_noun_article_session_api_no_match_returns_404():
    res = client.get("/api/nouns/article/session?count=5&level=challenge")
    assert res.status_code == 404
