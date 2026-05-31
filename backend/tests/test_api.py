from fastapi.testclient import TestClient

from app.domain.conjugation import CONJUGATIONS, VERB_GROUPS, VERB_METADATA
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


def test_next_question_group_er():
    er_verbs = {v for v, g in VERB_GROUPS.items() if g == "er"}
    for _ in range(20):
        res = client.get("/api/questions/next?group=er")
        assert res.status_code == 200
        assert res.json()["verb"] in er_verbs


def test_next_question_group_ir():
    ir_verbs = {v for v, g in VERB_GROUPS.items() if g == "ir"}
    for _ in range(20):
        res = client.get("/api/questions/next?group=ir")
        assert res.status_code == 200
        assert res.json()["verb"] in ir_verbs


def test_next_question_group_irregular():
    irregular_verbs = {v for v, g in VERB_GROUPS.items() if g == "irregular"}
    for _ in range(20):
        res = client.get("/api/questions/next?group=irregular")
        assert res.status_code == 200
        assert res.json()["verb"] in irregular_verbs


def test_next_question_group_all():
    res = client.get("/api/questions/next?group=all")
    assert res.status_code == 200
    data = res.json()
    assert "verb" in data


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


def test_regarder_conjugation():
    cases = [
        ("je", "regarde"),
        ("tu", "regardes"),
        ("il/elle", "regarde"),
        ("nous", "regardons"),
        ("vous", "regardez"),
        ("ils/elles", "regardent"),
    ]
    for pronoun, expected in cases:
        res = client.post(
            "/api/answers/check",
            json={
                "verb": "regarder",
                "tense": "présent",
                "pronoun": pronoun,
                "answer": expected,
            },
        )
        assert res.status_code == 200
        assert res.json()["correct"] is True, f"regarder/{pronoun}: expected {expected}"


def test_grandir_conjugation():
    cases = [
        ("je", "grandis"),
        ("tu", "grandis"),
        ("il/elle", "grandit"),
        ("nous", "grandissons"),
        ("vous", "grandissez"),
        ("ils/elles", "grandissent"),
    ]
    for pronoun, expected in cases:
        res = client.post(
            "/api/answers/check",
            json={
                "verb": "grandir",
                "tense": "présent",
                "pronoun": pronoun,
                "answer": expected,
            },
        )
        assert res.status_code == 200
        assert res.json()["correct"] is True, f"grandir/{pronoun}: expected {expected}"


def test_venir_conjugation():
    cases = [
        ("je", "viens"),
        ("tu", "viens"),
        ("il/elle", "vient"),
        ("nous", "venons"),
        ("vous", "venez"),
        ("ils/elles", "viennent"),
    ]
    for pronoun, expected in cases:
        res = client.post(
            "/api/answers/check",
            json={
                "verb": "venir",
                "tense": "présent",
                "pronoun": pronoun,
                "answer": expected,
            },
        )
        assert res.status_code == 200
        assert res.json()["correct"] is True, f"venir/{pronoun}: expected {expected}"


def test_prendre_conjugation():
    cases = [
        ("je", "prends"),
        ("tu", "prends"),
        ("il/elle", "prend"),
        ("nous", "prenons"),
        ("vous", "prenez"),
        ("ils/elles", "prennent"),
    ]
    for pronoun, expected in cases:
        res = client.post(
            "/api/answers/check",
            json={
                "verb": "prendre",
                "tense": "présent",
                "pronoun": pronoun,
                "answer": expected,
            },
        )
        assert res.status_code == 200
        assert res.json()["correct"] is True, f"prendre/{pronoun}: expected {expected}"


def test_pouvoir_conjugation():
    cases = [
        ("je", "peux"),
        ("tu", "peux"),
        ("il/elle", "peut"),
        ("nous", "pouvons"),
        ("vous", "pouvez"),
        ("ils/elles", "peuvent"),
    ]
    for pronoun, expected in cases:
        res = client.post(
            "/api/answers/check",
            json={
                "verb": "pouvoir",
                "tense": "présent",
                "pronoun": pronoun,
                "answer": expected,
            },
        )
        assert res.status_code == 200
        assert res.json()["correct"] is True, f"pouvoir/{pronoun}: expected {expected}"


def test_vouloir_conjugation():
    cases = [
        ("je", "veux"),
        ("tu", "veux"),
        ("il/elle", "veut"),
        ("nous", "voulons"),
        ("vous", "voulez"),
        ("ils/elles", "veulent"),
    ]
    for pronoun, expected in cases:
        res = client.post(
            "/api/answers/check",
            json={
                "verb": "vouloir",
                "tense": "présent",
                "pronoun": pronoun,
                "answer": expected,
            },
        )
        assert res.status_code == 200
        assert res.json()["correct"] is True, f"vouloir/{pronoun}: expected {expected}"


def test_devoir_conjugation():
    cases = [
        ("je", "dois"),
        ("tu", "dois"),
        ("il/elle", "doit"),
        ("nous", "devons"),
        ("vous", "devez"),
        ("ils/elles", "doivent"),
    ]
    for pronoun, expected in cases:
        res = client.post(
            "/api/answers/check",
            json={
                "verb": "devoir",
                "tense": "présent",
                "pronoun": pronoun,
                "answer": expected,
            },
        )
        assert res.status_code == 200
        assert res.json()["correct"] is True, f"devoir/{pronoun}: expected {expected}"


def test_savoir_conjugation():
    cases = [
        ("je", "sais"),
        ("tu", "sais"),
        ("il/elle", "sait"),
        ("nous", "savons"),
        ("vous", "savez"),
        ("ils/elles", "savent"),
    ]
    for pronoun, expected in cases:
        res = client.post(
            "/api/answers/check",
            json={
                "verb": "savoir",
                "tense": "présent",
                "pronoun": pronoun,
                "answer": expected,
            },
        )
        assert res.status_code == 200
        assert res.json()["correct"] is True, f"savoir/{pronoun}: expected {expected}"


def test_commencer_conjugation():
    cases = [
        ("je", "commence"),
        ("nous", "commençons"),
        ("ils/elles", "commencent"),
    ]
    for pronoun, expected in cases:
        res = client.post(
            "/api/answers/check",
            json={
                "verb": "commencer",
                "tense": "présent",
                "pronoun": pronoun,
                "answer": expected,
            },
        )
        assert res.status_code == 200
        assert res.json()["correct"] is True, f"commencer/{pronoun}"


def test_manger_conjugation():
    cases = [
        ("je", "mange"),
        ("nous", "mangeons"),
        ("ils/elles", "mangent"),
    ]
    for pronoun, expected in cases:
        res = client.post(
            "/api/answers/check",
            json={
                "verb": "manger",
                "tense": "présent",
                "pronoun": pronoun,
                "answer": expected,
            },
        )
        assert res.status_code == 200
        assert res.json()["correct"] is True, f"manger/{pronoun}: expected {expected}"


def test_acheter_conjugation():
    cases = [
        ("je", "achète"),
        ("nous", "achetons"),
        ("ils/elles", "achètent"),
    ]
    for pronoun, expected in cases:
        res = client.post(
            "/api/answers/check",
            json={
                "verb": "acheter",
                "tense": "présent",
                "pronoun": pronoun,
                "answer": expected,
            },
        )
        assert res.status_code == 200
        assert res.json()["correct"] is True, f"acheter/{pronoun}: expected {expected}"


def test_appeler_conjugation():
    cases = [
        ("je", "appelle"),
        ("nous", "appelons"),
        ("ils/elles", "appellent"),
    ]
    for pronoun, expected in cases:
        res = client.post(
            "/api/answers/check",
            json={
                "verb": "appeler",
                "tense": "présent",
                "pronoun": pronoun,
                "answer": expected,
            },
        )
        assert res.status_code == 200
        assert res.json()["correct"] is True, f"appeler/{pronoun}: expected {expected}"


def test_preferer_conjugation():
    cases = [
        ("je", "préfère"),
        ("nous", "préférons"),
        ("ils/elles", "préfèrent"),
    ]
    for pronoun, expected in cases:
        res = client.post(
            "/api/answers/check",
            json={
                "verb": "préférer",
                "tense": "présent",
                "pronoun": pronoun,
                "answer": expected,
            },
        )
        assert res.status_code == 200
        assert res.json()["correct"] is True, f"préférer/{pronoun}: expected {expected}"


def test_esperer_conjugation():
    cases = [
        ("je", "espère"),
        ("nous", "espérons"),
        ("ils/elles", "espèrent"),
    ]
    for pronoun, expected in cases:
        res = client.post(
            "/api/answers/check",
            json={
                "verb": "espérer",
                "tense": "présent",
                "pronoun": pronoun,
                "answer": expected,
            },
        )
        assert res.status_code == 200
        assert res.json()["correct"] is True, f"espérer/{pronoun}: expected {expected}"


def test_envoyer_conjugation():
    cases = [
        ("je", "envoie"),
        ("nous", "envoyons"),
        ("ils/elles", "envoient"),
    ]
    for pronoun, expected in cases:
        res = client.post(
            "/api/answers/check",
            json={
                "verb": "envoyer",
                "tense": "présent",
                "pronoun": pronoun,
                "answer": expected,
            },
        )
        assert res.status_code == 200
        assert res.json()["correct"] is True, f"envoyer/{pronoun}: expected {expected}"


def test_check_answer_unknown_verb_returns_400():
    res = client.post(
        "/api/answers/check",
        json={"verb": "unknown", "tense": "présent", "pronoun": "je", "answer": "foo"},
    )
    assert res.status_code == 400


def test_check_answer_unknown_tense_returns_400():
    res = client.post(
        "/api/answers/check",
        json={
            "verb": "parler",
            "tense": "imparfait",
            "pronoun": "je",
            "answer": "parlais",
        },
    )
    assert res.status_code == 400


def test_check_answer_missing_required_field_returns_422():
    res = client.post(
        "/api/answers/check",
        json={"verb": "parler", "tense": "présent", "pronoun": "je"},
    )
    assert res.status_code == 422


def test_check_answer_case_insensitive():
    res = client.post(
        "/api/answers/check",
        json={"verb": "être", "tense": "présent", "pronoun": "je", "answer": "SUIS"},
    )
    assert res.status_code == 200
    assert res.json()["correct"] is True


def test_check_answer_empty_answer_is_incorrect():
    res = client.post(
        "/api/answers/check",
        json={"verb": "parler", "tense": "présent", "pronoun": "je", "answer": ""},
    )
    assert res.status_code == 200
    assert res.json()["correct"] is False


def test_check_answer_given_field_is_stripped():
    res = client.post(
        "/api/answers/check",
        json={
            "verb": "aller",
            "tense": "présent",
            "pronoun": "je",
            "answer": "  vais  ",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["correct"] is True
    assert data["given"] == "vais"


def test_parler_conjugation():
    cases = [
        ("je", "parle"),
        ("tu", "parles"),
        ("il/elle", "parle"),
        ("nous", "parlons"),
        ("vous", "parlez"),
        ("ils/elles", "parlent"),
    ]
    for pronoun, expected in cases:
        res = client.post(
            "/api/answers/check",
            json={
                "verb": "parler",
                "tense": "présent",
                "pronoun": pronoun,
                "answer": expected,
            },
        )
        assert res.status_code == 200
        assert res.json()["correct"] is True, f"parler/{pronoun}: expected {expected}"


def test_aimer_conjugation():
    cases = [
        ("je", "aime"),
        ("tu", "aimes"),
        ("il/elle", "aime"),
        ("nous", "aimons"),
        ("vous", "aimez"),
        ("ils/elles", "aiment"),
    ]
    for pronoun, expected in cases:
        res = client.post(
            "/api/answers/check",
            json={
                "verb": "aimer",
                "tense": "présent",
                "pronoun": pronoun,
                "answer": expected,
            },
        )
        assert res.status_code == 200
        assert res.json()["correct"] is True, f"aimer/{pronoun}: expected {expected}"


def test_etre_conjugation():
    cases = [
        ("je", "suis"),
        ("tu", "es"),
        ("il/elle", "est"),
        ("nous", "sommes"),
        ("vous", "êtes"),
        ("ils/elles", "sont"),
    ]
    for pronoun, expected in cases:
        res = client.post(
            "/api/answers/check",
            json={
                "verb": "être",
                "tense": "présent",
                "pronoun": pronoun,
                "answer": expected,
            },
        )
        assert res.status_code == 200
        assert res.json()["correct"] is True, f"être/{pronoun}: expected {expected}"


def test_avoir_conjugation():
    cases = [
        ("je", "ai"),
        ("tu", "as"),
        ("il/elle", "a"),
        ("nous", "avons"),
        ("vous", "avez"),
        ("ils/elles", "ont"),
    ]
    for pronoun, expected in cases:
        res = client.post(
            "/api/answers/check",
            json={
                "verb": "avoir",
                "tense": "présent",
                "pronoun": pronoun,
                "answer": expected,
            },
        )
        assert res.status_code == 200
        assert res.json()["correct"] is True, f"avoir/{pronoun}: expected {expected}"


def test_aller_conjugation():
    cases = [
        ("je", "vais"),
        ("tu", "vas"),
        ("il/elle", "va"),
        ("nous", "allons"),
        ("vous", "allez"),
        ("ils/elles", "vont"),
    ]
    for pronoun, expected in cases:
        res = client.post(
            "/api/answers/check",
            json={
                "verb": "aller",
                "tense": "présent",
                "pronoun": pronoun,
                "answer": expected,
            },
        )
        assert res.status_code == 200
        assert res.json()["correct"] is True, f"aller/{pronoun}: expected {expected}"


def test_faire_conjugation():
    cases = [
        ("je", "fais"),
        ("tu", "fais"),
        ("il/elle", "fait"),
        ("nous", "faisons"),
        ("vous", "faites"),
        ("ils/elles", "font"),
    ]
    for pronoun, expected in cases:
        res = client.post(
            "/api/answers/check",
            json={
                "verb": "faire",
                "tense": "présent",
                "pronoun": pronoun,
                "answer": expected,
            },
        )
        assert res.status_code == 200
        assert res.json()["correct"] is True, f"faire/{pronoun}: expected {expected}"


def test_finir_conjugation():
    cases = [
        ("je", "finis"),
        ("tu", "finis"),
        ("il/elle", "finit"),
        ("nous", "finissons"),
        ("vous", "finissez"),
        ("ils/elles", "finissent"),
    ]
    for pronoun, expected in cases:
        res = client.post(
            "/api/answers/check",
            json={
                "verb": "finir",
                "tense": "présent",
                "pronoun": pronoun,
                "answer": expected,
            },
        )
        assert res.status_code == 200
        assert res.json()["correct"] is True, f"finir/{pronoun}: expected {expected}"


def test_choisir_conjugation():
    cases = [
        ("je", "choisis"),
        ("tu", "choisis"),
        ("il/elle", "choisit"),
        ("nous", "choisissons"),
        ("vous", "choisissez"),
        ("ils/elles", "choisissent"),
    ]
    for pronoun, expected in cases:
        res = client.post(
            "/api/answers/check",
            json={
                "verb": "choisir",
                "tense": "présent",
                "pronoun": pronoun,
                "answer": expected,
            },
        )
        assert res.status_code == 200
        assert res.json()["correct"] is True, f"choisir/{pronoun}: expected {expected}"


def test_verb_groups_conjugations_match():
    assert set(VERB_GROUPS) == set(CONJUGATIONS)


def test_verb_metadata_keys_match_groups():
    assert set(VERB_METADATA) == set(VERB_GROUPS)


def test_verb_metadata_levels_valid():
    valid = {"basic", "standard", "challenge"}
    for verb, meta in VERB_METADATA.items():
        assert meta["level"] in valid, f"{verb}: invalid level"


def test_verb_metadata_patterns_valid():
    valid = {
        "regular",
        "stem_change",
        "spelling_change",
        "irregular",
    }
    for verb, meta in VERB_METADATA.items():
        assert meta["pattern"] in valid, f"{verb}: invalid pattern"
