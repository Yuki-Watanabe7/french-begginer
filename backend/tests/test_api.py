from fastapi.testclient import TestClient

from app.domain.conjugation import VERB_GROUPS
from app.main import app

client = TestClient(app)


def test_health():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_next_question():
    res = client.get("/api/questions/next")
    assert res.status_code == 200
    data = res.json()
    assert "verb" in data
    assert "tense" in data
    assert "pronoun" in data


def test_next_question_er_group():
    for _ in range(20):
        res = client.get("/api/questions/next?group=er")
        assert res.status_code == 200
        data = res.json()
        assert VERB_GROUPS.get(data["verb"]) == "er"


def test_next_question_ir_group():
    for _ in range(20):
        res = client.get("/api/questions/next?group=ir")
        assert res.status_code == 200
        data = res.json()
        assert VERB_GROUPS.get(data["verb"]) == "ir"


def test_next_question_irregular_group():
    for _ in range(20):
        res = client.get("/api/questions/next?group=irregular")
        assert res.status_code == 200
        data = res.json()
        assert VERB_GROUPS.get(data["verb"]) == "irregular"


def test_next_question_invalid_group():
    res = client.get("/api/questions/next?group=invalid")
    assert res.status_code == 422


def test_check_answer_correct():
    res = client.post(
        "/api/answers/check",
        json={"verb": "être", "tense": "présent", "pronoun": "je", "answer": "suis"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["correct"] is True
    assert data["expected"] == "suis"


def test_check_answer_incorrect():
    res = client.post(
        "/api/answers/check",
        json={"verb": "être", "tense": "présent", "pronoun": "je", "answer": "est"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["correct"] is False
    assert data["expected"] == "suis"


def test_check_answer_whitespace_trimmed():
    res = client.post(
        "/api/answers/check",
        json={
            "verb": "avoir",
            "tense": "présent",
            "pronoun": "nous",
            "answer": " avons ",
        },
    )
    assert res.status_code == 200
    assert res.json()["correct"] is True


def test_check_answer_er_verb():
    res = client.post(
        "/api/answers/check",
        json={"verb": "parler", "tense": "présent", "pronoun": "nous", "answer": "parlons"},
    )
    assert res.status_code == 200
    assert res.json()["correct"] is True


def test_check_answer_ir_verb():
    res = client.post(
        "/api/answers/check",
        json={"verb": "finir", "tense": "présent", "pronoun": "ils/elles", "answer": "finissent"},
    )
    assert res.status_code == 200
    assert res.json()["correct"] is True
