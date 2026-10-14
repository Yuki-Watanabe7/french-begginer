"""due review queue から Review Practice Session を組み立てる（Issue #164）。

Phase 3 の手動 Practice Session とは別に、due review queue だけを入力として
「今復習すべきもの」だけを解く Session を作る。新規 Item は混ぜない。
Session 自体は永続化しない。学習履歴の source of truth は回答ごとの
LearningEvent（Issue #149）とする。未回答 / skip では ReviewSchedule を
更新しない。このモジュールは schedule を書き換えない。

このモジュールが依存してよいのは Python 標準ライブラリ、Pydantic、
`domain.tutor`、`domain.exercise`、`domain.exercise_generation`、
`domain.review_queue`、`domain.context_selection` のみ。
DB / FastAPI / OpenAI には依存しない。
wall clock は呼ばない。

```text
due review queue
  -> directionごとのeligible Exercise選択
  -> Review Practice Session
```

Selection policy（Phase 4）:
  1. due entry のみ。future / 未スケジュール / inactive は queue 側で除外済み
  2. entry の skill_direction に合う Exercise だけを選ぶ
  3. 同一 direction に複数 eligible があるときは固定優先順
     recognition: meaning_recognition
     production: cloze → expression_reconstruction → verb_conjugation → ja_to_fr
  4. 1 Session 内で同じ (learning_item_id, exercise_type) を重複させない
  5. 生成できない entry は Session 全体を失敗させず、理由付き skip
  6. 並びは queue の overdue 順。習熟度スコアでは並べ替えない
  7. question_count まで埋める。候補が少なければ水増ししない
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.context_selection import ContextUsage
from app.domain.exercise import (
    ExerciseSkipReason,
    PublicExercise,
    skill_direction_for,
    to_public_exercise,
)
from app.domain.exercise_generation import (
    DEFAULT_GENERATION_SEED,
    GeneratedExercise,
    generate_exercise,
)
from app.domain.review_queue import ReviewQueueEntry
from app.domain.tutor import (
    ExerciseType,
    LearningItem,
    SkillDirection,
    SourceDocument,
    new_id,
)

DEFAULT_QUESTION_COUNT = 5
MAX_QUESTION_COUNT = 20
MIN_QUESTION_COUNT = 1
DEFAULT_REVIEW_SESSION_SEED = "tutor-review"
"""未指定時の Session シード。Exercise 生成自体は DEFAULT_GENERATION_SEED。

Phase 4 の出題順は queue の overdue 順で決まる。seed は再現用に記録する。
"""

REVIEW_EXERCISE_PRIORITY: dict[SkillDirection, tuple[ExerciseType, ...]] = {
    "recognition": ("meaning_recognition",),
    "production": (
        "cloze",
        "expression_reconstruction",
        "verb_conjugation",
        "ja_to_fr",
    ),
}
"""同一 direction で複数 eligible なときの固定優先順。

production は source cloze を context 復習として最優先し、無ければ
item_type に応じて reconstruction / verb_conjugation / ja_to_fr へ落とす。
Phase 5 の習熟度スコアは使わない。
"""


class InvalidReviewSessionRequestError(ValueError):
    """question_count など、Review Session 入力が不正。"""


class SkippedReviewEntry(BaseModel):
    """Session に入れられなかった due queue entry。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    learning_item_id: str = Field(min_length=1)
    skill_direction: SkillDirection
    skip_reason: ExerciseSkipReason
    detail: str | None = None


class ReviewPracticeSession(BaseModel):
    """組み立て済みの Review Practice Session。永続化しない。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: str = Field(min_length=1)
    exercises: tuple[GeneratedExercise, ...] = ()
    skipped_entries: tuple[SkippedReviewEntry, ...] = ()
    requested_count: int = Field(ge=MIN_QUESTION_COUNT, le=MAX_QUESTION_COUNT)
    generated_count: int = Field(ge=0)
    seed: str = Field(min_length=1)

    @model_validator(mode="after")
    def _check_invariants(self) -> ReviewPracticeSession:
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


def build_review_practice_session(
    entries: Sequence[ReviewQueueEntry],
    *,
    pool: Sequence[LearningItem] = (),
    sources: Mapping[str, SourceDocument] | Sequence[SourceDocument] = (),
    question_count: int = DEFAULT_QUESTION_COUNT,
    seed: str | int = DEFAULT_REVIEW_SESSION_SEED,
    session_id: str | None = None,
    context_usages_by_item: Mapping[str, Sequence[ContextUsage]] | None = None,
) -> ReviewPracticeSession:
    """due queue entry から Review Practice Session を deterministic に組み立てる。

    `entries` は overdue 順済みの due queue を渡す。この関数は並びを変えず、
    先頭から question_count 件まで埋める。`pool` は distractor 用で、
    due でない Item を出題対象にはしない。
    Exercise の prompt / options は `DEFAULT_GENERATION_SEED` で生成し、
    既存の GET/answer API と同じ再構成結果にする。
    """
    if not MIN_QUESTION_COUNT <= question_count <= MAX_QUESTION_COUNT:
        raise InvalidReviewSessionRequestError(
            f"question_count は {MIN_QUESTION_COUNT}〜{MAX_QUESTION_COUNT}: "
            f"{question_count}"
        )

    active_pool = tuple(item for item in pool if item.status == "active")
    usages_by_item = context_usages_by_item or {}
    selected: list[GeneratedExercise] = []
    skipped: list[SkippedReviewEntry] = []
    used_keys: set[tuple[str, ExerciseType]] = set()

    for entry in entries:
        if len(selected) >= question_count:
            break
        exercise, skip = _select_exercise_for_entry(
            entry,
            pool=active_pool,
            sources=sources,
            used_keys=used_keys,
            context_usages=usages_by_item.get(entry.item.id, ()),
        )
        if skip is not None:
            skipped.append(skip)
            continue
        if exercise is None:
            continue
        selected.append(exercise)
        used_keys.add((exercise.spec.learning_item_id, exercise.spec.exercise_type))

    return ReviewPracticeSession(
        session_id=session_id if session_id is not None else new_id(),
        exercises=tuple(selected),
        skipped_entries=tuple(skipped),
        requested_count=question_count,
        generated_count=len(selected),
        seed=str(seed),
    )


def _select_exercise_for_entry(
    entry: ReviewQueueEntry,
    *,
    pool: Sequence[LearningItem],
    sources: Mapping[str, SourceDocument] | Sequence[SourceDocument],
    used_keys: set[tuple[str, ExerciseType]],
    context_usages: Sequence[ContextUsage] = (),
) -> tuple[GeneratedExercise | None, SkippedReviewEntry | None]:
    """1 due entry から、その direction の Exercise を1件選ぶ。"""
    first_skip: tuple[ExerciseSkipReason, str] | None = None
    for exercise_type in REVIEW_EXERCISE_PRIORITY[entry.skill_direction]:
        if skill_direction_for(exercise_type) != entry.skill_direction:
            continue
        if (entry.item.id, exercise_type) in used_keys:
            continue
        result = generate_exercise(
            entry.item,
            exercise_type,
            pool=pool,
            seed=DEFAULT_GENERATION_SEED,
            sources=sources,
            context_usages=context_usages,
        )
        if result.eligible and result.exercise is not None:
            if result.exercise.spec.skill_direction != entry.skill_direction:
                if first_skip is None:
                    first_skip = (
                        "unsupported_combination",
                        "生成結果の skill_direction が queue entry と一致しない",
                    )
                continue
            return result.exercise, None
        if first_skip is None:
            first_skip = (
                result.skip_reason or "unsupported_combination",
                result.detail or "unsupported exercise",
            )
    reason, detail = first_skip or (
        "unsupported_combination",
        f"{entry.item.item_type} の {entry.skill_direction} から "
        "Exercise を生成できない",
    )
    return None, SkippedReviewEntry(
        learning_item_id=entry.item.id,
        skill_direction=entry.skill_direction,
        skip_reason=reason,
        detail=detail,
    )
