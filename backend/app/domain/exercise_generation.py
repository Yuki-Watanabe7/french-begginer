"""LearningItem 向け deterministic Exercise 生成（Issue #146 / #147 / #148）。

accepted かつ active な LearningItem の確定済み情報と Source provenance から、
LLM 再呼び出しなしで Exercise を組み立てる。出題のたびに問題と正解を
LLM に作らせない。

このモジュールが依存してよいのは Python 標準ライブラリ、Pydantic、
`domain.tutor`、`domain.exercise`、`domain.conjugation_adapter` のみ。
DB / FastAPI / OpenAI には依存しない。

同じ (item, exercise_type, seed, exercise_version, sources) からは
同じ Exercise になる。正解は `ExerciseAnswerKey` に閉じ、
`to_public_exercise` には載せない。

```text
LearningItem (+ active pool, seed, sources)
  -> eligibility / skip reason
  -> ExerciseSpec + ExerciseAnswerKey
```

Phase 3 初期対象:
  - meaning_recognition（FR → 日本語意味の choice）
  - ja_to_fr（日本語意味 → canonical_form の production）
  - expression_reconstruction（expression の語順再構成）
  - source cloze（evidence_span から原文 slice を blank 化）
  - verb_conjugation（既存 CONJUGATIONS への adapter。条件を満たす conjugation のみ）

HTTP API / Frontend / 回答送信は対象外。
fr_to_ja の日本語自由記述は meaning_ja との文字列一致で採点しない。
cloze の正解は LLM の raw evidence text ではなく Source 本文の slice。
"""

from __future__ import annotations

import hashlib
import random
import re
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, NamedTuple

from pydantic import BaseModel, ConfigDict, model_validator

from app.domain.conjugation_adapter import (
    build_conjugation_prompt_material,
    evaluate_conjugation_adapter,
    pronouns_for,
)
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
from app.domain.tutor import (
    EvidenceSpan,
    ExerciseType,
    LearningItem,
    LearningItemType,
    SourceDocument,
    SourceRef,
    read_source_evidence,
)

MEANING_RECOGNITION_CHOICE_COUNT = 4
"""meaning_recognition の目標選択肢数。足りなければ MIN_CHOICE_OPTIONS まで減らす。"""

DEFAULT_GENERATION_SEED = "tutor-exercise"
"""未指定時の生成シード。テストでは必ず明示する。"""

SUPPORTED_ITEM_EXERCISE_TYPES: dict[LearningItemType, tuple[ExerciseType, ...]] = {
    "vocabulary": ("meaning_recognition", "ja_to_fr", "cloze"),
    "expression": (
        "meaning_recognition",
        "ja_to_fr",
        "expression_reconstruction",
        "cloze",
    ),
    "grammar": ("cloze",),
    "conjugation": ("verb_conjugation", "cloze"),
}
"""item_type ごとにこの生成器が組み立てる形式。"""

GENERATED_EXERCISE_TYPES: frozenset[ExerciseType] = frozenset(
    exercise_type
    for types in SUPPORTED_ITEM_EXERCISE_TYPES.values()
    for exercise_type in types
)
"""このモジュールが実際に組み立てる ExerciseType。"""

CLOZE_CONTEXT_MAX_CHARS = 160
"""cloze prompt に載せる前後文脈の上限。長文 Source 全文は返さない。"""

CLOZE_BLANK = "____"
"""evidence 部分を置き換える空欄。"""

_MEANING_RECOGNITION_PROMPT = (
    "次のフランス語の意味を選んでください。\n\n{canonical_form}"
)
_JA_TO_FR_PROMPT = "次の意味をフランス語で書いてください。\n\n{meaning_ja}"
_RECONSTRUCTION_PROMPT = "次の語を正しい順に並べて、表現を完成させてください。"
_CLOZE_PROMPT = "次の空欄に入るフランス語を、原文のまま書いてください。\n\n{cloze_text}"
_VERB_CONJUGATION_PROMPT = (
    "次の動詞を、指定された時制・主語で活用してください。\n\n"
    "動詞: {verb}\n時制: {tense}\n主語: {pronoun}"
)
_SENTENCE_BREAK_RE = re.compile(r"(?:[.!?…]+\s+|\n+)")
_SENTENCE_END_RE = re.compile(r"[.!?…]+|\n")


class _ClozeMaterial(NamedTuple):
    source: SourceDocument
    span: EvidenceSpan
    expected: str
    window: tuple[int, int]
    blanked: str


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
    sources: Mapping[str, SourceDocument] | Sequence[SourceDocument] = (),
    cloze_context_max_chars: int = CLOZE_CONTEXT_MAX_CHARS,
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
            f"{item.item_type} の {exercise_type} は この生成器の初期対象外",
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
    if exercise_type == "cloze":
        return _generate_cloze(
            item,
            _source_map(sources),
            metadata,
            cloze_context_max_chars=cloze_context_max_chars,
        )
    if exercise_type == "verb_conjugation":
        return _generate_verb_conjugation(item, rng, metadata)
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
    sources: Mapping[str, SourceDocument] | Sequence[SourceDocument] = (),
    cloze_context_max_chars: int = CLOZE_CONTEXT_MAX_CHARS,
) -> tuple[ExerciseGenerationResult, ...]:
    """この生成器が扱う ExerciseType を item に対して順に生成する。"""
    types = SUPPORTED_ITEM_EXERCISE_TYPES[item.item_type]
    if not types:
        return ()
    return tuple(
        generate_exercise(
            item,
            exercise_type,
            pool=pool,
            seed=seed,
            sources=sources,
            cloze_context_max_chars=cloze_context_max_chars,
        )
        for exercise_type in types
    )


def select_cloze_source_ref(
    item: LearningItem,
    sources: Mapping[str, SourceDocument] | Sequence[SourceDocument],
) -> SourceRef | None:
    """cloze に使う SourceRef を deterministic に1件選ぶ。

    方針（oldest-source）:
      - evidence_span がある SourceRef だけを候補にする
      - SourceDocument が渡されているものだけを候補にする
      - SourceDocument.created_at 昇順、同刻なら source_document_id 昇順
      - さらに同順位なら evidence_span.start / end 昇順
      - 暗黙の random は使わない
    """
    source_map = _source_map(sources)
    ranked = _rank_cloze_source_refs(item, source_map)
    return ranked[0] if ranked else None


def blank_source_span(
    content: str,
    start: int,
    end: int,
    *,
    blank: str = CLOZE_BLANK,
) -> str:
    """本文の [start:end) を blank に置き換える。文字列 replace は使わない。"""
    return content[:start] + blank + content[end:]


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


def _generate_verb_conjugation(
    item: LearningItem,
    rng: random.Random,
    metadata: dict[str, Any],
) -> ExerciseGenerationResult:
    target, skip = evaluate_conjugation_adapter(item)
    if target is None or skip is not None:
        reason, detail = skip or (
            "unknown_conjugation_lemma",
            "conjugation adapter の対象を解決できない",
        )
        return _skipped("verb_conjugation", reason, detail)
    pronouns = pronouns_for(target.lemma, target.tense)
    if not pronouns:
        return _skipped(
            "verb_conjugation",
            "unsupported_conjugation_tense",
            f"既存 domain に pronoun がない: {target.lemma}/{target.tense}",
        )
    pronoun = pronouns[rng.randrange(len(pronouns))]
    material = build_conjugation_prompt_material(target, pronoun)
    if material is None:
        return _skipped(
            "verb_conjugation",
            "unsupported_conjugation_tense",
            f"既存 domain に正解がない: {target.lemma}/{target.tense}/{pronoun}",
        )
    spec = make_exercise_spec(
        item,
        "verb_conjugation",
        prompt=_VERB_CONJUGATION_PROMPT.format(
            verb=material.lemma,
            tense=material.tense,
            pronoun=material.pronoun,
        ),
        metadata={
            **metadata,
            "verb": material.lemma,
            "tense": material.tense,
            "pronoun": material.pronoun,
        },
    )
    return _generated(
        spec,
        ExerciseAnswerKey(expected_answers=(material.expected,)),
    )


def _generate_cloze(
    item: LearningItem,
    sources: Mapping[str, SourceDocument],
    metadata: dict[str, Any],
    *,
    cloze_context_max_chars: int,
) -> ExerciseGenerationResult:
    material = _resolve_cloze_material(item, sources, cloze_context_max_chars)
    if not isinstance(material, _ClozeMaterial):
        reason, detail = material
        return _skipped("cloze", reason, detail)
    spec = make_exercise_spec(
        item,
        "cloze",
        prompt=_CLOZE_PROMPT.format(cloze_text=material.blanked),
        source_context=material.blanked,
        metadata={
            **metadata,
            "source_document_id": material.source.id,
            "evidence_start": material.span.start,
            "evidence_end": material.span.end,
            "context_window_start": material.window[0],
            "context_window_end": material.window[1],
        },
    )
    return _generated(spec, ExerciseAnswerKey(expected_answers=(material.expected,)))


def _resolve_cloze_material(
    item: LearningItem,
    sources: Mapping[str, SourceDocument],
    max_chars: int,
) -> _ClozeMaterial | tuple[ExerciseSkipReason, str]:
    """valid な cloze 材料を選ぶ。invalid を無言で誤問題にしない。"""
    evidence_refs = [ref for ref in item.source_refs if ref.evidence_span is not None]
    if not evidence_refs:
        return (
            "missing_source_evidence",
            "source cloze には evidence_span 付きの source_ref が必要",
        )

    valid: list[_ClozeMaterial] = []
    first_error: tuple[ExerciseSkipReason, str] | None = None
    for ref in _ordered_cloze_refs(evidence_refs, sources):
        checked = _validate_cloze_ref(ref, sources, max_chars)
        if isinstance(checked, _ClozeMaterial):
            valid.append(checked)
        elif first_error is None:
            first_error = checked

    if valid:
        valid.sort(
            key=lambda row: (
                row.source.created_at,
                row.source.id,
                row.span.start,
                row.span.end,
            )
        )
        return valid[0]
    return first_error or (
        "source_not_found",
        "source cloze に必要な SourceDocument が見つからない",
    )


_MISSING_SOURCE_CREATED_AT = datetime.max.replace(tzinfo=UTC)


def _ordered_cloze_refs(
    refs: Sequence[SourceRef],
    sources: Mapping[str, SourceDocument],
) -> list[SourceRef]:
    """失敗理由を安定して返すための走査順。存在する Source を先に、古い順。"""

    def sort_key(ref: SourceRef) -> tuple[int, datetime, str, int, int]:
        source = sources.get(ref.source_document_id)
        span = ref.evidence_span
        start = span.start if span is not None else 0
        end = span.end if span is not None else 0
        if source is None:
            return (1, _MISSING_SOURCE_CREATED_AT, ref.source_document_id, start, end)
        return (0, source.created_at, source.id, start, end)

    return sorted(refs, key=sort_key)


def _rank_cloze_source_refs(
    item: LearningItem,
    sources: Mapping[str, SourceDocument],
) -> list[SourceRef]:
    refs = [ref for ref in item.source_refs if ref.evidence_span is not None]
    present = [ref for ref in refs if ref.source_document_id in sources]
    return _ordered_cloze_refs(present, sources)


def _validate_cloze_ref(
    ref: SourceRef,
    sources: Mapping[str, SourceDocument],
    max_chars: int,
) -> _ClozeMaterial | tuple[ExerciseSkipReason, str]:
    span = ref.evidence_span
    if span is None:
        return (
            "missing_source_evidence",
            "source cloze には evidence_span 付きの source_ref が必要",
        )
    source = sources.get(ref.source_document_id)
    if source is None:
        return (
            "source_not_found",
            f"SourceDocument が存在しない: {ref.source_document_id}",
        )
    try:
        expected = read_source_evidence(source.content, span)
    except ValueError as exc:
        return ("evidence_span_out_of_range", str(exc))
    if expected.strip() == "":
        return (
            "evidence_span_empty",
            "再構成した根拠断片が空、または whitespace のみ",
        )
    window = _cloze_window_bounds(source.content, span.start, span.end, max_chars)
    if window is None:
        return (
            "context_unavailable",
            "blank 対象の前後に十分な context を切り出せない",
        )
    win_start, win_end = window
    window_text = source.content[win_start:win_end]
    rel_start = span.start - win_start
    rel_end = span.end - win_start
    outside = window_text[:rel_start] + window_text[rel_end:]
    if outside.strip() == "":
        return (
            "context_unavailable",
            "blank 対象の前後に十分な context を切り出せない",
        )
    return _ClozeMaterial(
        source=source,
        span=span,
        expected=expected,
        window=(win_start, win_end),
        blanked=blank_source_span(window_text, rel_start, rel_end),
    )


def _cloze_window_bounds(
    content: str,
    start: int,
    end: int,
    max_chars: int,
) -> tuple[int, int] | None:
    """evidence を含む前後 context の [win_start, win_end) を返す。"""
    if max_chars <= 0:
        return None
    span_len = end - start
    if span_len <= 0 or span_len >= max_chars:
        return None
    n = len(content)
    if n <= max_chars:
        return (0, n)

    sent_start, sent_end = _sentence_bounds(content, start, end)
    if sent_end - sent_start <= max_chars and sent_start <= start and sent_end >= end:
        return (sent_start, sent_end)

    budget = max_chars - span_len
    left_avail = start
    right_avail = n - end
    left_take = min(left_avail, budget // 2)
    right_take = min(right_avail, budget - left_take)
    leftover = budget - left_take - right_take
    if leftover and left_take < left_avail:
        extra = min(leftover, left_avail - left_take)
        left_take += extra
        leftover -= extra
    if leftover and right_take < right_avail:
        right_take += min(leftover, right_avail - right_take)
    win_start = start - left_take
    win_end = end + right_take
    snapped_start = _snap_left(content, win_start, start)
    snapped_end = _snap_right(content, win_end, end)
    snapped_outside = content[snapped_start:start] + content[end:snapped_end]
    if snapped_outside.strip():
        win_start, win_end = snapped_start, snapped_end
    if win_end - win_start > max_chars:
        overflow = (win_end - win_start) - max_chars
        win_end = max(end, win_end - overflow)
    return (win_start, win_end)


def _sentence_bounds(content: str, start: int, end: int) -> tuple[int, int]:
    sent_start = 0
    for match in _SENTENCE_BREAK_RE.finditer(content[:start]):
        sent_start = match.end()
    match = _SENTENCE_END_RE.search(content[end:])
    if match is None:
        sent_end = len(content)
    elif match.group() == "\n" or match.group().startswith("\n"):
        sent_end = end + match.start()
    else:
        sent_end = end + match.end()
    return sent_start, sent_end


def _snap_left(content: str, win_start: int, span_start: int) -> int:
    """トークン途中で切らないよう、必要なら開始を次の空白境界へ進める。"""
    if win_start <= 0 or win_start >= span_start:
        return win_start
    if content[win_start].isspace() or content[win_start - 1].isspace():
        return win_start
    cursor = win_start
    while cursor < span_start and not content[cursor].isspace():
        cursor += 1
    while cursor < span_start and content[cursor].isspace():
        cursor += 1
    return cursor


def _snap_right(content: str, win_end: int, span_end: int) -> int:
    """トークン途中で切らないよう、必要なら終端を前の空白境界へ戻す。"""
    n = len(content)
    if win_end >= n or win_end <= span_end:
        return win_end
    if content[win_end - 1].isspace() or (win_end < n and content[win_end].isspace()):
        return win_end
    cursor = win_end
    while cursor > span_end and not content[cursor - 1].isspace():
        cursor -= 1
    return cursor


def _source_map(
    sources: Mapping[str, SourceDocument] | Sequence[SourceDocument],
) -> dict[str, SourceDocument]:
    if isinstance(sources, Mapping):
        return dict(sources)
    return {source.id: source for source in sources}


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
