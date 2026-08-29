"""vocabulary / expression 向け deterministic Exercise 生成（Issue #146）。

accepted かつ active な LearningItem の確定済み情報から、LLM 再呼び出しなしで
基本 Exercise を組み立てる。出題のたびに問題と正解を LLM に作らせない。

このモジュールが依存してよいのは Python 標準ライブラリ、Pydantic、
`domain.tutor`、`domain.exercise` のみ。DB / FastAPI / OpenAI には依存しない。

同じ (item, exercise_type, seed, exercise_version) からは同じ Exercise になる。
正解は `ExerciseAnswerKey` に閉じ、`to_public_exercise` には載せない。

```text
LearningItem (+ active pool, seed)
  -> eligibility / skip reason
  -> ExerciseSpec + ExerciseAnswerKey
```

Phase 3 初期対象:
  - meaning_recognition（FR → 日本語意味の choice）
  - ja_to_fr（日本語意味 → canonical_form の production）
  - expression_reconstruction（expression の語順再構成）

cloze / verb_conjugation adapter / HTTP API / Frontend / 回答送信は対象外。
fr_to_ja の日本語自由記述は meaning_ja との文字列一致で採点しない。
"""

from __future__ import annotations

import hashlib
import random
import unicodedata
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

from app.domain.exercise import (
    EXERCISE_VERSION,
    MIN_CHOICE_OPTIONS,
    ExerciseAnswerKey,
    ExerciseSkipReason,
    ExerciseSpec,
    PublicExercise,
    evaluate_exercise_eligibility,
    make_exercise_spec,
    to_public_exercise,
    tokenize_canonical_form,
)
from app.domain.tutor import ExerciseType, LearningItem, LearningItemType

MEANING_RECOGNITION_CHOICE_COUNT = 4
"""meaning_recognition の目標選択肢数。足りなければ MIN_CHOICE_OPTIONS まで減らす。"""

DEFAULT_GENERATION_SEED = "tutor-exercise"
"""未指定時の生成シード。テストでは必ず明示する。"""

SUPPORTED_ITEM_EXERCISE_TYPES: dict[LearningItemType, tuple[ExerciseType, ...]] = {
    "vocabulary": ("meaning_recognition", "ja_to_fr"),
    "expression": (
        "meaning_recognition",
        "ja_to_fr",
        "expression_reconstruction",
    ),
    "grammar": (),
    "conjugation": (),
}
"""item_type ごとに #146 で生成する形式。cloze は含めない。"""

GENERATED_EXERCISE_TYPES: frozenset[ExerciseType] = frozenset(
    exercise_type
    for types in SUPPORTED_ITEM_EXERCISE_TYPES.values()
    for exercise_type in types
)
"""このモジュールが実際に組み立てる ExerciseType。"""

_MEANING_RECOGNITION_PROMPT = (
    "次のフランス語の意味を選んでください。\n\n{canonical_form}"
)
_JA_TO_FR_PROMPT = "次の意味をフランス語で書いてください。\n\n{meaning_ja}"
_RECONSTRUCTION_PROMPT = "次の語を正しい順に並べて、表現を完成させてください。"


class GeneratedExercise(BaseModel):
    """生成結果の内部束。public DTO と answer key を分離する。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    spec: ExerciseSpec
    answer_key: ExerciseAnswerKey

    def to_public(self) -> PublicExercise:
        """Frontend 向け DTO。正解はコピーしない。"""
        return to_public_exercise(self.spec)


class ExerciseGenerationResult(BaseModel):
    """1つの ExerciseType の生成結果。失敗しても例外にせず skip reason を返す。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    exercise_type: ExerciseType
    eligible: bool
    exercise: GeneratedExercise | None = None
    skip_reason: ExerciseSkipReason | None = None
    detail: str | None = None

    @model_validator(mode="after")
    def _check_fields(self) -> ExerciseGenerationResult:
        if self.eligible:
            if self.exercise is None:
                raise ValueError("eligible な生成結果には exercise が必要")
            if self.skip_reason is not None or self.detail is not None:
                raise ValueError("eligible な生成結果に skip_reason / detail は不要")
        elif self.exercise is not None:
            raise ValueError("ineligible な生成結果に exercise は不要")
        elif self.skip_reason is None:
            raise ValueError("ineligible なら skip_reason が必要")
        return self


def generate_exercise(
    item: LearningItem,
    exercise_type: ExerciseType,
    *,
    pool: Sequence[LearningItem] = (),
    seed: str | int = DEFAULT_GENERATION_SEED,
) -> ExerciseGenerationResult:
    """1つの ExerciseType を deterministic に生成する。

    unsupported / 材料不足でも例外で全体を止めず、skip reason を返す。
    """
    eligibility = evaluate_exercise_eligibility(item, exercise_type)
    if not eligibility.eligible:
        return _skipped(
            exercise_type,
            eligibility.skip_reason or "unsupported_combination",
            eligibility.detail or "unsupported exercise",
        )
    if exercise_type not in SUPPORTED_ITEM_EXERCISE_TYPES[item.item_type]:
        return _skipped(
            exercise_type,
            "generation_not_implemented",
            f"{item.item_type} の {exercise_type} は "
            "vocabulary / expression 初期生成の対象外",
        )

    metadata = {
        "generation_seed": str(seed),
        "generation_version": EXERCISE_VERSION,
    }
    rng = _stable_rng(seed, item.id, exercise_type, EXERCISE_VERSION)

    if exercise_type == "meaning_recognition":
        return _generate_meaning_recognition(item, pool, rng, metadata)
    if exercise_type == "ja_to_fr":
        return _generate_ja_to_fr(item, metadata)
    if exercise_type == "expression_reconstruction":
        return _generate_expression_reconstruction(item, rng, metadata)
    return _skipped(
        exercise_type,
        "generation_not_implemented",
        f"{exercise_type} の prompt 組み立ては Phase 3 初期生成の対象外",
    )


def generate_supported_exercises(
    item: LearningItem,
    *,
    pool: Sequence[LearningItem] = (),
    seed: str | int = DEFAULT_GENERATION_SEED,
) -> tuple[ExerciseGenerationResult, ...]:
    """#146 対象の ExerciseType を item に対して順に生成する。"""
    types = SUPPORTED_ITEM_EXERCISE_TYPES[item.item_type]
    if not types:
        return ()
    return tuple(
        generate_exercise(item, exercise_type, pool=pool, seed=seed)
        for exercise_type in types
    )


def meaning_key(text: str) -> str:
    """意味の重複判定用キー。NFC と空白正規化だけ行い、別表現は別キーにする。"""
    normalized = unicodedata.normalize("NFC", text)
    return " ".join(normalized.split())


def unique_distractor_meanings(
    item: LearningItem,
    pool: Sequence[LearningItem],
) -> tuple[str, ...]:
    """active な他 Item から、正解と重複しない meaning_ja を安定順で返す。"""
    seen = {meaning_key(item.meaning_ja)}
    distractors: list[str] = []
    for other in sorted(pool, key=lambda row: row.id):
        if other.id == item.id:
            continue
        if other.status != "active":
            continue
        key = meaning_key(other.meaning_ja)
        if key in seen:
            continue
        seen.add(key)
        distractors.append(other.meaning_ja)
    return tuple(distractors)


def _generate_meaning_recognition(
    item: LearningItem,
    pool: Sequence[LearningItem],
    rng: random.Random,
    metadata: dict[str, Any],
) -> ExerciseGenerationResult:
    needed = MIN_CHOICE_OPTIONS - 1
    distractors = list(unique_distractor_meanings(item, pool))
    if len(distractors) < needed:
        return _skipped(
            "meaning_recognition",
            "insufficient_distractors",
            "meaning_recognition には正解以外のユニークな meaning_ja が必要",
        )
    take = min(len(distractors), MEANING_RECOGNITION_CHOICE_COUNT - 1)
    rng.shuffle(distractors)
    selected = distractors[:take]
    options = [item.meaning_ja, *selected]
    rng.shuffle(options)
    option_tuple = tuple(options)
    spec = make_exercise_spec(
        item,
        "meaning_recognition",
        prompt=_MEANING_RECOGNITION_PROMPT.format(canonical_form=item.canonical_form),
        options=option_tuple,
        metadata=metadata,
    )
    return _generated(
        spec,
        ExerciseAnswerKey(
            expected_answers=(item.meaning_ja,),
            correct_option_index=option_tuple.index(item.meaning_ja),
        ),
    )


def _generate_ja_to_fr(
    item: LearningItem,
    metadata: dict[str, Any],
) -> ExerciseGenerationResult:
    spec = make_exercise_spec(
        item,
        "ja_to_fr",
        prompt=_JA_TO_FR_PROMPT.format(meaning_ja=item.meaning_ja),
        metadata=metadata,
    )
    return _generated(
        spec,
        ExerciseAnswerKey(expected_answers=(item.canonical_form,)),
    )


def _generate_expression_reconstruction(
    item: LearningItem,
    rng: random.Random,
    metadata: dict[str, Any],
) -> ExerciseGenerationResult:
    tokens = tokenize_canonical_form(item.canonical_form)
    shuffled = _shuffle_tokens(tokens, rng)
    spec = make_exercise_spec(
        item,
        "expression_reconstruction",
        prompt=_RECONSTRUCTION_PROMPT,
        options=shuffled,
        metadata=metadata,
    )
    return _generated(
        spec,
        ExerciseAnswerKey(expected_answers=(" ".join(tokens),)),
    )


def _shuffle_tokens(tokens: tuple[str, ...], rng: random.Random) -> tuple[str, ...]:
    """可能なら元の語順と異なる提示順にする。同じ入力なら同じ結果。"""
    shuffled = list(tokens)
    original = list(tokens)
    if len(set(tokens)) <= 1:
        return tokens
    for _ in range(max(8, len(tokens) * 4)):
        rng.shuffle(shuffled)
        if shuffled != original:
            return tuple(shuffled)
    return tuple(shuffled)


def _stable_rng(
    seed: str | int,
    learning_item_id: str,
    exercise_type: ExerciseType,
    exercise_version: str,
) -> random.Random:
    material = "\0".join((str(seed), learning_item_id, exercise_type, exercise_version))
    digest = hashlib.sha256(material.encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _generated(
    spec: ExerciseSpec, answer_key: ExerciseAnswerKey
) -> ExerciseGenerationResult:
    return ExerciseGenerationResult(
        exercise_type=spec.exercise_type,
        eligible=True,
        exercise=GeneratedExercise(spec=spec, answer_key=answer_key),
    )


def _skipped(
    exercise_type: ExerciseType,
    reason: ExerciseSkipReason,
    detail: str,
) -> ExerciseGenerationResult:
    return ExerciseGenerationResult(
        exercise_type=exercise_type,
        eligible=False,
        skip_reason=reason,
        detail=detail,
    )
