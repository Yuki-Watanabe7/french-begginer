"""抽出 Candidate の evidence 検証・正規化・重複統合（Issue #133）。

LLM 出力の後ろに置く deterministic な防波堤。embedding / vector DB には
依存しない。同じ入力からは常に同じ結果になる。

このモジュールが依存してよいのは Python 標準ライブラリと domain.tutor のみ。

## whitespace / Unicode 方針

evidence span:
  - オフセットは Python の Unicode コードポイント（`len` / スライスと同じ）。
    バイトオフセットでも grapheme cluster でもない。
  - 検証は保存済み `SourceDocument.content` に対して行う。検証前に本文を
    NFC しない。LLM に渡した本文（= 保存済み本文）のオフセットと一致させる。
  - 根拠断片は LLM が返した text を信じず、`read_source_evidence` で
    `content[start:end]` から再構成する。
  - `0 <= start < end <= len(content)` を満たさない span は除外する。
  - 再構成結果が空、または strip 後に空（whitespace のみ）なら除外する。

canonical_form / meaning_ja:
  - `unicodedata.normalize("NFC", ...)` で合成済み形に揃える。
  - 前後の whitespace を除去し、内部の連続 whitespace は単一スペースにする。
  - canonical_form の両端を囲む引用符（ASCII / フランス語ギュメ / スマート
    クォート）を除去する。保存する表記の大文字小文字は維持する。

normalization key（同一 Source 内の重複統合、および既存 LearningItem との
比較準備）:
  - `candidate-norm-v1:{item_type}:{NFC済み正規化形.casefold()}`
  - 大文字小文字・前後空白の差ではキーが変わらない。
  - 異なる item_type は同じ表記でも統合しない。
  - 意味・lemma はキーに含めない（同一表現の別訳で爆発させない）。
  - accept 処理は `CandidateService.accept`（Issue #134）。このモジュールでは行わない。
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from app.domain.tutor import (
    EvidenceSpan,
    LearningItem,
    LearningItemCandidate,
    LearningItemType,
    SourceDocument,
    read_source_evidence,
)

NORMALIZATION_VERSION = "candidate-norm-v1"
"""normalization key の版。規則を変えるときは bump する。"""

MAX_VOCABULARY_TOKENS = 3
"""vocabulary が文脈付き断片とみなされるトークン数の上限（この数まで許容）。"""

CandidateExclusionReason = Literal[
    "evidence_span_out_of_range",
    "evidence_span_empty",
    "empty_canonical_form",
    "empty_meaning_ja",
    "vocabulary_context_fragment",
    "duplicate",
]

_WHITESPACE_RE = re.compile(r"\s+")
_SENTENCE_PUNCT_RE = re.compile(r"[.!?]")
_WRAP_QUOTES: tuple[tuple[str, str], ...] = (
    ("\u00ab", "\u00bb"),
    ("\u2039", "\u203a"),
    ("\u201c", "\u201d"),
    ("\u2018", "\u2019"),
    ('"', '"'),
    ("'", "'"),
)


@dataclass(frozen=True)
class CandidateExclusion:
    """正規化パイプラインが Candidate を残さなかった理由。"""

    reason: CandidateExclusionReason
    detail: str
    source_index: int
    item_type: LearningItemType | None = None
    canonical_form: str | None = None
    normalization_key: str | None = None


@dataclass(frozen=True)
class CandidateNormalizationResult:
    """1 Source 分の正規化結果。除外理由を捨てない。"""

    candidates: tuple[LearningItemCandidate, ...]
    exclusions: tuple[CandidateExclusion, ...]


def normalize_canonical_form(canonical_form: str) -> str:
    """canonical_form の deterministic な文字列正規化。

    フランス語としての正誤は判定しない。空白・Unicode・引用符だけを揃える。
    """
    return _strip_wrapping_quotes(_collapse_whitespace(_nfc(canonical_form)))


def normalize_meaning_ja(meaning_ja: str) -> str:
    """meaning_ja の deterministic な文字列正規化。"""
    return _collapse_whitespace(_nfc(meaning_ja))


def item_normalization_key(item_type: LearningItemType, canonical_form: str) -> str:
    """Candidate と既存 LearningItem の一致判定に使う structured key。

    Phase 2 の accept（#134）で source_ref 追加判定に使う。embedding は使わない。
    """
    normalized = normalize_canonical_form(canonical_form)
    return f"{NORMALIZATION_VERSION}:{item_type}:{normalized.casefold()}"


def learning_item_normalization_key(item: LearningItem) -> str:
    """既存 LearningItem 側の normalization key。"""
    return item_normalization_key(item.item_type, item.canonical_form)


def candidate_normalization_key(candidate: LearningItemCandidate) -> str:
    """Candidate 側の normalization key。"""
    return item_normalization_key(candidate.item_type, candidate.canonical_form)


def normalize_candidates(
    source: SourceDocument,
    candidates: Sequence[LearningItemCandidate],
) -> CandidateNormalizationResult:
    """Source 本文に対して Candidate を検証・正規化し、同一 Source 内で統合する。

    入力の Candidate は変更しない。除外は理由付きで返す。黙って捨てない。
    """
    kept: list[tuple[int, LearningItemCandidate]] = []
    exclusions: list[CandidateExclusion] = []

    for index, candidate in enumerate(candidates):
        outcome = _normalize_one(source, candidate, index)
        if isinstance(outcome, CandidateExclusion):
            exclusions.append(outcome)
            continue
        kept.append((index, outcome))

    deduped, duplicate_exclusions = _deduplicate(kept)
    exclusions.extend(duplicate_exclusions)
    return CandidateNormalizationResult(
        candidates=tuple(deduped),
        exclusions=tuple(exclusions),
    )


def _normalize_one(
    source: SourceDocument,
    candidate: LearningItemCandidate,
    index: int,
) -> LearningItemCandidate | CandidateExclusion:
    span_error = _validate_evidence_span(source.content, candidate.evidence_span)
    if span_error is not None:
        reason, detail = span_error
        return CandidateExclusion(
            reason=reason,
            detail=detail,
            source_index=index,
            item_type=candidate.item_type,
            canonical_form=candidate.canonical_form,
        )

    canonical_form = normalize_canonical_form(candidate.canonical_form)
    if not canonical_form:
        return CandidateExclusion(
            reason="empty_canonical_form",
            detail="正規化後の canonical_form が空になった",
            source_index=index,
            item_type=candidate.item_type,
            canonical_form=candidate.canonical_form,
        )

    meaning_ja = normalize_meaning_ja(candidate.meaning_ja)
    if not meaning_ja:
        return CandidateExclusion(
            reason="empty_meaning_ja",
            detail="正規化後の meaning_ja が空になった",
            source_index=index,
            item_type=candidate.item_type,
            canonical_form=canonical_form,
        )

    if candidate.item_type == "vocabulary" and _is_vocabulary_context_fragment(
        canonical_form
    ):
        return CandidateExclusion(
            reason="vocabulary_context_fragment",
            detail=f"vocabulary が文脈付き断片に見える: {canonical_form!r}",
            source_index=index,
            item_type=candidate.item_type,
            canonical_form=canonical_form,
        )

    explanation_ja = candidate.explanation_ja
    if explanation_ja is not None:
        explanation_ja = _collapse_whitespace(_nfc(explanation_ja)) or None

    key = item_normalization_key(candidate.item_type, canonical_form)
    metadata = {
        **candidate.metadata,
        "normalization_key": key,
        "normalization_version": NORMALIZATION_VERSION,
    }
    if candidate.item_type == "conjugation":
        metadata["lemma"] = canonical_form

    return candidate.model_copy(
        update={
            "canonical_form": canonical_form,
            "meaning_ja": meaning_ja,
            "explanation_ja": explanation_ja,
            "metadata": metadata,
        }
    )


def _validate_evidence_span(
    content: str, span: EvidenceSpan
) -> tuple[CandidateExclusionReason, str] | None:
    try:
        fragment = read_source_evidence(content, span)
    except ValueError as exc:
        return ("evidence_span_out_of_range", str(exc))
    if fragment.strip() == "":
        return (
            "evidence_span_empty",
            "再構成した根拠断片が空、または whitespace のみ",
        )
    return None


def _is_vocabulary_context_fragment(canonical_form: str) -> bool:
    if _SENTENCE_PUNCT_RE.search(canonical_form):
        return True
    tokens = canonical_form.split(" ")
    return len(tokens) > MAX_VOCABULARY_TOKENS


def _deduplicate(
    kept: Sequence[tuple[int, LearningItemCandidate]],
) -> tuple[list[LearningItemCandidate], list[CandidateExclusion]]:
    groups: dict[str, list[tuple[int, LearningItemCandidate]]] = {}
    order: list[str] = []
    for index, candidate in kept:
        key = candidate_normalization_key(candidate)
        if key not in groups:
            order.append(key)
            groups[key] = []
        groups[key].append((index, candidate))

    winners: list[LearningItemCandidate] = []
    exclusions: list[CandidateExclusion] = []
    for key in order:
        members = groups[key]
        winner_index, winner = max(
            members,
            key=lambda item: (_confidence_value(item[1]), -item[0]),
        )
        merged_count = len(members)
        if merged_count > 1:
            winner = winner.model_copy(
                update={
                    "metadata": {
                        **winner.metadata,
                        "merged_count": merged_count,
                    }
                }
            )
        winners.append(winner)
        for index, candidate in members:
            if index == winner_index:
                continue
            exclusions.append(
                CandidateExclusion(
                    reason="duplicate",
                    detail=(
                        f"normalization_key={key} の重複。"
                        f"残す source_index={winner_index}"
                    ),
                    source_index=index,
                    item_type=candidate.item_type,
                    canonical_form=candidate.canonical_form,
                    normalization_key=key,
                )
            )
    return winners, exclusions


def _confidence_value(candidate: LearningItemCandidate) -> float:
    if candidate.confidence is None:
        return -1.0
    return candidate.confidence


def _nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _collapse_whitespace(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", value).strip()


def _strip_wrapping_quotes(value: str) -> str:
    current = value.strip()
    changed = True
    while changed and current:
        changed = False
        for left, right in _WRAP_QUOTES:
            if (
                len(current) >= 2
                and current.startswith(left)
                and current.endswith(right)
            ):
                current = current[len(left) : -len(right)].strip()
                changed = True
                break
    return current
