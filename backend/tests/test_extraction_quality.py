"""LLM抽出品質ハーネス（Issue #136）のテスト。

実 LLM は呼ばない。固定 fixture と fake extractor で deterministic に検証する。
live LLM は RUN_LIVE_LLM=1 のときだけ opt-in。
"""

from __future__ import annotations

import ast
import inspect
import json
import os
from dataclasses import dataclass, field

import pytest
from evaluate_tutor_extraction import (
    evaluate_with_extractor,
    reports_failed_strict,
    select_fixtures,
)

from app.domain.candidate_normalization import CandidateExclusion
from app.domain.tutor import EvidenceSpan, LearningItemCandidate, SourceDocument
from app.evaluation.extraction_fixtures import (
    EXTRACTION_QUALITY_FIXTURES,
    FIXTURE_A,
    FIXTURE_B,
    FIXTURE_C,
    FIXTURE_D,
    get_fixture,
)
from app.evaluation.extraction_quality import (
    evaluate_extraction,
    format_text_report,
    reports_to_json,
)
from app.services.extraction_prompt import EXTRACTION_VERSION, MAX_CANDIDATES
from app.services.extraction_schema import ExtractedCandidate, ExtractedEvidenceSpan
from app.services.extraction_service import ExtractionResult, ExtractionService
from app.services.extractors import ExtractorResult


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


def _span(content: str, fragment: str) -> ExtractedEvidenceSpan:
    start = content.index(fragment)
    return ExtractedEvidenceSpan(start=start, end=start + len(fragment))


def _extracted(
    content: str,
    *,
    item_type: str,
    canonical_form: str,
    meaning_ja: str,
    fragment: str,
    confidence: float = 0.9,
) -> ExtractedCandidate:
    return ExtractedCandidate(
        item_type=item_type,
        canonical_form=canonical_form,
        meaning_ja=meaning_ja,
        evidence_span=_span(content, fragment),
        confidence=confidence,
    )


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


def _candidate(
    source: SourceDocument,
    *,
    item_type: str = "vocabulary",
    canonical_form: str = "pomme",
    meaning_ja: str = "りんご",
    start: int = 0,
    end: int = 2,
    confidence: float = 0.9,
) -> LearningItemCandidate:
    return LearningItemCandidate(
        source_document_id=source.id,
        item_type=item_type,
        canonical_form=canonical_form,
        meaning_ja=meaning_ja,
        evidence_span=EvidenceSpan(start=start, end=end),
        confidence=confidence,
        extraction_version=EXTRACTION_VERSION,
    )


def _snapshot(
    source: SourceDocument,
    candidates: tuple[LearningItemCandidate, ...],
    *,
    exclusions: tuple[CandidateExclusion, ...] = (),
    provider: str = "fake",
    model: str = "fixture",
    extraction_version: str = EXTRACTION_VERSION,
) -> ExtractionResult:
    return ExtractionResult(
        source_document_id=source.id,
        candidates=candidates,
        provider=provider,
        model=model,
        extraction_version=extraction_version,
        exclusions=exclusions,
    )


def _good_a() -> tuple[ExtractedCandidate, ...]:
    content = FIXTURE_A.content
    return (
        _extracted(
            content,
            item_type="expression",
            canonical_form="se rendre compte de",
            meaning_ja="〜に気づく",
            fragment="rendu compte",
        ),
        _extracted(
            content,
            item_type="grammar",
            canonical_form="il faut",
            meaning_ja="〜しなければならない",
            fragment="il fallait",
        ),
        _extracted(
            content,
            item_type="vocabulary",
            canonical_form="stratégie",
            meaning_ja="戦略",
            fragment="stratégie",
        ),
    )


def test_fixed_source_fixtures_cover_required_patterns():
    assert [fixture.fixture_id for fixture in EXTRACTION_QUALITY_FIXTURES] == [
        "A",
        "B",
        "C",
        "D",
    ]
    assert FIXTURE_A.content.startswith("Je me suis rendu compte")
    assert FIXTURE_B.content == "Je mange une pomme."
    assert "s'agit de" in FIXTURE_C.content
    assert "suis allé" in FIXTURE_D.content
    for fixture in EXTRACTION_QUALITY_FIXTURES:
        assert fixture.must_include
        assert fixture.must_not_hallucinate
        assert fixture.max_candidates <= MAX_CANDIDATES
        assert fixture.source_document().content == fixture.content


def test_must_have_and_unacceptable_expectations_are_documented():
    labels_a = {item.label for item in FIXTURE_A.must_include}
    assert labels_a == {"se rendre compte de", "il faut / falloir", "stratégie"}
    assert "bonjour" in FIXTURE_A.must_not_hallucinate
    labels_c = {item.label for item in FIXTURE_C.must_include}
    assert "prendre rendez-vous" in labels_c
    labels_d = {item.label for item in FIXTURE_D.must_include}
    assert labels_d == {"aller", "faire", "passé composé"}
    for item in FIXTURE_D.must_include:
        if item.label in {"aller", "faire"}:
            assert "conjugation" in item.item_types


def test_valid_fixture_a_extraction_passes_contract_and_must_haves(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    fake = FakeLearningItemExtractor(result=_result(_good_a()))
    reports = evaluate_with_extractor(fake, [FIXTURE_A])
    report = reports[0]
    assert report.contract_passed
    assert report.must_have_recall == 1.0
    assert report.hallucination_count == 0
    assert report.duplicate_count == 0
    assert report.over_extracted is False
    assert report.provider == "openai"
    assert report.model == "gpt-4o-mini"
    assert report.extraction_version == EXTRACTION_VERSION
    assert report.type_counts["expression"] == 1
    assert report.type_counts["vocabulary"] == 1
    assert report.type_counts["grammar"] == 1


def test_acceptable_variant_se_rendre_compte_counts_as_must_have():
    content = FIXTURE_A.content
    source = FIXTURE_A.source_document()
    variant = _extracted(
        content,
        item_type="expression",
        canonical_form="se rendre compte",
        meaning_ja="〜に気づく",
        fragment="rendu compte",
    )
    result = ExtractionService(
        FakeLearningItemExtractor(result=_result((variant,)))
    ).extract(source)
    report = evaluate_extraction(FIXTURE_A, result, source=source)
    assert "se rendre compte de" not in report.missing_must_haves
    assert report.must_have_found >= 1


def test_evidence_span_out_of_range_fails_contract():
    source = FIXTURE_A.source_document()
    bad = _candidate(
        source,
        canonical_form="stratégie",
        start=0,
        end=len(source.content) + 8,
    )
    report = evaluate_extraction(FIXTURE_A, _snapshot(source, (bad,)), source=source)
    names = {check.name: check.passed for check in report.contract_checks}
    assert names["evidence_span_in_range"] is False
    assert report.contract_passed is False
    assert report.hallucination_count >= 1


def test_evidence_is_reconstructable_from_source_slice():
    source = FIXTURE_B.source_document()
    start = source.content.index("pomme")
    good = _candidate(
        source,
        canonical_form="pomme",
        meaning_ja="りんご",
        start=start,
        end=start + len("pomme"),
    )
    report = evaluate_extraction(FIXTURE_B, _snapshot(source, (good,)), source=source)
    names = {check.name: check.passed for check in report.contract_checks}
    assert names["evidence_reconstructable"] is True
    assert names["evidence_span_in_range"] is True
    assert names["required_fields"] is True
    assert names["known_item_type"] is True


def test_duplicate_keys_fail_contract_and_are_counted():
    source = FIXTURE_B.source_document()
    start = source.content.index("pomme")
    first = _candidate(source, start=start, end=start + 5, confidence=0.4)
    second = _candidate(source, start=start, end=start + 5, confidence=0.9)
    report = evaluate_extraction(
        FIXTURE_B,
        _snapshot(
            source,
            (first, second),
            exclusions=(
                CandidateExclusion(
                    reason="duplicate",
                    detail="dup",
                    source_index=0,
                    item_type="vocabulary",
                    canonical_form="pomme",
                ),
            ),
        ),
        source=source,
    )
    names = {check.name: check.passed for check in report.contract_checks}
    assert names["no_duplicate_keys"] is False
    assert report.duplicate_count == 1


def test_candidate_count_limit_is_checked():
    source = FIXTURE_B.source_document()
    start = source.content.index("pomme")
    overflow = tuple(
        _candidate(
            source,
            canonical_form=f"pomme-{index}",
            start=start,
            end=start + 5,
        )
        for index in range(MAX_CANDIDATES + 1)
    )
    report = evaluate_extraction(FIXTURE_B, _snapshot(source, overflow), source=source)
    names = {check.name: check.passed for check in report.contract_checks}
    assert names["candidate_count_within_limit"] is False


def test_obvious_hallucination_and_forbidden_forms_are_detected():
    source = FIXTURE_A.source_document()
    hello_start = 0
    hello = _candidate(
        source,
        item_type="expression",
        canonical_form="bonjour tout le monde",
        meaning_ja="こんにちは",
        start=hello_start,
        end=hello_start + 2,
    )
    pomme = _candidate(
        source,
        item_type="vocabulary",
        canonical_form="pomme",
        meaning_ja="りんご",
        start=hello_start,
        end=hello_start + 2,
    )
    report = evaluate_extraction(
        FIXTURE_A, _snapshot(source, (hello, pomme)), source=source
    )
    forms = {item.canonical_form for item in report.hallucinations}
    assert "bonjour tout le monde" in forms
    assert "pomme" in forms
    assert report.hallucination_count == 2


def test_fixture_b_detects_over_extraction():
    content = FIXTURE_B.content
    extras = [
        _extracted(
            content,
            item_type="vocabulary",
            canonical_form="pomme",
            meaning_ja="りんご",
            fragment="pomme",
        ),
        _extracted(
            content,
            item_type="conjugation",
            canonical_form="manger",
            meaning_ja="食べる",
            fragment="mange",
        ),
        _extracted(
            content,
            item_type="grammar",
            canonical_form="article indéfini",
            meaning_ja="不定冠詞",
            fragment="une",
        ),
        _extracted(
            content,
            item_type="vocabulary",
            canonical_form="je",
            meaning_ja="私は",
            fragment="Je",
        ),
        _extracted(
            content,
            item_type="grammar",
            canonical_form="présent",
            meaning_ja="現在",
            fragment="mange",
        ),
        _extracted(
            content,
            item_type="vocabulary",
            canonical_form="une pomme",
            meaning_ja="りんご1個",
            fragment="une pomme",
        ),
        _extracted(
            content,
            item_type="expression",
            canonical_form="je mange",
            meaning_ja="私は食べる",
            fragment="Je mange",
        ),
    ]
    source = FIXTURE_B.source_document()
    result = ExtractionService(
        FakeLearningItemExtractor(result=_result(tuple(extras)))
    ).extract(source)
    report = evaluate_extraction(FIXTURE_B, result, source=source)
    assert report.over_extracted is True
    assert report.candidate_count > FIXTURE_B.max_candidates


def test_fixture_c_requires_phrase_not_just_vocabulary():
    content = FIXTURE_C.content
    only_word = _extracted(
        content,
        item_type="vocabulary",
        canonical_form="rendez-vous",
        meaning_ja="約束",
        fragment="rendez-vous",
    )
    source = FIXTURE_C.source_document()
    result = ExtractionService(
        FakeLearningItemExtractor(result=_result((only_word,)))
    ).extract(source)
    report = evaluate_extraction(FIXTURE_C, result, source=source)
    assert "prendre rendez-vous" in report.missing_must_haves


def test_fixture_d_surface_form_vocabulary_does_not_satisfy_conjugation():
    content = FIXTURE_D.content
    surface = _extracted(
        content,
        item_type="vocabulary",
        canonical_form="allé",
        meaning_ja="行った",
        fragment="allé",
    )
    source = FIXTURE_D.source_document()
    result = ExtractionService(
        FakeLearningItemExtractor(result=_result((surface,)))
    ).extract(source)
    report = evaluate_extraction(FIXTURE_D, result, source=source)
    assert "aller" in report.missing_must_haves


def test_irregular_lemma_is_not_flagged_as_hallucination():
    content = FIXTURE_D.content
    aller = _extracted(
        content,
        item_type="conjugation",
        canonical_form="aller",
        meaning_ja="行く",
        fragment="allé",
    )
    source = FIXTURE_D.source_document()
    result = ExtractionService(
        FakeLearningItemExtractor(result=_result((aller,)))
    ).extract(source)
    report = evaluate_extraction(FIXTURE_D, result, source=source)
    assert report.hallucination_count == 0
    assert "aller" not in report.missing_must_haves


def test_report_keeps_provider_model_and_prompt_version():
    fake = FakeLearningItemExtractor(
        result=_result(
            _good_a()[:1],
            provider="openai",
            model="gpt-4o-mini",
            extraction_version=EXTRACTION_VERSION,
        )
    )
    report = evaluate_with_extractor(fake, [FIXTURE_A])[0]
    payload = json.loads(reports_to_json([report]))
    assert payload["provider"] == "openai"
    assert payload["model"] == "gpt-4o-mini"
    assert payload["extraction_version"] == EXTRACTION_VERSION
    text = format_text_report([report])
    assert EXTRACTION_VERSION in text
    assert "provider: openai" in text


def test_quality_modules_do_not_import_openai():
    import app.evaluation.extraction_fixtures as fixtures_module
    import app.evaluation.extraction_quality as quality_module

    for module in (fixtures_module, quality_module):
        tree = ast.parse(inspect.getsource(module))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".", 1)[0])
        assert "openai" not in names


def test_select_fixtures_and_strict_failure_helpers():
    assert select_fixtures("all") == EXTRACTION_QUALITY_FIXTURES
    assert select_fixtures("b")[0] is FIXTURE_B
    with pytest.raises(KeyError):
        get_fixture("Z")
    fake = FakeLearningItemExtractor(result=_result(_good_a()[:1]))
    reports = evaluate_with_extractor(fake, [FIXTURE_A])
    assert reports_failed_strict(reports) is True


@pytest.mark.live_llm
@pytest.mark.skipif(os.environ.get("RUN_LIVE_LLM") != "1", reason="opt-in live LLM")
def test_live_llm_evaluation_is_opt_in():
    from app.services.openai_extractor import OpenAILearningItemExtractor

    reports = evaluate_with_extractor(OpenAILearningItemExtractor(), [FIXTURE_B])
    assert reports[0].provider
    assert reports[0].model
    assert reports[0].extraction_version == EXTRACTION_VERSION
    assert reports[0].contract_passed
