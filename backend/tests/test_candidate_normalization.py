"""Candidate normalization pipeline（Issue #133）の単体テスト。

固定 Source と固定 Candidate（fake LLM 相当）で deterministic に検証する。
"""

from __future__ import annotations

import ast
import inspect
import unicodedata

from app.domain.candidate_normalization import (
    NORMALIZATION_VERSION,
    candidate_normalization_key,
    item_normalization_key,
    learning_item_normalization_key,
    normalize_candidates,
    normalize_canonical_form,
)
from app.domain.tutor import (
    EvidenceSpan,
    LearningItem,
    LearningItemCandidate,
    SourceDocument,
)

CONTENT = "Je me suis rendu compte qu'il fallait changer de strategie."


def _source() -> SourceDocument:
    return SourceDocument(title="記事", content=CONTENT)


def _span_for(fragment: str) -> EvidenceSpan:
    start = CONTENT.index(fragment)
    return EvidenceSpan(start=start, end=start + len(fragment))


def _candidate(
    source: SourceDocument | None = None,
    **overrides,
) -> LearningItemCandidate:
    source = source or _source()
    values = {
        "source_document_id": source.id,
        "item_type": "expression",
        "canonical_form": "se rendre compte",
        "meaning_ja": "〜に気づく",
        "evidence_span": _span_for("rendu compte"),
        "extraction_version": "extract-v1",
        "confidence": 0.9,
    }
    values.update(overrides)
    return LearningItemCandidate(**values)


def test_valid_span_is_kept():
    source = _source()
    result = normalize_candidates(source, [_candidate(source)])
    assert len(result.candidates) == 1
    assert result.exclusions == ()
    kept = result.candidates[0]
    assert kept.canonical_form == "se rendre compte"
    assert kept.metadata["normalization_key"] == item_normalization_key(
        "expression", "se rendre compte"
    )
    assert kept.metadata["normalization_version"] == NORMALIZATION_VERSION


def test_span_outside_source_is_excluded():
    source = _source()
    result = normalize_candidates(
        source,
        [
            _candidate(source),
            _candidate(
                source,
                canonical_form="hors texte",
                evidence_span=EvidenceSpan(start=0, end=len(CONTENT) + 5),
            ),
        ],
    )
    assert [c.canonical_form for c in result.candidates] == ["se rendre compte"]
    assert len(result.exclusions) == 1
    assert result.exclusions[0].reason == "evidence_span_out_of_range"
    assert result.exclusions[0].source_index == 1


def test_whitespace_only_span_is_excluded():
    content = "abc   def"
    source = SourceDocument(title="空白", content=content)
    space_start = content.index("   ")
    result = normalize_candidates(
        source,
        [
            _candidate(
                source,
                evidence_span=EvidenceSpan(start=space_start, end=space_start + 3),
            )
        ],
    )
    assert result.candidates == ()
    assert result.exclusions[0].reason == "evidence_span_empty"


def test_duplicate_candidates_are_merged_to_one():
    source = _source()
    result = normalize_candidates(
        source,
        [
            _candidate(source, confidence=0.4),
            _candidate(source, confidence=0.9),
            _candidate(source, confidence=0.5),
        ],
    )
    assert len(result.candidates) == 1
    assert result.candidates[0].confidence == 0.9
    assert result.candidates[0].metadata["merged_count"] == 3
    assert [e.reason for e in result.exclusions] == ["duplicate", "duplicate"]
    assert {e.source_index for e in result.exclusions} == {0, 2}


def test_case_and_whitespace_differences_do_not_duplicate():
    source = _source()
    result = normalize_candidates(
        source,
        [
            _candidate(source, canonical_form="  Se Rendre Compte  "),
            _candidate(source, canonical_form="se rendre compte"),
        ],
    )
    assert len(result.candidates) == 1
    assert result.exclusions[0].reason == "duplicate"
    key = candidate_normalization_key(result.candidates[0])
    assert key == item_normalization_key("expression", "se rendre compte")


def test_different_item_types_are_not_merged():
    source = _source()
    result = normalize_candidates(
        source,
        [
            _candidate(
                source,
                item_type="vocabulary",
                canonical_form="changer",
                evidence_span=_span_for("changer"),
            ),
            _candidate(
                source,
                item_type="conjugation",
                canonical_form="changer",
                evidence_span=_span_for("changer"),
            ),
        ],
    )
    assert {c.item_type for c in result.candidates} == {"vocabulary", "conjugation"}
    assert result.exclusions == ()
    conjugation = next(c for c in result.candidates if c.item_type == "conjugation")
    assert conjugation.metadata["lemma"] == "changer"
    assert "tense" not in conjugation.metadata


def test_conjugation_tense_and_mood_are_canonicalized():
    source = _source()
    result = normalize_candidates(
        source,
        [
            _candidate(
                source,
                item_type="conjugation",
                canonical_form="parler",
                evidence_span=_span_for("changer"),
                metadata={"tense": "Présent", "mood": "Indicatif"},
            )
        ],
    )
    kept = result.candidates[0]
    assert kept.metadata["lemma"] == "parler"
    assert kept.metadata["tense"] == "présent"
    assert kept.metadata["mood"] == "indicatif"


def test_conjugation_unknown_tense_is_not_persisted():
    source = _source()
    result = normalize_candidates(
        source,
        [
            _candidate(
                source,
                item_type="conjugation",
                canonical_form="parler",
                evidence_span=_span_for("changer"),
                metadata={"tense": "not-a-real-tense", "mood": "mystery"},
            )
        ],
    )
    kept = result.candidates[0]
    assert kept.metadata["lemma"] == "parler"
    assert "tense" not in kept.metadata
    assert "mood" not in kept.metadata
    assert result.exclusions == ()


def test_normalization_is_deterministic():
    source = _source()
    candidates = [
        _candidate(source, canonical_form="« se rendre compte »"),
        _candidate(
            source,
            item_type="vocabulary",
            canonical_form="strategie",
            evidence_span=_span_for("strategie"),
        ),
    ]
    first = normalize_candidates(source, candidates)
    second = normalize_candidates(source, candidates)
    assert [c.canonical_form for c in first.candidates] == [
        c.canonical_form for c in second.candidates
    ]
    assert [c.metadata["normalization_key"] for c in first.candidates] == [
        c.metadata["normalization_key"] for c in second.candidates
    ]
    assert [e.reason for e in first.exclusions] == [e.reason for e in second.exclusions]


def test_exclusion_reasons_are_inspectable():
    source = _source()
    result = normalize_candidates(
        source,
        [
            _candidate(
                source,
                canonical_form="   ",
                evidence_span=_span_for("changer"),
            ),
            _candidate(
                source,
                item_type="vocabulary",
                canonical_form="je me suis rendu compte",
                evidence_span=_span_for("rendu compte"),
            ),
            _candidate(
                source,
                evidence_span=EvidenceSpan(start=0, end=len(CONTENT) + 1),
            ),
        ],
    )
    reasons = [e.reason for e in result.exclusions]
    assert "empty_canonical_form" in reasons
    assert "vocabulary_context_fragment" in reasons
    assert "evidence_span_out_of_range" in reasons
    assert all(e.detail for e in result.exclusions)
    assert result.candidates == ()


def test_normalization_key_matches_existing_learning_item():
    candidate_key = item_normalization_key("expression", "  SE RENDRE COMPTE  ")
    item = LearningItem(
        item_type="expression",
        canonical_form="se rendre compte",
        meaning_ja="〜に気づく",
    )
    assert learning_item_normalization_key(item) == candidate_key
    assert candidate_key.startswith(f"{NORMALIZATION_VERSION}:expression:")


def test_unicode_nfc_normalization_is_applied():
    decomposed = "strate" + "\u0301" + "gie"
    composed = unicodedata.normalize("NFC", decomposed)
    assert normalize_canonical_form(decomposed) == composed
    assert item_normalization_key("vocabulary", decomposed) == item_normalization_key(
        "vocabulary", composed
    )


def test_wrapping_quotes_are_stripped():
    assert normalize_canonical_form('"se rendre compte"') == "se rendre compte"
    assert normalize_canonical_form("« se rendre compte »") == "se rendre compte"


def test_vocabulary_context_fragment_is_excluded():
    source = _source()
    result = normalize_candidates(
        source,
        [
            _candidate(
                source,
                item_type="vocabulary",
                canonical_form="pomme de terre",
                evidence_span=_span_for("changer"),
            ),
            _candidate(
                source,
                item_type="vocabulary",
                canonical_form="je me suis rendu",
                evidence_span=_span_for("rendu compte"),
            ),
        ],
    )
    assert [c.canonical_form for c in result.candidates] == ["pomme de terre"]
    assert result.exclusions[0].reason == "vocabulary_context_fragment"


def test_module_does_not_depend_on_embeddings():
    import app.domain.candidate_normalization as module

    tree = ast.parse(inspect.getsource(module))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".", 1)[0])
    forbidden = {
        "numpy",
        "sklearn",
        "openai",
        "chromadb",
        "faiss",
        "sentence_transformers",
        "tiktoken",
    }
    assert names.isdisjoint(forbidden)
    assert "unicodedata" in names
