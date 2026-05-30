from fastapi.testclient import TestClient

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
