"""Tutor Exercise の server-side 採点（Issue #149 / Phase 3）。

Frontend から expected_answer を受け取って採点しない。
同じ (item, exercise_type, exercise_version) から再構成した
`GeneratedExercise` の `ExerciseAnswerKey` だけを正解根拠にする。

このモジュールが依存してよいのは Python 標準ライブラリ、Pydantic、
`domain.tutor`、`domain.exercise`、`domain.exercise_generation` のみ。
DB / FastAPI / OpenAI には依存しない。

```text
GeneratedExercise + learner answer
  -> response_kind 別 evaluation
  -> correct / incorrect
```

正規化はここへ一元化する。

- Unicode NFC
- 前後空白除去と連続空白の圧縮
- 印刷用 apostrophe（U+2019 等）を ASCII `'` へ揃える
- 大文字小文字は casefold で無視する

**accent は除去しない。** `été` と `ete` は別回答である。
日本語自由記述の意味判定（fr_to_ja）は扱わない。
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from app.domain.exercise import tokenize_canonical_form
from app.domain.exercise_generation import GeneratedExercise, meaning_key

# フランス語で同一の省略記号として扱う apostrophe 類。
# ASCII APOSTROPHE (U+0027) へ寄せる。アクセント記号そのものは対象外。
_APOSTROPHE_TRANSLATION = str.maketrans(
    {
        "\u2019": "'",  # RIGHT SINGLE QUOTATION MARK
        "\u2018": "'",  # LEFT SINGLE QUOTATION MARK
        "\u02bc": "'",  # MODIFIER LETTER APOSTROPHE
        "\uff07": "'",  # FULLWIDTH APOSTROPHE
    }
)


class MalformedExerciseAnswerError(ValueError):
    """response_kind と回答の形が合わない、または空である。"""


class ExerciseEvaluation(BaseModel):
    """採点結果。correct_answer は正規化前の内部正解を返す。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    correct: bool
    correct_answer: str = Field(min_length=1)
    given: str | tuple[str, ...]


def normalize_french_production(text: str) -> str:
    """フランス語 production 回答の正規化。

    手順（順序固定）:
      1. Unicode NFC
      2. typographic apostrophe を ASCII `'` へ置換
      3. 前後空白除去と連続 Unicode 空白の圧縮
      4. casefold（大文字小文字を無視）

    NFD 分解して combining mark を落とす処理は行わない。
    そのため `été` と `ete` は一致しない。
    """
    normalized = unicodedata.normalize("NFC", text)
    normalized = normalized.translate(_APOSTROPHE_TRANSLATION)
    collapsed = " ".join(normalized.split())
    return collapsed.casefold()


def normalize_choice_answer(text: str) -> str:
    """choice の安定識別子比較。option 文字列の NFC と空白だけ揃える。

    表示順や option index には依存しない。アクセントも除去しない。
    """
    return meaning_key(text)


def evaluate_exercise_answer(
    generated: GeneratedExercise,
    answer: str | Sequence[str],
) -> ExerciseEvaluation:
    """再構成済み Exercise に対して回答を判定する。

    正解は `generated.answer_key` からのみ取る。Client 入力の expected は見ない。
    空・型不一致は `MalformedExerciseAnswerError`。誤答は incorrect であり、
    例外にはしない。
    """
    kind = generated.spec.response_kind
    correct_answer = generated.answer_key.expected_answers[0]
    if kind == "choice":
        given = _require_text_answer(answer)
        correct = _matches_choice(given, generated.answer_key.expected_answers)
        return ExerciseEvaluation(
            correct=correct, correct_answer=correct_answer, given=given
        )
    if kind == "text":
        given = _require_text_answer(answer)
        correct = _matches_french_text(given, generated.answer_key.expected_answers)
        return ExerciseEvaluation(
            correct=correct, correct_answer=correct_answer, given=given
        )
    if kind == "reconstruction":
        tokens = _require_reconstruction_tokens(answer)
        correct = _matches_reconstruction(
            tokens, generated.answer_key.expected_answers[0]
        )
        return ExerciseEvaluation(
            correct=correct, correct_answer=correct_answer, given=tokens
        )
    raise MalformedExerciseAnswerError(f"未対応の response_kind: {kind}")


def _require_text_answer(answer: str | Sequence[str]) -> str:
    if not isinstance(answer, str):
        raise MalformedExerciseAnswerError(
            "choice / text の回答は文字列である必要がある"
        )
    if " ".join(answer.split()) == "":
        raise MalformedExerciseAnswerError("回答が空、または whitespace のみ")
    return answer


def _require_reconstruction_tokens(
    answer: str | Sequence[str],
) -> tuple[str, ...]:
    if isinstance(answer, str):
        tokens = tokenize_canonical_form(answer)
    else:
        if any(not isinstance(token, str) for token in answer):
            raise MalformedExerciseAnswerError(
                "reconstruction の各 token は文字列である必要がある"
            )
        tokens = tuple(answer)
        if any(not token.strip() for token in tokens):
            raise MalformedExerciseAnswerError(
                "reconstruction の token に空文字は使えない"
            )
    if len(tokens) == 0:
        raise MalformedExerciseAnswerError("reconstruction の回答が空")
    return tokens


def _matches_choice(given: str, expected_answers: tuple[str, ...]) -> bool:
    given_key = normalize_choice_answer(given)
    if given_key == "":
        raise MalformedExerciseAnswerError("回答が空、または whitespace のみ")
    return any(
        given_key == normalize_choice_answer(expected) for expected in expected_answers
    )


def _matches_french_text(given: str, expected_answers: tuple[str, ...]) -> bool:
    given_key = normalize_french_production(given)
    if given_key == "":
        raise MalformedExerciseAnswerError("回答が空、または whitespace のみ")
    return any(
        given_key == normalize_french_production(expected)
        for expected in expected_answers
    )


def _matches_reconstruction(tokens: tuple[str, ...], expected: str) -> bool:
    expected_tokens = tokenize_canonical_form(expected)
    given_norm = tuple(normalize_french_production(token) for token in tokens)
    expected_norm = tuple(
        normalize_french_production(token) for token in expected_tokens
    )
    return given_norm == expected_norm
