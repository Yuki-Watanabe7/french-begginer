"""LearningItem → Exercise の共通契約（Issue #145 / Phase 3）。

Tutor layer が「この LearningItem にどの Exercise を出せるか」を判断し、
既存 / 新規の出題実装へ委譲するための薄い境界。実際の問題文生成・HTTP API・
Frontend はこのモジュールの責務ではない。

このモジュールが依存してよいのは Python 標準ライブラリ、Pydantic、
`domain.tutor`、`domain.conjugation_adapter` のみ。
既存動詞データ（`conjugation.CONJUGATIONS`）への接続は adapter が担う。
DB / FastAPI / OpenAI には依存しない。

Exercise 自体は永続化しない。同じ (item, exercise_type, exercise_version)
から同じ Exercise を再構成できることを優先する。

```text
LearningItem
  -> eligibility / policy
  -> ExerciseSpec
  -> renderer / evaluator（後続Issue）
  -> LearningEvent（exercise_version を metadata で追跡）
```
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Set
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.conjugation_adapter import evaluate_conjugation_adapter
from app.domain.tutor import (
    ExerciseType,
    LearningItem,
    LearningItemType,
    SkillDirection,
)

EXERCISE_VERSION = "exercise-v1"
"""現行の Exercise 生成ロジック版。規則を変えるときは bump する。"""

ResponseKind = Literal["choice", "text", "reconstruction"]
"""学習者の応答形式。choice=選択肢 / text=文字列入力 / reconstruction=再構成。"""

ExerciseSkipReason = Literal[
    "unsupported_combination",
    "missing_source_evidence",
    "source_not_found",
    "evidence_span_out_of_range",
    "evidence_span_empty",
    "context_unavailable",
    "unknown_conjugation_lemma",
    "missing_conjugation_tense",
    "unsupported_conjugation_tense",
    "unsupported_conjugation_mood",
    "requires_semantic_grading",
    "existing_quiz_only",
    "insufficient_expression_tokens",
    "inactive_item",
    "insufficient_distractors",
    "generation_not_implemented",
]

MIN_CHOICE_OPTIONS = 2
"""choice 形式に必要な選択肢の下限。1件では選択にならない。"""

MIN_RECONSTRUCTION_TOKENS = 2
"""expression_reconstruction に必要な canonical_form のトークン数下限。"""

_WHITESPACE_RE = re.compile(r"\s+")

# 公開 DTO に混ぜてはいけない内部判定フィールド。
_INTERNAL_ANSWER_FIELDS = frozenset(
    {
        "expected",
        "expected_answer",
        "expected_answers",
        "answer",
        "answer_key",
        "correct",
        "correct_option",
        "correct_index",
        "correct_option_index",
        "acceptable",
        "acceptable_answers",
        "grader",
        "evaluation",
    }
)

EXERCISE_SKILL_DIRECTIONS: dict[ExerciseType, SkillDirection] = {
    "meaning_recognition": "recognition",
    "fr_to_ja": "recognition",
    "ja_to_fr": "production",
    "cloze": "production",
    "expression_reconstruction": "production",
    "verb_conjugation": "production",
    "noun_gender": "recognition",
    "noun_article": "production",
}
"""ExerciseType → SkillDirection。曖昧な形式もここに一元化する。"""

EXERCISE_RESPONSE_KINDS: dict[ExerciseType, ResponseKind] = {
    "meaning_recognition": "choice",
    "fr_to_ja": "text",
    "ja_to_fr": "text",
    "cloze": "text",
    "expression_reconstruction": "reconstruction",
    "verb_conjugation": "text",
    "noun_gender": "choice",
    "noun_article": "choice",
}

# item_type ごとに Phase 3 で「候補になりうる」Exercise。
# metadata 不足や既存クイズ専用の型は、この集合に入れても後段で skip する。
_PHASE3_CANDIDATE_EXERCISES: dict[LearningItemType, frozenset[ExerciseType]] = {
    "vocabulary": frozenset({"meaning_recognition", "ja_to_fr", "cloze"}),
    "expression": frozenset(
        {
            "meaning_recognition",
            "ja_to_fr",
            "expression_reconstruction",
            "cloze",
        }
    ),
    "grammar": frozenset({"meaning_recognition", "cloze"}),
    "conjugation": frozenset({"cloze", "verb_conjugation"}),
}

# 既存クイズ layer 専用。Tutor の LearningItem から新規生成しない。
_EXISTING_QUIZ_EXERCISE_TYPES: frozenset[ExerciseType] = frozenset(
    {"noun_gender", "noun_article"}
)

# 日本語自由記述の意味判定が必要になるため、Phase 3 では生成しない。
_SEMANTIC_GRADING_EXERCISE_TYPES: frozenset[ExerciseType] = frozenset({"fr_to_ja"})

EXERCISE_TYPES: tuple[ExerciseType, ...] = get_args(ExerciseType)


class ExerciseSpec(BaseModel):
    """出題の共通契約。正解・内部判定情報は持たない。

    renderer / evaluator へ委譲する入力。Frontend へ返す場合は
    `to_public_exercise` を通し、metadata を露出しない。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    learning_item_id: str = Field(min_length=1)
    exercise_type: ExerciseType
    skill_direction: SkillDirection
    prompt: str = Field(min_length=1)
    response_kind: ResponseKind
    options: tuple[str, ...] | None = None
    source_context: str | None = Field(default=None, min_length=1)
    exercise_version: str = Field(default=EXERCISE_VERSION, min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_contract(self) -> ExerciseSpec:
        expected_direction = skill_direction_for(self.exercise_type)
        if self.skill_direction != expected_direction:
            raise ValueError(
                f"{self.exercise_type} の skill_direction は "
                f"{expected_direction} である必要がある: {self.skill_direction}"
            )
        expected_kind = response_kind_for(self.exercise_type)
        if self.response_kind != expected_kind:
            raise ValueError(
                f"{self.exercise_type} の response_kind は "
                f"{expected_kind} である必要がある: {self.response_kind}"
            )
        if self.response_kind == "choice":
            if self.options is None or len(self.options) < MIN_CHOICE_OPTIONS:
                raise ValueError(
                    f"choice には {MIN_CHOICE_OPTIONS} 件以上の options が必要"
                )
            if any(not option.strip() for option in self.options):
                raise ValueError("choice の options に空文字は使えない")
        elif self.response_kind == "reconstruction":
            if self.options is not None:
                if len(self.options) < MIN_RECONSTRUCTION_TOKENS:
                    raise ValueError(
                        f"reconstruction には {MIN_RECONSTRUCTION_TOKENS} 件以上の "
                        "options（提示トークン）が必要"
                    )
                if any(not option.strip() for option in self.options):
                    raise ValueError("reconstruction の options に空文字は使えない")
        elif self.options is not None:
            raise ValueError(
                f"{self.response_kind} に options は不要: {self.exercise_type}"
            )
        leaked = _INTERNAL_ANSWER_FIELDS.intersection(self.metadata)
        if leaked:
            raise ValueError(
                f"ExerciseSpec.metadata に正解情報を載せない: {sorted(leaked)}"
            )
        return self


class PublicExercise(BaseModel):
    """Frontend 向け DTO。正解・判定内部情報・内部 metadata を持たない。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    learning_item_id: str = Field(min_length=1)
    exercise_type: ExerciseType
    skill_direction: SkillDirection
    prompt: str = Field(min_length=1)
    response_kind: ResponseKind
    options: tuple[str, ...] | None = None
    source_context: str | None = None
    exercise_version: str = Field(min_length=1)


class ExerciseAnswerKey(BaseModel):
    """evaluator 内部用の正解情報。PublicExercise に混ぜない。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    expected_answers: tuple[str, ...] = Field(min_length=1)
    correct_option_index: int | None = Field(default=None, ge=0)


class ExerciseEligibility(BaseModel):
    """1つの ExerciseType が当該 LearningItem に出せるか。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    exercise_type: ExerciseType
    skill_direction: SkillDirection
    eligible: bool
    skip_reason: ExerciseSkipReason | None = None
    detail: str | None = None

    @model_validator(mode="after")
    def _check_skip_fields(self) -> ExerciseEligibility:
        if self.eligible:
            if self.skip_reason is not None or self.detail is not None:
                raise ValueError("eligible な判定に skip_reason / detail は不要")
        elif self.skip_reason is None:
            raise ValueError("ineligible なら skip_reason が必要")
        return self


class UnsupportedExerciseError(ValueError):
    """unsupported な item_type × ExerciseType を生成しようとした。"""

    def __init__(self, reason: ExerciseSkipReason, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


def skill_direction_for(exercise_type: ExerciseType) -> SkillDirection:
    """ExerciseType に対する SkillDirection。常に一意。"""
    return EXERCISE_SKILL_DIRECTIONS[exercise_type]


def response_kind_for(exercise_type: ExerciseType) -> ResponseKind:
    """ExerciseType に対する ResponseKind。常に一意。"""
    return EXERCISE_RESPONSE_KINDS[exercise_type]


def tokenize_canonical_form(canonical_form: str) -> tuple[str, ...]:
    """canonical_form を語 / まとまりへ分割する。

    方針:
      - Unicode whitespace で分割する
      - apostrophe / elision（l'heure, d'accord, s'en, j'ai）は
        1トークンのまま残す。whitespace 以外では切らない
      - hyphen も分割しない（peut-être, n'est-ce）
      - 空トークンは捨てる
    """
    stripped = canonical_form.strip()
    if not stripped:
        return ()
    return tuple(token for token in _WHITESPACE_RE.split(stripped) if token)


def has_source_evidence(item: LearningItem) -> bool:
    """source cloze に必要な原文根拠が1件以上あるか。"""
    return any(ref.evidence_span is not None for ref in item.source_refs)


def evaluate_exercise_eligibility(
    item: LearningItem,
    exercise_type: ExerciseType,
    *,
    known_conjugation_lemmas: Set[str] | None = None,
) -> ExerciseEligibility:
    """当該 item に exercise_type を出してよいかを判定する。

    無理に生成しない。skip する場合は理由を残す。
    """
    direction = skill_direction_for(exercise_type)
    skip = _skip_reason(
        item,
        exercise_type,
        known_conjugation_lemmas=known_conjugation_lemmas,
    )
    if skip is None:
        return ExerciseEligibility(
            exercise_type=exercise_type,
            skill_direction=direction,
            eligible=True,
        )
    reason, detail = skip
    return ExerciseEligibility(
        exercise_type=exercise_type,
        skill_direction=direction,
        eligible=False,
        skip_reason=reason,
        detail=detail,
    )


def list_exercise_eligibility(
    item: LearningItem,
    *,
    known_conjugation_lemmas: Set[str] | None = None,
) -> tuple[ExerciseEligibility, ...]:
    """全 ExerciseType の適用可否。順序は EXERCISE_TYPES で deterministic。"""
    return tuple(
        evaluate_exercise_eligibility(
            item,
            exercise_type,
            known_conjugation_lemmas=known_conjugation_lemmas,
        )
        for exercise_type in EXERCISE_TYPES
    )


def eligible_exercise_types(
    item: LearningItem,
    *,
    known_conjugation_lemmas: Set[str] | None = None,
) -> tuple[ExerciseType, ...]:
    """Phase 3 で安全に出せる ExerciseType。unsupported は含めない。"""
    return tuple(
        row.exercise_type
        for row in list_exercise_eligibility(
            item, known_conjugation_lemmas=known_conjugation_lemmas
        )
        if row.eligible
    )


def make_exercise_spec(
    item: LearningItem,
    exercise_type: ExerciseType,
    prompt: str,
    *,
    options: tuple[str, ...] | None = None,
    source_context: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    exercise_version: str = EXERCISE_VERSION,
    known_conjugation_lemmas: Set[str] | None = None,
) -> ExerciseSpec:
    """eligibility を満たすときだけ ExerciseSpec を組み立てる。

    prompt / options の中身は呼び出し側（後続の生成実装）が用意する。
    この関数は適用条件と契約の一貫性だけを保証する。
    """
    eligibility = evaluate_exercise_eligibility(
        item,
        exercise_type,
        known_conjugation_lemmas=known_conjugation_lemmas,
    )
    if not eligibility.eligible:
        raise UnsupportedExerciseError(
            eligibility.skip_reason or "unsupported_combination",
            eligibility.detail or "unsupported exercise",
        )
    return ExerciseSpec(
        learning_item_id=item.id,
        exercise_type=exercise_type,
        skill_direction=eligibility.skill_direction,
        prompt=prompt,
        response_kind=response_kind_for(exercise_type),
        options=options,
        source_context=source_context,
        exercise_version=exercise_version,
        metadata=dict(metadata) if metadata is not None else {},
    )


def to_public_exercise(spec: ExerciseSpec) -> PublicExercise:
    """ExerciseSpec から Frontend 向け DTO を作る。

    metadata と正解情報はコピーしない。同じ入力からは同じ DTO になる。
    """
    dumped = spec.model_dump()
    leaked = _INTERNAL_ANSWER_FIELDS.intersection(dumped)
    if leaked:
        raise ValueError(f"public DTO に正解情報が混入している: {sorted(leaked)}")
    return PublicExercise(
        learning_item_id=spec.learning_item_id,
        exercise_type=spec.exercise_type,
        skill_direction=spec.skill_direction,
        prompt=spec.prompt,
        response_kind=spec.response_kind,
        options=spec.options,
        source_context=spec.source_context,
        exercise_version=spec.exercise_version,
    )


def exercise_reconstruction_key(
    learning_item_id: str,
    exercise_type: ExerciseType,
    exercise_version: str = EXERCISE_VERSION,
) -> str:
    """Exercise を永続化せず再構成するための identity。"""
    return f"{exercise_version}:{exercise_type}:{learning_item_id}"


def exercise_event_metadata(spec: ExerciseSpec) -> dict[str, Any]:
    """LearningEvent.metadata に載せる追跡情報。正解は含めない。"""
    return {
        "exercise_version": spec.exercise_version,
        "skill_direction": spec.skill_direction,
        "response_kind": spec.response_kind,
        "reconstruction_key": exercise_reconstruction_key(
            spec.learning_item_id, spec.exercise_type, spec.exercise_version
        ),
    }


def _skip_reason(
    item: LearningItem,
    exercise_type: ExerciseType,
    *,
    known_conjugation_lemmas: Set[str] | None,
) -> tuple[ExerciseSkipReason, str] | None:
    if item.status != "active":
        return (
            "inactive_item",
            f"{item.status} の LearningItem は新規学習 Session の対象外",
        )
    if exercise_type in _EXISTING_QUIZ_EXERCISE_TYPES:
        return (
            "existing_quiz_only",
            f"{exercise_type} は既存クイズ layer 専用で、"
            "LearningItem から新規生成しない",
        )
    if exercise_type in _SEMANTIC_GRADING_EXERCISE_TYPES:
        return (
            "requires_semantic_grading",
            "fr_to_ja の日本語自由記述は Phase 3 で LLM 意味判定しない",
        )
    if exercise_type not in _PHASE3_CANDIDATE_EXERCISES[item.item_type]:
        return (
            "unsupported_combination",
            f"{item.item_type} に {exercise_type} は Phase 3 で出さない",
        )
    if exercise_type == "cloze" and not has_source_evidence(item):
        return (
            "missing_source_evidence",
            "source cloze には evidence_span 付きの source_ref が必要",
        )
    if exercise_type == "verb_conjugation":
        _target, skip = evaluate_conjugation_adapter(
            item, known_conjugation_lemmas=known_conjugation_lemmas
        )
        if skip is not None:
            return skip
    if exercise_type == "expression_reconstruction":
        tokens = tokenize_canonical_form(item.canonical_form)
        if len(tokens) < MIN_RECONSTRUCTION_TOKENS:
            return (
                "insufficient_expression_tokens",
                "expression_reconstruction には複数トークンの表現が必要",
            )
    return None
