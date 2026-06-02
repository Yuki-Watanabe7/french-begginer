"""
表示文生成（elision）のテスト。

このファイルの責務:
  - format_subject_verb() が je + 母音始まり活用形を j'... に変換すること
  - je + 子音始まり活用形が je ... になること
  - その他の主語が通常スペース結合になること
  - CONJUGATIONSが活用形のみを保持し主語付き表現を含まないこと（責務分界の確認）

domainデータ単体の検証（活用形の正しさ）は test_domain_validation.py に委譲する。
"""

import pytest

from app.domain.conjugation import CONJUGATIONS
from app.domain.display_format import format_subject_verb

# ---------------------------------------------------------------------------
# 1. je + 母音始まり活用形 → j'... (elision)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "verb,expected_display",
    [
        ("écouter", "j'écoute"),
        ("aimer", "j'aime"),
        ("avoir", "j'ai"),
        ("étudier", "j'étudie"),
    ],
)
def test_je_elision_vowel_start(verb: str, expected_display: str) -> None:
    """je + 母音始まりの活用形はelisionして j'... になること。"""
    conjugation = CONJUGATIONS[verb]["présent"]["je"]
    result = format_subject_verb("je", conjugation)
    assert result == expected_display, (
        f"動詞 '{verb}': "
        f"format_subject_verb('je', '{conjugation}') = '{result}'"
        f" ≠ '{expected_display}'\n"
        f"→ 画面に 'je {conjugation}' が表示される場合、elisionが未適用です。"
    )


# ---------------------------------------------------------------------------
# 2. je + 子音始まり活用形 → je ... (スペース結合、elisionしない)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "verb,expected_display",
    [
        ("être", "je suis"),
        ("aller", "je vais"),
        ("parler", "je parle"),
        ("finir", "je finis"),
    ],
)
def test_je_space_consonant_start(verb: str, expected_display: str) -> None:
    """je + 子音始まりの活用形はスペースで結合すること（elisionしない）。"""
    conjugation = CONJUGATIONS[verb]["présent"]["je"]
    result = format_subject_verb("je", conjugation)
    assert result == expected_display, (
        f"動詞 '{verb}': "
        f"format_subject_verb('je', '{conjugation}') = '{result}'"
        f" ≠ '{expected_display}'"
    )


# ---------------------------------------------------------------------------
# 3. je以外の主語 → 通常スペース結合（elisionしない）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pronoun,conjugation,expected_display",
    [
        ("tu", "parles", "tu parles"),
        ("il/elle", "parle", "il/elle parle"),
        ("nous", "parlons", "nous parlons"),
        ("vous", "parlez", "vous parlez"),
        ("ils/elles", "parlent", "ils/elles parlent"),
        # tu + 母音始まりの活用形でもelisionしない
        ("tu", "aimes", "tu aimes"),
    ],
)
def test_non_je_pronouns_space_join(
    pronoun: str, conjugation: str, expected_display: str
) -> None:
    """je以外の主語は通常スペースで活用形と結合すること。"""
    result = format_subject_verb(pronoun, conjugation)
    assert result == expected_display


# ---------------------------------------------------------------------------
# 4. CONJUGATIONSが活用形のみを保持していること（主語付き表現を含まない）
# ---------------------------------------------------------------------------


def test_conjugations_do_not_contain_elided_forms() -> None:
    """CONJUGATIONSの全活用形にアポストロフ（' または '）が含まれないこと。

    主語付き表現（j'écoute 等）はCONJUGATIONSに入れない責務分界を確認する。
    elisionは表示層（format_subject_verb）で処理する。
    """
    errors: list[str] = []
    for verb, tenses in CONJUGATIONS.items():
        for tense, pronouns in tenses.items():
            for pronoun, form in pronouns.items():
                # 直線アポストロフ（'）とTypographic apostrophe（'）の両方を検出
                if "'" in form or "’" in form:
                    errors.append(f"  {verb}/{tense}/{pronoun}: {repr(form)}")
    assert not errors, (
        "CONJUGATIONSにアポストロフを含む活用形が見つかりました"
        "（主語付き表現が混入しています）:\n"
        + "\n".join(errors)
        + "\n→ CONJUGATIONS には活用形のみを格納し、"
        "主語付き表記は format_subject_verb() で生成してください。"
    )
