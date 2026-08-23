"""ExtractionService（Issue #132）のユースケーステスト。

LLM 実通信は使わない。fake extractor で Source 本文の引き渡し、
4種 Candidate、不正応答の拒否、エラー分類、metadata 保持を確認する。
"""

from __future__ import annotations

import ast
import inspect
from dataclasses import dataclass, field

import pytest
from pydantic import ValidationError

from app.domain.tutor import LearningItem, LearningItemCandidate, SourceDocument
from app.services.exceptions import (
    ExtractionConfigError,
    ExtractionInvalidResponseError,
    ExtractionTransientError,
)
from app.services.extraction_prompt import EXTRACTION_VERSION, MAX_CANDIDATES
from app.services.extraction_schema import (
    ExtractedCandidate,
    ExtractedEvidenceSpan,
    ExtractionLlmOutput,
)
from app.services.extraction_service import ExtractionService
from app.services.extractors import ExtractorResult

CONTENT = "Je me suis rendu compte qu'il fallait changer de stratégie."


def _source() -> SourceDocument:
    return SourceDocument(title="記事", content=CONTENT)


def _span_for(fragment: str) -> ExtractedEvidenceSpan:
    start = CONTENT.index(fragment)
    return ExtractedEvidenceSpan(start=start, end=start + len(fragment))


def _extracted(
    *,
    item_type: str = "expression",
    canonical_form: str = "se rendre compte",
    meaning_ja: str = "〜に気づく",
    fragment: str = "rendu compte",
    confidence: float = 0.9,
    **overrides,
) -> ExtractedCandidate:
    values = {
        "item_type": item_type,
        "canonical_form": canonical_form,
        "meaning_ja": meaning_ja,
        "evidence_span": _span_for(fragment),
        "confidence": confidence,
    }
    values.update(overrides)
    return ExtractedCandidate(**values)


def _four_types() -> tuple[ExtractedCandidate, ...]:
    return (
        _extracted(
            item_type="expression",
            canonical_form="se rendre compte",
            meaning_ja="〜に気づく",
            fragment="rendu compte",
        ),
        _extracted(
            item_type="vocabulary",
            canonical_form="stratégie",
            meaning_ja="戦略",
            fragment="stratégie",
            confidence=0.8,
        ),
        _extracted(
            item_type="grammar",
            canonical_form="il fallait + infinitif",
            meaning_ja="〜しなければならなかった",
            fragment="il fallait",
            explanation_ja="義務の過去",
            level="A2",
            confidence=0.7,
        ),
        _extracted(
            item_type="conjugation",
            canonical_form="changer",
            meaning_ja="変える",
            fragment="changer",
            confidence=0.6,
        ),
    )


@dataclass
class FakeLearningItemExtractor:
    result: ExtractorResult | None = None
    error: Exception | None = None
    seen_sources: list[SourceDocument] = field(default_factory=list)

    def extract(self, source: SourceDocument) -> ExtractorResult:
        self.seen_sources.append(source)
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


def _result(
    candidates: tuple[ExtractedCandidate, ...] | list[ExtractedCandidate],
    *,
    provider: str = "openai",
    model: str = "gpt-4o-mini",
    extraction_version: str = EXTRACTION_VERSION,
) -> ExtractorResult:
    return ExtractorResult(
        candidates=tuple(candidates),
        provider=provider,
        model=model,
        extraction_version=extraction_version,
    )


def test_extract_passes_source_content_to_extractor():
    fake = FakeLearningItemExtractor(result=_result(_four_types()))
    source = _source()
    ExtractionService(fake).extract(source)
    assert fake.seen_sources == [source]
    assert fake.seen_sources[0].content == CONTENT


def test_extract_maps_four_item_types_to_candidates():
    fake = FakeLearningItemExtractor(result=_result(_four_types()))
    result = ExtractionService(fake).extract(_source())

    assert [c.item_type for c in result.candidates] == [
        "expression",
        "vocabulary",
        "grammar",
        "conjugation",
    ]
    assert all(isinstance(c, LearningItemCandidate) for c in result.candidates)
    assert all(not isinstance(c, LearningItem) for c in result.candidates)
    assert {c.status for c in result.candidates} == {"candidate"}
    grammar = result.candidates[2]
    assert grammar.explanation_ja == "義務の過去"
    assert grammar.level == "A2"


def test_extract_keeps_prompt_model_version_metadata():
    fake = FakeLearningItemExtractor(
        result=_result(
            _four_types()[:1],
            provider="openai",
            model="gpt-4o-mini",
            extraction_version=EXTRACTION_VERSION,
        )
    )
    source = _source()
    result = ExtractionService(fake).extract(source)

    assert result.provider == "openai"
    assert result.model == "gpt-4o-mini"
    assert result.extraction_version == EXTRACTION_VERSION
    assert result.source_document_id == source.id
    candidate = result.candidates[0]
    assert candidate.extraction_version == EXTRACTION_VERSION
    assert candidate.metadata["provider"] == "openai"
    assert candidate.metadata["model"] == "gpt-4o-mini"
    assert candidate.metadata["prompt_version"] == EXTRACTION_VERSION


def test_extract_does_not_create_learning_item():
    fake = FakeLearningItemExtractor(result=_result(_four_types()[:1]))
    result = ExtractionService(fake).extract(_source())
    assert isinstance(result.candidates[0], LearningItemCandidate)
    assert result.candidates[0].canonical_form == "se rendre compte"


@pytest.mark.parametrize(
    "error",
    [
        ExtractionConfigError(
            "OPENAI_API_KEY が設定されていない",
            kind="api_key_missing",
        ),
        ExtractionTransientError("timeout", kind="timeout"),
        ExtractionTransientError("network", kind="network"),
        ExtractionTransientError("rate limit", kind="rate_limit"),
        ExtractionInvalidResponseError(
            "malformed",
            kind="invalid_structured_response",
        ),
        ExtractionInvalidResponseError("empty", kind="empty_response"),
    ],
)
def test_extract_propagates_classified_extractor_errors(error: Exception):
    fake = FakeLearningItemExtractor(error=error)
    with pytest.raises(type(error)) as exc_info:
        ExtractionService(fake).extract(_source())
    assert exc_info.value.kind == error.kind
    assert exc_info.value.retryable is error.retryable


def test_extract_rejects_too_many_candidates():
    overflow = tuple(
        _extracted(canonical_form=f"item-{i}", fragment="stratégie")
        for i in range(MAX_CANDIDATES + 1)
    )
    fake = FakeLearningItemExtractor(result=_result(overflow))
    with pytest.raises(ExtractionInvalidResponseError, match="上限") as exc_info:
        ExtractionService(fake).extract(_source())
    assert exc_info.value.kind == "too_many_candidates"
    assert exc_info.value.retryable is False


def test_schema_rejects_unknown_item_type():
    with pytest.raises(ValidationError):
        ExtractionLlmOutput.model_validate(
            {
                "candidates": [
                    {
                        "item_type": "idiom",
                        "canonical_form": "se rendre compte",
                        "meaning_ja": "〜に気づく",
                        "evidence_span": {"start": 0, "end": 5},
                        "confidence": 0.9,
                    }
                ]
            }
        )


def test_schema_rejects_malformed_span_and_confidence():
    with pytest.raises(ValidationError):
        ExtractedEvidenceSpan(start=5, end=5)
    with pytest.raises(ValidationError):
        _extracted(confidence=1.1)
    with pytest.raises(ValidationError):
        _extracted(canonical_form="")
    with pytest.raises(ValidationError):
        ExtractionLlmOutput(
            candidates=[
                _extracted(canonical_form=f"x{i}") for i in range(MAX_CANDIDATES + 1)
            ]
        )


def test_schema_accepts_empty_candidate_list():
    output = ExtractionLlmOutput.model_validate({"candidates": []})
    assert output.candidates == []


def test_extract_allows_zero_candidates():
    fake = FakeLearningItemExtractor(result=_result(()))
    result = ExtractionService(fake).extract(_source())
    assert result.candidates == ()


def test_extraction_service_does_not_import_openai():
    import app.services.extraction_service as module

    tree = ast.parse(inspect.getsource(module))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".", 1)[0])
    assert "openai" not in names


def test_domain_and_service_work_without_openai_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    fake = FakeLearningItemExtractor(result=_result(_four_types()[:1]))
    result = ExtractionService(fake).extract(_source())
    assert len(result.candidates) == 1
    assert _source().content == CONTENT
