"""LLM抽出結果に対する deterministic な品質チェック（Issue #136）。

CI の pass/fail はここを主根拠にする。LLM-as-judge は使わない。
同じ入力からは常に同じ QualityReport になる。
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Protocol

from app.domain.candidate_normalization import (
    CandidateExclusion,
    candidate_normalization_key,
    normalize_canonical_form,
)
from app.domain.tutor import LearningItemCandidate, SourceDocument, read_source_evidence
from app.evaluation.extraction_fixtures import (
    ALLOWED_ITEM_TYPES,
    ExtractionQualityFixture,
    MustHaveExpectation,
)
from app.services.extraction_prompt import MAX_CANDIDATES

_TOKEN_RE = re.compile(r"[0-9A-Za-zÀ-ÿŒœÆæ'-]+")
_FUNCTION_WORDS = frozenset(
    {
        "a",
        "ai",
        "au",
        "aux",
        "ce",
        "ces",
        "d",
        "de",
        "des",
        "du",
        "et",
        "il",
        "j",
        "je",
        "l",
        "la",
        "le",
        "les",
        "me",
        "ne",
        "pas",
        "que",
        "qui",
        "se",
        "te",
        "tu",
        "un",
        "une",
        "y",
        "à",
    }
)


class ExtractionSnapshot(Protocol):
    """ExtractionResult とテスト用の偽結果が満たす最小契約。"""

    candidates: tuple[LearningItemCandidate, ...]
    exclusions: tuple[CandidateExclusion, ...]
    provider: str
    model: str
    extraction_version: str


@dataclass(frozen=True)
class ContractCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class HallucinationFinding:
    canonical_form: str
    item_type: str
    reason: str


@dataclass(frozen=True)
class FixtureQualityReport:
    fixture_id: str
    title: str
    provider: str
    model: str
    extraction_version: str
    candidate_count: int
    duplicate_count: int
    hallucination_count: int
    evidence_invalid_count: int
    type_counts: dict[str, int]
    must_have_found: int
    must_have_total: int
    must_have_recall: float
    missing_must_haves: tuple[str, ...]
    over_extracted: bool
    contract_passed: bool
    contract_checks: tuple[ContractCheck, ...]
    hallucinations: tuple[HallucinationFinding, ...]
    issues: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["missing_must_haves"] = list(self.missing_must_haves)
        payload["contract_checks"] = [asdict(item) for item in self.contract_checks]
        payload["hallucinations"] = [asdict(item) for item in self.hallucinations]
        payload["issues"] = list(self.issues)
        return payload


def evaluate_extraction(
    fixture: ExtractionQualityFixture,
    result: ExtractionSnapshot,
    *,
    source: SourceDocument | None = None,
) -> FixtureQualityReport:
    """fixture に対する抽出結果を deterministic に採点する。"""
    source = source or fixture.source_document()
    candidates = result.candidates
    type_counts = dict(Counter(candidate.item_type for candidate in candidates))
    duplicate_count = sum(
        1 for exclusion in result.exclusions if exclusion.reason == "duplicate"
    )
    evidence_invalid_count = sum(
        1
        for exclusion in result.exclusions
        if exclusion.reason in {"evidence_span_out_of_range", "evidence_span_empty"}
    )

    contract_checks = _contract_checks(source, candidates)
    contract_passed = all(check.passed for check in contract_checks)
    hallucinations = _hallucination_findings(fixture, source, candidates)
    found, missing = _must_have_coverage(fixture.must_include, candidates)
    over_extracted = len(candidates) > fixture.max_candidates

    issues: list[str] = []
    if not contract_passed:
        issues.append("deterministic contract failed")
    if missing:
        issues.append("missing must-have: " + ", ".join(missing))
    if hallucinations:
        issues.append(f"hallucination count={len(hallucinations)}")
    if over_extracted:
        issues.append(
            f"over-extraction: {len(candidates)} > max {fixture.max_candidates}"
        )
    if duplicate_count:
        issues.append(f"duplicate count={duplicate_count}")

    total = len(fixture.must_include)
    recall = (found / total) if total else 1.0
    return FixtureQualityReport(
        fixture_id=fixture.fixture_id,
        title=fixture.title,
        provider=result.provider,
        model=result.model,
        extraction_version=result.extraction_version,
        candidate_count=len(candidates),
        duplicate_count=duplicate_count,
        hallucination_count=len(hallucinations),
        evidence_invalid_count=evidence_invalid_count,
        type_counts=type_counts,
        must_have_found=found,
        must_have_total=total,
        must_have_recall=recall,
        missing_must_haves=tuple(missing),
        over_extracted=over_extracted,
        contract_passed=contract_passed,
        contract_checks=contract_checks,
        hallucinations=tuple(hallucinations),
        issues=tuple(issues),
    )


def reports_to_json(reports: Sequence[FixtureQualityReport]) -> str:
    """provider / model / prompt version を残す JSON。"""
    first = reports[0] if reports else None
    payload = {
        "provider": first.provider if first else None,
        "model": first.model if first else None,
        "extraction_version": first.extraction_version if first else None,
        "fixtures": [report.to_dict() for report in reports],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def format_text_report(reports: Sequence[FixtureQualityReport]) -> str:
    if not reports:
        return "評価対象の fixture がありません。"
    first = reports[0]
    lines = [
        f"provider: {first.provider}",
        f"model: {first.model}",
        f"extraction_version: {first.extraction_version}",
        "",
    ]
    for report in reports:
        types = (
            ", ".join(
                f"{item_type}={count}"
                for item_type, count in sorted(report.type_counts.items())
            )
            or "(none)"
        )
        lines.extend(
            [
                f"Fixture {report.fixture_id}: {report.title}",
                f"  candidates: {report.candidate_count}",
                (
                    f"  must-have recall: {report.must_have_found}/"
                    f"{report.must_have_total} ({report.must_have_recall:.2f})"
                ),
                f"  hallucinations: {report.hallucination_count}",
                f"  duplicates: {report.duplicate_count}",
                f"  evidence invalid: {report.evidence_invalid_count}",
                f"  types: {types}",
                f"  over-extracted: {report.over_extracted}",
                f"  contract: {'pass' if report.contract_passed else 'fail'}",
            ]
        )
        if report.missing_must_haves:
            lines.append("  missing: " + ", ".join(report.missing_must_haves))
        if report.issues:
            lines.append("  issues: " + "; ".join(report.issues))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def canonical_matches_variant(canonical_form: str, variant: str) -> bool:
    """正規化後の表記ゆれを許容する。完全一致リストにはしない。"""
    left = normalize_canonical_form(canonical_form).casefold()
    right = normalize_canonical_form(variant).casefold()
    if left == right:
        return True
    return left.startswith(right + " ") or right.startswith(left + " ")


def _must_have_coverage(
    expectations: Sequence[MustHaveExpectation],
    candidates: Sequence[LearningItemCandidate],
) -> tuple[int, list[str]]:
    missing: list[str] = []
    found = 0
    for expectation in expectations:
        if _find_must_have(expectation, candidates) is not None:
            found += 1
        else:
            missing.append(expectation.label)
    return found, missing


def _find_must_have(
    expectation: MustHaveExpectation,
    candidates: Sequence[LearningItemCandidate],
) -> LearningItemCandidate | None:
    for candidate in candidates:
        if candidate.item_type not in expectation.item_types:
            continue
        if any(
            canonical_matches_variant(candidate.canonical_form, variant)
            for variant in expectation.variants
        ):
            return candidate
    return None


def _contract_checks(
    source: SourceDocument,
    candidates: Sequence[LearningItemCandidate],
) -> tuple[ContractCheck, ...]:
    span_failures = 0
    reconstruct_failures = 0
    unknown_types = 0
    missing_fields = 0
    for candidate in candidates:
        if candidate.item_type not in ALLOWED_ITEM_TYPES:
            unknown_types += 1
        if _missing_required_fields(candidate):
            missing_fields += 1
        span_error = _evidence_span_error(source.content, candidate)
        if span_error == "out_of_range":
            span_failures += 1
        elif span_error == "not_reconstructable":
            reconstruct_failures += 1

    keys = [candidate_normalization_key(candidate) for candidate in candidates]
    duplicate_keys = len(keys) - len(set(keys))
    over_limit = len(candidates) > MAX_CANDIDATES

    return (
        ContractCheck(
            name="evidence_span_in_range",
            passed=span_failures == 0,
            detail=f"out_of_range={span_failures}",
        ),
        ContractCheck(
            name="evidence_reconstructable",
            passed=reconstruct_failures == 0,
            detail=f"not_reconstructable={reconstruct_failures}",
        ),
        ContractCheck(
            name="known_item_type",
            passed=unknown_types == 0,
            detail=f"unknown={unknown_types}",
        ),
        ContractCheck(
            name="required_fields",
            passed=missing_fields == 0,
            detail=f"missing={missing_fields}",
        ),
        ContractCheck(
            name="no_duplicate_keys",
            passed=duplicate_keys == 0,
            detail=f"duplicate_keys={duplicate_keys}",
        ),
        ContractCheck(
            name="candidate_count_within_limit",
            passed=not over_limit,
            detail=f"count={len(candidates)} limit={MAX_CANDIDATES}",
        ),
    )


def _hallucination_findings(
    fixture: ExtractionQualityFixture,
    source: SourceDocument,
    candidates: Sequence[LearningItemCandidate],
) -> list[HallucinationFinding]:
    findings: list[HallucinationFinding] = []
    forbidden = tuple(
        normalize_canonical_form(item).casefold()
        for item in fixture.must_not_hallucinate
    )
    for candidate in candidates:
        if _evidence_span_error(source.content, candidate) is not None:
            findings.append(
                HallucinationFinding(
                    canonical_form=candidate.canonical_form,
                    item_type=candidate.item_type,
                    reason="evidence is not reconstructable from the source",
                )
            )
            continue
        normalized = normalize_canonical_form(candidate.canonical_form).casefold()
        if any(
            canonical_matches_variant(candidate.canonical_form, item)
            or normalized == item
            for item in forbidden
        ):
            findings.append(
                HallucinationFinding(
                    canonical_form=candidate.canonical_form,
                    item_type=candidate.item_type,
                    reason="matches fixture must-not-hallucinate",
                )
            )
            continue
        if _is_obvious_ungrounded_phrase(candidate.canonical_form, source.content):
            findings.append(
                HallucinationFinding(
                    canonical_form=candidate.canonical_form,
                    item_type=candidate.item_type,
                    reason="canonical content words are absent from the source",
                )
            )
    return findings


def _is_obvious_ungrounded_phrase(canonical_form: str, content: str) -> bool:
    """複数語で、内容語が本文と一切重ならない場合だけ明白な hallucination。

    単一 lemma（être / faire 等）は表層形と一致しないことがあるため、
    ここでは減点しない。fixture の must-not と must-have で見る。
    """
    tokens = _content_tokens(canonical_form)
    if len(tokens) < 2:
        return False
    source_tokens = _all_tokens(content)
    return not any(
        _token_overlaps_source(token, content, source_tokens) for token in tokens
    )


def _token_overlaps_source(
    token: str, content: str, source_tokens: tuple[str, ...]
) -> bool:
    folded_content = _fold(content)
    if token in folded_content:
        return True
    prefix = token[:4] if len(token) >= 4 else token
    if len(prefix) < 3:
        return False
    return any(
        other.startswith(prefix) or token.startswith(other[:4])
        for other in source_tokens
    )


def _content_tokens(value: str) -> tuple[str, ...]:
    return tuple(
        token
        for token in _all_tokens(value)
        if token not in _FUNCTION_WORDS and len(token) >= 3
    )


def _all_tokens(value: str) -> tuple[str, ...]:
    return tuple(_fold(match.group(0)) for match in _TOKEN_RE.finditer(value))


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value.casefold())
    stripped = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    return stripped.replace("'", "").replace("’", "")


def _missing_required_fields(candidate: LearningItemCandidate) -> bool:
    if not candidate.canonical_form.strip():
        return True
    if not candidate.meaning_ja.strip():
        return True
    if not candidate.extraction_version.strip():
        return True
    return candidate.evidence_span is None


def _evidence_span_error(content: str, candidate: LearningItemCandidate) -> str | None:
    span = candidate.evidence_span
    if span.start < 0 or span.end > len(content) or span.end <= span.start:
        return "out_of_range"
    try:
        fragment = read_source_evidence(content, span)
    except ValueError:
        return "out_of_range"
    if fragment != content[span.start : span.end]:
        return "not_reconstructable"
    if fragment.strip() == "":
        return "not_reconstructable"
    return None
