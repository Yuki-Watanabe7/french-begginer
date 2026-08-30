"""conjugation LearningItem → 既存動詞活用 Exercise の adapter（Issue #148）。

既存の `CONJUGATIONS` / `get_correct_answer` を Tutor 用に複製せず再利用する。
LLM が「この動詞は現在形だから既存 quiz へ流してよい」と最終判断しない。
判定は metadata と supported-domain lookup のみで deterministic にする。

```text
conjugation item
  -> lemma 特定 + 既存 domain に動詞がある
  -> metadata.tense が明示され、CONJUGATIONS[lemma] にその時制がある
  -> mood があるなら indicatif のみ許可
  -> 既存 pronoun 集合から1つ選び、get_correct_answer で正解を取る
  -> 条件を満たさなければ verb_conjugation を出さず、source cloze 等へ fallback
```

このモジュールが依存してよいのは Python 標準ライブラリ、Pydantic、
`domain.tutor`、`domain.conjugation` のみ。DB / FastAPI / OpenAI には依存しない。
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Set
from typing import Any, Literal, NamedTuple

from app.domain.conjugation import CONJUGATIONS, get_correct_answer
from app.domain.tutor import LearningItem, LearningItemCandidate

CONJUGATION_METADATA_KEYS: tuple[str, ...] = ("lemma", "tense", "mood")
"""LearningItem / Candidate に載せる conjugation adapter 用 metadata。"""

ADAPTER_MOOD = "indicatif"
"""既存 CONJUGATIONS が表す法。présent は直説法のみ。"""

# 永続化してよい時制ラベル。adapter 対象かは CONJUGATIONS 側の有無で決める。
# 自由文字列をそのまま metadata に残さない。
CONJUGATION_TENSE_LABELS: frozenset[str] = frozenset(
    {
        "présent",
        "imparfait",
        "futur",
        "passé composé",
    }
)

CONJUGATION_MOOD_LABELS: frozenset[str] = frozenset(
    {
        "indicatif",
        "subjonctif",
        "conditionnel",
        "impératif",
    }
)

ConjugationAdapterSkipReason = Literal[
    "unknown_conjugation_lemma",
    "missing_conjugation_tense",
    "unsupported_conjugation_tense",
    "unsupported_conjugation_mood",
]


class ConjugationAdapterTarget(NamedTuple):
    """既存 domain に接続できる verb / tense。pronoun はまだ選ばない。"""

    lemma: str
    tense: str
    mood: str | None


class ConjugationPromptMaterial(NamedTuple):
    """既存 question 契約と同じ verb / tense / pronoun と、domain 由来の正解。"""

    lemma: str
    tense: str
    pronoun: str
    expected: str


def conjugation_lemma(item: LearningItem) -> str:
    """conjugation item の lemma。metadata.lemma があればそれを優先する。"""
    raw = item.metadata.get("lemma")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return item.canonical_form.strip()


def conjugation_tense(item: LearningItem) -> str | None:
    """明示された tense。欠落を présent とみなさない。"""
    return _nonempty_string(item.metadata.get("tense"))


def conjugation_mood(item: LearningItem) -> str | None:
    """明示された mood。欠落は許容する（présent は直説法前提）。"""
    return _nonempty_string(item.metadata.get("mood"))


def canonical_conjugation_tense(raw: str) -> str | None:
    """許可リスト内なら canonical な時制ラベル。未知の自由文字列は捨てる。"""
    return _canonical_label(raw, CONJUGATION_TENSE_LABELS)


def canonical_conjugation_mood(raw: str) -> str | None:
    """許可リスト内なら canonical な法ラベル。未知の自由文字列は捨てる。"""
    return _canonical_label(raw, CONJUGATION_MOOD_LABELS)


def resolve_conjugation_lemma(
    raw: str,
    known_lemmas: Set[str] | Mapping[str, Any] | None = None,
) -> str | None:
    """既存 domain の動詞キーへ解決する。大小文字差は吸収する。"""
    target = _nfc(raw).strip().casefold()
    if not target:
        return None
    known = CONJUGATIONS if known_lemmas is None else known_lemmas
    for key in known:
        if _nfc(key).casefold() == target:
            return key
    return None


def resolve_conjugation_tense(lemma: str, raw_tense: str) -> str | None:
    """CONJUGATIONS[lemma] にある時制キーへ解決する。無ければ None。"""
    tenses = CONJUGATIONS.get(lemma)
    if not tenses:
        return None
    target = _nfc(raw_tense).strip().casefold()
    if not target:
        return None
    for tense in tenses:
        if _nfc(tense).casefold() == target:
            return tense
    return None


def pronouns_for(lemma: str, tense: str) -> tuple[str, ...]:
    """既存 CONJUGATIONS の pronoun 順をそのまま返す。"""
    tenses = CONJUGATIONS.get(lemma, {})
    pronouns = tenses.get(tense, {})
    return tuple(pronouns.keys())


def evaluate_conjugation_adapter(
    item: LearningItem,
    *,
    known_conjugation_lemmas: Set[str] | Mapping[str, Any] | None = None,
) -> (
    tuple[ConjugationAdapterTarget, None]
    | tuple[None, tuple[ConjugationAdapterSkipReason, str]]
):
    """verb_conjugation に接続できるなら target、否则 skip reason。

    metadata.tense が無いとき présent を補完しない。
    """
    if item.item_type != "conjugation":
        return (
            None,
            (
                "unknown_conjugation_lemma",
                f"{item.item_type} は conjugation adapter の対象外",
            ),
        )

    lemma_raw = conjugation_lemma(item)
    lemma = resolve_conjugation_lemma(lemma_raw, known_lemmas=known_conjugation_lemmas)
    if lemma is None:
        return (
            None,
            (
                "unknown_conjugation_lemma",
                f"既存 verb_conjugation に接続できない lemma: {lemma_raw}",
            ),
        )

    tense_raw = conjugation_tense(item)
    if tense_raw is None:
        return (
            None,
            (
                "missing_conjugation_tense",
                "conjugation adapter には metadata.tense が必要。"
                "欠落を présent 扱いしない",
            ),
        )

    tense = resolve_conjugation_tense(lemma, tense_raw)
    if tense is None:
        return (
            None,
            (
                "unsupported_conjugation_tense",
                f"既存 domain が対応していない tense: {tense_raw}（lemma={lemma}）",
            ),
        )

    mood_raw = conjugation_mood(item)
    mood: str | None = None
    if mood_raw is not None:
        mood = canonical_conjugation_mood(mood_raw)
        if mood != ADAPTER_MOOD:
            return (
                None,
                (
                    "unsupported_conjugation_mood",
                    f"既存 domain が対応していない mood: {mood_raw}（lemma={lemma}）",
                ),
            )

    return (ConjugationAdapterTarget(lemma=lemma, tense=tense, mood=mood), None)


def build_conjugation_prompt_material(
    target: ConjugationAdapterTarget,
    pronoun: str,
) -> ConjugationPromptMaterial | None:
    """既存 get_correct_answer から正解を取る。データを複製しない。"""
    expected = get_correct_answer(target.lemma, target.tense, pronoun)
    if expected is None:
        return None
    return ConjugationPromptMaterial(
        lemma=target.lemma,
        tense=target.tense,
        pronoun=pronoun,
        expected=expected,
    )


def conjugation_candidate_metadata(
    *,
    lemma: str,
    tense: str | None = None,
    mood: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Candidate / LearningItem に載せる最小 metadata。未知ラベルは残さない。"""
    metadata = dict(extra) if extra is not None else {}
    metadata["lemma"] = lemma
    metadata.pop("tense", None)
    metadata.pop("mood", None)
    canonical_tense = canonical_conjugation_tense(tense) if tense is not None else None
    if canonical_tense is not None:
        metadata["tense"] = canonical_tense
    canonical_mood = canonical_conjugation_mood(mood) if mood is not None else None
    if canonical_mood is not None:
        metadata["mood"] = canonical_mood
    return metadata


def conjugation_item_metadata(candidate: LearningItemCandidate) -> dict[str, Any]:
    """accept 時に LearningItem へ引き継ぐ conjugation metadata。"""
    if candidate.item_type != "conjugation":
        return {}
    metadata: dict[str, Any] = {}
    for key in CONJUGATION_METADATA_KEYS:
        value = _nonempty_string(candidate.metadata.get(key))
        if value is None:
            continue
        if key == "tense":
            value = canonical_conjugation_tense(value)
        elif key == "mood":
            value = canonical_conjugation_mood(value)
        if value is not None:
            metadata[key] = value
    return metadata


def merge_conjugation_item_metadata(
    item: LearningItem,
    candidate: LearningItemCandidate,
) -> dict[str, Any]:
    """既存 Item の conjugation metadata を欠落分だけ埋める。上書きしない。"""
    merged = dict(item.metadata)
    if item.item_type != "conjugation":
        return merged
    incoming = conjugation_item_metadata(candidate)
    for key, value in incoming.items():
        current = _nonempty_string(merged.get(key))
        if current is None:
            merged[key] = value
    return merged


def _canonical_label(raw: str, allowed: frozenset[str]) -> str | None:
    target = " ".join(_nfc(raw).split()).casefold()
    if not target:
        return None
    for label in allowed:
        if _nfc(label).casefold() == target:
            return label
    return None


def _nonempty_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)
