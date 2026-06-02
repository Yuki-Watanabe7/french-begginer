"""
フランス語ドメインデータの構造的・内容的整合性を検証するテスト。

責務の分界:
  - このファイル: domainデータ単体の正しさを検証する（活用形のみ）
  - elision（j'écoute など）や表示文生成の検証は別の層の責務（表示層テスト）
  - golden fileとの照合は present_conjugations.json が参照データ

elision について:
  CONJUGATIONS に保存するのは「活用形のみ」。
  例: écouter の je → "écoute"（"j'écoute" ではない）
  主語付き表記（elision、アポストロフ）は表示層で処理する。
"""

import json
import unicodedata
from pathlib import Path

import pytest

from app.domain.conjugation import CONJUGATIONS, VERB_GROUPS, VERB_METADATA

EXPECTED_PRONOUNS = {"je", "tu", "il/elle", "nous", "vous", "ils/elles"}
GOLDEN_FILE = (
    Path(__file__).parent.parent
    / "app"
    / "domain"
    / "french_reference"
    / "present_conjugations.json"
)


# ---------------------------------------------------------------------------
# 1. キー整合性: VERB_METADATA / VERB_GROUPS / CONJUGATIONS が一致する
# ---------------------------------------------------------------------------


def test_all_conjugation_verbs_are_in_verb_groups():
    """CONJUGATIONS に登録された動詞がすべて VERB_GROUPS に存在する。"""
    missing = sorted(set(CONJUGATIONS) - set(VERB_GROUPS))
    assert not missing, (
        f"CONJUGATIONS にあるが VERB_GROUPS にない動詞: {missing}\n"
        "→ VERB_GROUPS に追加してください。"
    )


def test_all_conjugation_verbs_are_in_verb_metadata():
    """CONJUGATIONS に登録された動詞がすべて VERB_METADATA に存在する。"""
    missing = sorted(set(CONJUGATIONS) - set(VERB_METADATA))
    assert not missing, (
        f"CONJUGATIONS にあるが VERB_METADATA にない動詞: {missing}\n"
        "→ VERB_METADATA に level/pattern を追加してください。"
    )


def test_all_verb_groups_are_in_conjugations():
    """VERB_GROUPS に登録された動詞がすべて CONJUGATIONS に存在する。"""
    missing = sorted(set(VERB_GROUPS) - set(CONJUGATIONS))
    assert not missing, (
        f"VERB_GROUPS にあるが CONJUGATIONS にない動詞: {missing}\n"
        "→ CONJUGATIONS に活用形を追加してください。"
    )


def test_all_verb_metadata_are_in_conjugations():
    """VERB_METADATA に登録された動詞がすべて CONJUGATIONS に存在する。"""
    missing = sorted(set(VERB_METADATA) - set(CONJUGATIONS))
    assert not missing, (
        f"VERB_METADATA にあるが CONJUGATIONS にない動詞: {missing}\n"
        "→ CONJUGATIONS に活用形を追加してください。"
    )


# ---------------------------------------------------------------------------
# 2. 時制の存在確認: すべての動詞に présent が定義されている
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("verb", sorted(CONJUGATIONS.keys()))
def test_present_tense_exists(verb: str):
    """すべての動詞に présent 時制が定義されていること。"""
    assert "présent" in CONJUGATIONS[verb], (
        f"動詞 '{verb}' に 'présent' が定義されていません。\n"
        "→ CONJUGATIONS['{verb}']['présent'] を追加してください。"
    )


# ---------------------------------------------------------------------------
# 3. 人称の完全性: présent に6人称が過不足なく揃っている
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("verb", sorted(CONJUGATIONS.keys()))
def test_present_has_all_six_pronouns(verb: str):
    """présent に je/tu/il/elle/nous/vous/ils/elles の6人称が揃っていること。"""
    present = CONJUGATIONS[verb].get("présent", {})
    actual = set(present.keys())
    missing = EXPECTED_PRONOUNS - actual
    extra = actual - EXPECTED_PRONOUNS
    errors = []
    if missing:
        errors.append(f"  不足している人称: {sorted(missing)}")
    if extra:
        errors.append(f"  余分な人称: {sorted(extra)}")
    assert not errors, f"動詞 '{verb}' の présent 人称が不正:\n" + "\n".join(errors)


# ---------------------------------------------------------------------------
# 4. 値の品質: 空文字・前後空白・None がないこと
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("verb", sorted(CONJUGATIONS.keys()))
def test_conjugation_values_are_non_empty_strings(verb: str):
    """すべての活用形が空でない文字列であること（None・空文字・空白のみ禁止）。"""
    present = CONJUGATIONS[verb].get("présent", {})
    errors = []
    for pronoun, form in present.items():
        if not isinstance(form, str):
            errors.append(f"  {pronoun}: 値が文字列でない ({type(form).__name__})")
        elif not form or not form.strip():
            errors.append(f"  {pronoun}: 空文字または空白のみ (repr: {repr(form)})")
    assert not errors, f"動詞 '{verb}' の présent に不正な値があります:\n" + "\n".join(
        errors
    )


@pytest.mark.parametrize("verb", sorted(CONJUGATIONS.keys()))
def test_conjugation_values_have_no_surrounding_whitespace(verb: str):
    """活用形に前後の余分な空白がないこと。"""
    present = CONJUGATIONS[verb].get("présent", {})
    errors = []
    for pronoun, form in present.items():
        if isinstance(form, str) and form != form.strip():
            errors.append(f"  {pronoun}: 前後に空白あり (repr: {repr(form)})")
    assert not errors, (
        f"動詞 '{verb}' の présent 活用形に前後空白があります:\n" + "\n".join(errors)
    )


# ---------------------------------------------------------------------------
# 5. Unicode品質: NFCに正規化されていること・アクセント破損がないこと
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("verb", sorted(CONJUGATIONS.keys()))
def test_conjugation_values_are_nfc_normalized(verb: str):
    """活用形がUnicode NFC形式であること（合成済みアクセント文字を使用）。"""
    present = CONJUGATIONS[verb].get("présent", {})
    errors = []
    for pronoun, form in present.items():
        if isinstance(form, str):
            nfc_form = unicodedata.normalize("NFC", form)
            if form != nfc_form:
                errors.append(
                    f"  {pronoun}: NFC正規化前={repr(form)}, 後={repr(nfc_form)}"
                )
    assert not errors, (
        f"動詞 '{verb}' の présent にNFC未正規化の値があります:\n"
        + "\n".join(errors)
        + "\n→ unicodedata.normalize('NFC', value) で修正してください。"
    )


@pytest.mark.parametrize("verb", sorted(CONJUGATIONS.keys()))
def test_verb_key_is_nfc_normalized(verb: str):
    """動詞キー自体がNFC正規化されていること。"""
    nfc_verb = unicodedata.normalize("NFC", verb)
    assert verb == nfc_verb, (
        f"動詞キー '{verb}' がNFC未正規化です。\n→ NFC正規化後: {repr(nfc_verb)}"
    )


# ---------------------------------------------------------------------------
# 6. golden fileとの照合: レビュー済み参照データとの完全一致
# ---------------------------------------------------------------------------


def load_golden_file() -> dict:
    assert GOLDEN_FILE.exists(), (
        f"golden file が見つかりません: {GOLDEN_FILE}\n"
        "→ backend/app/domain/french_reference/present_conjugations.json"
        " を確認してください。"
    )
    with GOLDEN_FILE.open(encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def golden_data() -> dict:
    return load_golden_file()


def test_golden_file_is_loadable():
    """golden fileが正常に読み込めること（JSON形式・必須キー存在）。"""
    data = load_golden_file()
    assert "present" in data, "golden file に 'present' キーがありません。"
    assert isinstance(data["present"], dict), (
        "golden file の 'present' は辞書型である必要があります。"
    )


@pytest.mark.parametrize(
    "verb",
    sorted(
        json.load(open(GOLDEN_FILE, encoding="utf-8"))["present"].keys()
        if GOLDEN_FILE.exists()
        else []
    ),
)
def test_golden_file_verb_exists_in_conjugations(verb: str):
    """golden fileに登録された動詞がCONJUGATIONSに存在すること。"""
    assert verb in CONJUGATIONS, (
        f"golden fileの動詞 '{verb}' が CONJUGATIONS に存在しません。\n"
        "→ conjugation.py に活用形を追加するか、golden fileから削除してください。"
    )


def test_all_conjugation_verbs_have_golden_file_entry(golden_data: dict):
    """CONJUGATIONS の全動詞が golden file に登録されていること。"""
    golden_verbs = set(golden_data["present"].keys())
    conjugation_verbs = set(CONJUGATIONS.keys())
    missing = sorted(conjugation_verbs - golden_verbs)
    assert not missing, (
        f"CONJUGATIONS にあるが golden file にない動詞: {missing}\n"
        "→ present_conjugations.json に活用形を追加してください。"
    )


def test_golden_file_verb_count_matches_conjugations(golden_data: dict):
    """golden file の動詞数が CONJUGATIONS と完全に一致すること。"""
    golden_count = len(golden_data["present"])
    conjugation_count = len(CONJUGATIONS)
    assert golden_count == conjugation_count, (
        f"動詞数が一致しません: golden file={golden_count}, "
        f"CONJUGATIONS={conjugation_count}\n"
        "→ どちらかに動詞の過不足があります。"
    )


@pytest.mark.parametrize(
    "verb,pronoun,expected",
    [
        (verb, pronoun, form)
        for verb, conjugations in (
            json.load(open(GOLDEN_FILE, encoding="utf-8"))["present"].items()
            if GOLDEN_FILE.exists()
            else {}.items()
        )
        for pronoun, form in conjugations.items()
    ],
)
def test_conjugation_matches_golden_file(verb: str, pronoun: str, expected: str):
    """
    CONJUGATIONS の活用形がgolden fileの参照データと完全一致すること。

    不一致はフランス語として誤った活用形が混入している可能性を示す。
    golden fileを更新する場合はPR差分として明示的に確認すること。
    """
    actual = CONJUGATIONS.get(verb, {}).get("présent", {}).get(pronoun)
    assert actual is not None, (
        f"動詞 '{verb}' の présent/{pronoun} が CONJUGATIONS に定義されていません。"
    )
    assert actual == expected, (
        f"動詞 '{verb}' présent/{pronoun} の活用形が golden file と一致しません:\n"
        f"  CONJUGATIONS: {repr(actual)}\n"
        f"  golden file:  {repr(expected)}\n"
        "→ どちらが正しいか確認し、誤っている方を修正してください。\n"
        "  golden fileを変更した場合はPR上で差分が明示されます。"
    )
