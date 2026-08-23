"""SourceDocument から学習候補を抽出するユースケース（Issue #132）。

LLM は候補生成器として扱う。出力は LearningItemCandidate へ validation した
うえで返し、LearningItem には保存しない。永続化・正規化・採否は後続 Issue。

OpenAI SDK は使わない。LearningItemExtractor にだけ依存する。
"""

from dataclasses import dataclass

from pydantic import ValidationError

from app.domain.tutor import EvidenceSpan, LearningItemCandidate, SourceDocument
from app.services.exceptions import ExtractionInvalidResponseError
from app.services.extraction_prompt import MAX_CANDIDATES
from app.services.extraction_schema import ExtractedCandidate
from app.services.extractors import ExtractorResult, LearningItemExtractor


@dataclass(frozen=True)
class ExtractionResult:
    """Source 1件に対する抽出結果。"""

    source_document_id: str
    candidates: tuple[LearningItemCandidate, ...]
    provider: str
    model: str
    extraction_version: str


class ExtractionService:
    def __init__(self, extractor: LearningItemExtractor) -> None:
        self._extractor = extractor

    def extract(self, source: SourceDocument) -> ExtractionResult:
        """Source 本文から学習候補を抽出して domain Candidate にする。

        LearningItem は作らない。
        """
        raw = self._extractor.extract(source)
        if len(raw.candidates) > MAX_CANDIDATES:
            raise ExtractionInvalidResponseError(
                f"抽出候補が上限 {MAX_CANDIDATES} 件を超えている: "
                f"{len(raw.candidates)} 件",
                kind="too_many_candidates",
            )
        try:
            candidates = tuple(
                _to_learning_item_candidate(source, item, raw)
                for item in raw.candidates
            )
        except (ValueError, TypeError, ValidationError) as exc:
            raise ExtractionInvalidResponseError(
                "抽出結果を LearningItemCandidate にできなかった",
                kind="invalid_structured_response",
            ) from exc
        return ExtractionResult(
            source_document_id=source.id,
            candidates=candidates,
            provider=raw.provider,
            model=raw.model,
            extraction_version=raw.extraction_version,
        )


def _to_learning_item_candidate(
    source: SourceDocument,
    item: ExtractedCandidate,
    raw: ExtractorResult,
) -> LearningItemCandidate:
    return LearningItemCandidate(
        source_document_id=source.id,
        item_type=item.item_type,
        canonical_form=item.canonical_form,
        meaning_ja=item.meaning_ja,
        explanation_ja=item.explanation_ja,
        level=item.level,
        evidence_span=EvidenceSpan(
            start=item.evidence_span.start,
            end=item.evidence_span.end,
        ),
        confidence=item.confidence,
        extraction_version=raw.extraction_version,
        metadata={
            "provider": raw.provider,
            "model": raw.model,
            "prompt_version": raw.extraction_version,
        },
    )
