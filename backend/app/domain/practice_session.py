"""active LearningItem から Tutor Practice Session を組み立てる（Issue #150）。

accepted 後の LearningItem を複数まとめ、ユーザーが手動開始できる
最小セッションにする。due / overdue / mastery による優先順位は付けない。
Session 自体は永続化しない。学習履歴の source of truth は回答ごとの
LearningEvent（Issue #149）とする。

このモジュールが依存してよいのは Python 標準ライブラリ、Pydantic、
`domain.tutor`、`domain.exercise`、`domain.exercise_generation` のみ。
DB / FastAPI / OpenAI には依存しない。

```text
active LearningItems
  -> eligible Exercise 列挙
  -> session policy
  -> PracticeSession
```

Selection policy（Phase 3）:
  1. active Item のみ。Candidate は入れない。suspended / mastered は skip
  2. 1 Session 内で同じ (learning_item_id, exercise_type) を重複させない
  3. recognition と production を可能な範囲で交互に含める
  4. 生成できない Item は Session 全体を失敗させず、理由付き skip
  5. RNG は seed から決定する。Item 数が少なくても同一問題を水増ししない
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Mapping, Sequence
from typing import NamedTuple

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.exercise import (
    EXERCISE_VERSION,
    ExerciseSkipReason,
    PublicExercise,
    to_public_exercise,
)
from app.domain.exercise_generation import (
    DEFAULT_GENERATION_SEED,
    SUPPORTED_ITEM_EXERCISE_TYPES,
    GeneratedExercise,
    generate_exercise,
)
from app.domain.tutor import LearningItem, SkillDirection, SourceDocument, new_id

DEFAULT_QUESTION_COUNT = 5
MAX_QUESTION_COUNT = 20
MIN_QUESTION_COUNT = 1
DEFAULT_SESSION_SEED = "tutor-practice"
"""未指定時の Session 選択シード。Exercise 生成自体は DEFAULT_GENERATION_SEED。"""


class UnknownPracticeItemError(ValueError):
    """item_ids に、渡された Item 集合へ存在しない ID が含まれる。"""

    def __init__(self, item_id: str) -> None:
        self.item_id = item_id
        super().__init__(f"LearningItem が見つからない: id={item_id}")


class InvalidPracticeSessionRequestError(ValueError):
    """question_count など、Session 入力が不正。"""


class SkippedPracticeItem(BaseModel):
    """Session に入れられなかった LearningItem。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    learning_item_id: str = Field(min_length=1)
    skip_reason: ExerciseSkipReason
    detail: str | None = None


class PracticeSession(BaseModel):
    """組み立て済みの最小 Practice Session。永続化しない。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: str = Field(min_length=1)
    exercises: tuple[GeneratedExercise, ...] = ()
    skipped_items: tuple[SkippedPracticeItem, ...] = ()
    requested_count: int = Field(ge=MIN_QUESTION_COUNT, le=MAX_QUESTION_COUNT)
    generated_count: int = Field(ge=0)
    seed: str = Field(min_length=1)

    @model_validator(mode="after")
    def _check_invariants(self) -> PracticeSession:
        if self.generated_count != len(self.exercises):
            raise ValueError("generated_count は exercises 件数と一致する必要がある")
        if self.generated_count > self.requested_count:
            raise ValueError("generated_count は requested_count を超えない")
        keys = [
            (row.spec.learning_item_id, row.spec.exercise_type)
            for row in self.exercises
        ]
        if len(keys) != len(set(keys)):
            raise ValueError(
                "1 Session 内で同じ learning_item_id + exercise_type は重複できない"
            )
        return self

    def to_public_exercises(self) -> tuple[PublicExercise, ...]:
        """Frontend 向け DTO。正解・内部 metadata は載せない。"""
        return tuple(to_public_exercise(row.spec) for row in self.exercises)


class _EligibleSlot(NamedTuple):
    item: LearningItem
    exercise: GeneratedExercise

    @property
    def skill_direction(self) -> SkillDirection:
        return self.exercise.spec.skill_direction

    @property
    def exercise_type(self) -> str:
        return self.exercise.spec.exercise_type


def build_practice_session(
    items: Sequence[LearningItem],
    *,
    sources: Mapping[str, SourceDocument] | Sequence[SourceDocument] = (),
    source_id: str | None = None,
    item_ids: Sequence[str] | None = None,
    question_count: int = DEFAULT_QUESTION_COUNT,
    seed: str | int = DEFAULT_SESSION_SEED,
    session_id: str | None = None,
) -> PracticeSession:
    """Item 集合から Practice Session を deterministic に組み立てる。

    `items` はストア上の LearningItem 全体を渡す。distractor pool は
    フィルタ前の active Item を使う（Source 内が少なくても choice を壊さない）。
    Exercise の prompt / options は `DEFAULT_GENERATION_SEED` で生成し、
    既存の GET/answer API と同じ再構成結果にする。seed は選択順だけに使う。
    """
    if not MIN_QUESTION_COUNT <= question_count <= MAX_QUESTION_COUNT:
        raise InvalidPracticeSessionRequestError(
            f"question_count は {MIN_QUESTION_COUNT}〜{MAX_QUESTION_COUNT}: "
            f"{question_count}"
        )
    if source_id is not None and item_ids is not None:
        raise InvalidPracticeSessionRequestError(
            "source_id と item_ids は同時に指定できない"
        )

    targets = _resolve_targets(items, source_id=source_id, item_ids=item_ids)
    if item_ids is None and source_id is None:
        # 全体練習では inactive を skipped に並べない。明示指定時だけ理由を返す。
        targets = [item for item in targets if item.status == "active"]
    pool = tuple(item for item in items if item.status == "active")
    slots: list[_EligibleSlot] = []
    skipped: list[SkippedPracticeItem] = []

    for item in targets:
        item_slots, skip = _enumerate_item(item, pool=pool, sources=sources)
        if skip is not None:
            skipped.append(skip)
            continue
        slots.extend(item_slots)

    selected = _select_slots(slots, question_count=question_count, seed=seed)
    exercises = tuple(slot.exercise for slot in selected)
    return PracticeSession(
        session_id=session_id if session_id is not None else new_id(),
        exercises=exercises,
        skipped_items=tuple(skipped),
        requested_count=question_count,
        generated_count=len(exercises),
        seed=str(seed),
    )


def _resolve_targets(
    items: Sequence[LearningItem],
    *,
    source_id: str | None,
    item_ids: Sequence[str] | None,
) -> list[LearningItem]:
    by_id = {item.id: item for item in items}
    if item_ids is not None:
        seen: set[str] = set()
        ordered: list[LearningItem] = []
        for item_id in item_ids:
            if item_id in seen:
                continue
            seen.add(item_id)
            item = by_id.get(item_id)
            if item is None:
                raise UnknownPracticeItemError(item_id)
            ordered.append(item)
        return ordered
    filtered = list(items)
    if source_id is not None:
        filtered = [
            item
            for item in items
            if any(ref.source_document_id == source_id for ref in item.source_refs)
        ]
    return sorted(filtered, key=lambda item: (item.created_at, item.id))


def _enumerate_item(
    item: LearningItem,
    *,
    pool: Sequence[LearningItem],
    sources: Mapping[str, SourceDocument] | Sequence[SourceDocument],
) -> tuple[list[_EligibleSlot], SkippedPracticeItem | None]:
    """1 Item から出せる Exercise を列挙する。1件も無ければ skip。"""
    types = SUPPORTED_ITEM_EXERCISE_TYPES[item.item_type]
    slots: list[_EligibleSlot] = []
    first_skip: tuple[ExerciseSkipReason, str] | None = None
    for exercise_type in types:
        result = generate_exercise(
            item,
            exercise_type,
            pool=pool,
            seed=DEFAULT_GENERATION_SEED,
            sources=sources,
        )
        if result.eligible and result.exercise is not None:
            slots.append(_EligibleSlot(item=item, exercise=result.exercise))
            continue
        if first_skip is None:
            first_skip = (
                result.skip_reason or "unsupported_combination",
                result.detail or "unsupported exercise",
            )
    if slots:
        return slots, None
    reason, detail = first_skip or (
        "unsupported_combination",
        f"{item.item_type} から Exercise を生成できない",
    )
    return [], SkippedPracticeItem(
        learning_item_id=item.id,
        skip_reason=reason,
        detail=detail,
    )


def _select_slots(
    slots: Sequence[_EligibleSlot],
    *,
    question_count: int,
    seed: str | int,
) -> list[_EligibleSlot]:
    """recognition と production を交互に取り、上限まで重複なしで選ぶ。"""
    recognition = [slot for slot in slots if slot.skill_direction == "recognition"]
    production = [slot for slot in slots if slot.skill_direction == "production"]
    recognition.sort(key=_slot_sort_key)
    production.sort(key=_slot_sort_key)

    rng = _session_rng(seed)
    rng.shuffle(recognition)
    rng.shuffle(production)

    selected: list[_EligibleSlot] = []
    i_rec = 0
    i_prod = 0
    while len(selected) < question_count and (
        i_rec < len(recognition) or i_prod < len(production)
    ):
        if i_rec < len(recognition):
            selected.append(recognition[i_rec])
            i_rec += 1
            if len(selected) >= question_count:
                break
        if i_prod < len(production):
            selected.append(production[i_prod])
            i_prod += 1
    return selected


def _slot_sort_key(slot: _EligibleSlot) -> tuple:
    return (slot.item.created_at, slot.item.id, slot.exercise_type)


def _session_rng(seed: str | int) -> random.Random:
    material = "\0".join(("practice-session", str(seed), EXERCISE_VERSION))
    digest = hashlib.sha256(material.encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))
