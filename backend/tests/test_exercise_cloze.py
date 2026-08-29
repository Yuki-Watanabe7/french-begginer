"""Source evidence からの cloze Exercise 生成（Issue #147）のテスト。

検証方針:
  - vocabulary / expression / grammar / conjugation で cloze を生成できる
  - 正解は Source 本文 slice から再構成し、LLM raw text を使わない
  - source 外 span / 空 evidence / Source 不存在 / SourceRef なしを拒否する
  - context 長に上限がある
  - 複数 SourceRef の選択が deterministic
  - apostrophe / Unicode / 改行を壊さない
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from app.domain.exercise import EXERCISE_VERSION
from app.domain.exercise_generation import (
    CLOZE_BLANK,
    CLOZE_CONTEXT_MAX_CHARS,
    blank_source_span,
    generate_exercise,
    select_cloze_source_ref,
)
from app.domain.tutor import (
    EvidenceSpan,
    LearningItem,
    LearningItemType,
    SourceDocument,
    SourceRef,
)

FIXTURE_CONTENT = "Je me suis rendu compte qu'il fallait changer de stratégie."
EVIDENCE = "rendu compte"


def _span_for(content: str, fragment: str) -> EvidenceSpan:
    start = content.index(fragment)
    return EvidenceSpan(start=start, end=start + len(fragment), text="LLM-RAW-WRONG")


def _source(
    *,
    source_id: str = "src-1",
    content: str = FIXTURE_CONTENT,
    created_at: datetime | None = None,
) -> SourceDocument:
    return SourceDocument(
        id=source_id,
        title="fixture",
        content=content,
        created_at=created_at or datetime(2026, 1, 1, tzinfo=UTC),
    )


def _item(
    *,
    item_id: str,
    item_type: LearningItemType,
    canonical_form: str,
    meaning_ja: str,
    source: SourceDocument | None = None,
    fragment: str = EVIDENCE,
    extra_refs: list[SourceRef] | None = None,
) -> LearningItem:
    refs: list[SourceRef] = []
    if source is not None:
        refs.append(
            SourceRef(
                source_document_id=source.id,
                evidence_span=_span_for(source.content, fragment),
            )
        )
    if extra_refs:
        refs.extend(extra_refs)
    return LearningItem(
        id=item_id,
        item_type=item_type,
        canonical_form=canonical_form,
        meaning_ja=meaning_ja,
        source_refs=refs,
    )


def _cloze(
    item: LearningItem,
    sources: list[SourceDocument] | dict[str, SourceDocument],
    *,
    cloze_context_max_chars: int = CLOZE_CONTEXT_MAX_CHARS,
):
    return generate_exercise(
        item,
        "cloze",
        seed="fixed",
        sources=sources,
        cloze_context_max_chars=cloze_context_max_chars,
    )


@pytest.mark.parametrize(
    ("item_type", "item_id", "canonical_form", "meaning_ja", "fragment"),
    [
        ("vocabulary", "v-strategie", "stratégie", "戦略", "stratégie"),
        (
            "expression",
            "e-se-rendre",
            "se rendre compte de",
            "〜に気づく",
            "rendu compte",
        ),
        ("grammar", "g-fallait", "il fallait", "しなければならなかった", "fallait"),
        ("conjugation", "c-changer", "changer", "変える", "changer"),
    ],
)
def test_cloze_is_generated_for_four_item_types(
    item_type: LearningItemType,
    item_id: str,
    canonical_form: str,
    meaning_ja: str,
    fragment: str,
):
    source = _source()
    item = _item(
        item_id=item_id,
        item_type=item_type,
        canonical_form=canonical_form,
        meaning_ja=meaning_ja,
        source=source,
        fragment=fragment,
    )
    result = _cloze(item, [source])
    assert result.eligible is True
    assert result.exercise is not None
    spec = result.exercise.spec
    public = result.exercise.to_public()
    expected = fragment
    assert spec.exercise_type == "cloze"
    assert spec.skill_direction == "production"
    assert spec.response_kind == "text"
    assert spec.options is None
    assert CLOZE_BLANK in spec.prompt
    assert fragment not in spec.prompt
    assert expected not in spec.prompt
    assert spec.source_context is not None
    assert CLOZE_BLANK in spec.source_context
    assert result.exercise.answer_key.expected_answers == (expected,)
    assert expected not in public.prompt
    assert "expected" not in public.model_dump()
    assert "metadata" not in public.model_dump()


def test_cloze_answer_is_reconstructed_from_source_slice_not_llm_text():
    source = _source()
    item = _item(
        item_id="e-se-rendre",
        item_type="expression",
        canonical_form="se rendre compte de",
        meaning_ja="〜に気づく",
        source=source,
        fragment="rendu compte",
    )
    result = _cloze(item, [source])
    assert result.exercise is not None
    span = item.source_refs[0].evidence_span
    assert span is not None
    assert span.text == "LLM-RAW-WRONG"
    sliced = source.content[span.start : span.end]
    assert sliced == "rendu compte"
    assert result.exercise.answer_key.expected_answers == (sliced,)
    assert "LLM-RAW-WRONG" not in result.exercise.spec.prompt
    assert "se rendre compte de" not in result.exercise.answer_key.expected_answers
    assert result.exercise.spec.prompt == (
        "次の空欄に入るフランス語を、原文のまま書いてください。\n\n"
        "Je me suis ____ qu'il fallait changer de stratégie."
    )


def test_cloze_rejects_span_outside_source():
    source = _source()
    item = LearningItem(
        id="v-bad",
        item_type="vocabulary",
        canonical_form="livre",
        meaning_ja="本",
        source_refs=[
            SourceRef(
                source_document_id=source.id,
                evidence_span=EvidenceSpan(start=0, end=len(source.content) + 8),
            )
        ],
    )
    result = _cloze(item, [source])
    assert result.eligible is False
    assert result.skip_reason == "evidence_span_out_of_range"
    assert result.exercise is None


def test_cloze_caps_context_length():
    filler = "α" * 80
    content = f"{filler} rendu compte {filler}"
    source = _source(content=content)
    item = _item(
        item_id="e-se-rendre",
        item_type="expression",
        canonical_form="se rendre compte de",
        meaning_ja="〜に気づく",
        source=source,
        fragment="rendu compte",
    )
    result = _cloze(item, [source], cloze_context_max_chars=40)
    assert result.eligible is True
    assert result.exercise is not None
    spec = result.exercise.spec
    context = spec.source_context
    assert context is not None
    window_len = (
        spec.metadata["context_window_end"] - spec.metadata["context_window_start"]
    )
    assert window_len <= 40
    assert window_len < len(content)
    assert CLOZE_BLANK in context
    assert content not in context
    assert result.exercise.answer_key.expected_answers == ("rendu compte",)
    assert "α" in context


def test_cloze_uses_containing_sentence_instead_of_full_long_source():
    sentence = FIXTURE_CONTENT
    content = ("Avant. " * 30) + sentence + (" Après. " * 30)
    source = _source(content=content)
    item = _item(
        item_id="e-se-rendre",
        item_type="expression",
        canonical_form="se rendre compte de",
        meaning_ja="〜に気づく",
        source=source,
        fragment="rendu compte",
    )
    result = _cloze(item, [source])
    assert result.eligible is True
    assert result.exercise is not None
    context = result.exercise.spec.source_context
    assert context == "Je me suis ____ qu'il fallait changer de stratégie."
    assert "Avant" not in context
    assert "Après" not in context
    assert len(content) > CLOZE_CONTEXT_MAX_CHARS


def test_multiple_source_refs_choose_oldest_deterministically():
    older_content = "Je me suis rendu compte qu'il fallait changer."
    newer_content = "Elle s'est rendu compte de la stratégie."
    older = _source(
        source_id="src-old",
        content=older_content,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    newer = _source(
        source_id="src-new",
        content=newer_content,
        created_at=datetime(2026, 6, 1, tzinfo=UTC),
    )
    item = LearningItem(
        id="e-se-rendre",
        item_type="expression",
        canonical_form="se rendre compte de",
        meaning_ja="〜に気づく",
        source_refs=[
            SourceRef(
                source_document_id=newer.id,
                evidence_span=_span_for(newer_content, "rendu compte"),
            ),
            SourceRef(
                source_document_id=older.id,
                evidence_span=_span_for(older_content, "rendu compte"),
            ),
        ],
    )
    first = _cloze(item, [newer, older])
    second = _cloze(item, {"src-new": newer, "src-old": older})
    selected = select_cloze_source_ref(item, [newer, older])
    assert selected is not None
    assert selected.source_document_id == older.id
    assert first.exercise is not None
    assert second.exercise is not None
    assert first.exercise.spec.prompt == second.exercise.spec.prompt
    assert first.exercise.spec.metadata["source_document_id"] == older.id
    assert "Je me suis ____" in first.exercise.spec.prompt
    assert "Elle s'est" not in first.exercise.spec.prompt


def test_same_created_at_breaks_ties_by_source_id():
    content_a = "alpha rendu compte ici."
    content_b = "beta rendu compte là."
    created = datetime(2026, 3, 1, tzinfo=UTC)
    source_b = _source(source_id="src-b", content=content_b, created_at=created)
    source_a = _source(source_id="src-a", content=content_a, created_at=created)
    item = LearningItem(
        id="e-tie",
        item_type="expression",
        canonical_form="se rendre compte de",
        meaning_ja="〜に気づく",
        source_refs=[
            SourceRef(
                source_document_id=source_b.id,
                evidence_span=_span_for(content_b, "rendu compte"),
            ),
            SourceRef(
                source_document_id=source_a.id,
                evidence_span=_span_for(content_a, "rendu compte"),
            ),
        ],
    )
    result = _cloze(item, [source_b, source_a])
    assert result.exercise is not None
    assert result.exercise.spec.metadata["source_document_id"] == "src-a"
    assert "alpha ____ ici." in result.exercise.spec.prompt


def test_cloze_preserves_apostrophe_unicode_and_newlines():
    content = "Aujourd'hui c'est l'heure.\nIl faut changer de stratégie."
    source = _source(content=content)
    item = _item(
        item_id="v-heure",
        item_type="vocabulary",
        canonical_form="heure",
        meaning_ja="時間",
        source=source,
        fragment="l'heure",
    )
    result = _cloze(item, [source])
    assert result.exercise is not None
    spec = result.exercise.spec
    assert result.exercise.answer_key.expected_answers == ("l'heure",)
    assert "Aujourd'hui c'est ____." in spec.prompt
    assert "\n" in spec.prompt
    assert "stratégie" in spec.prompt
    unicode_source = _source(
        source_id="src-unicode",
        content="La stratégie d’accord.",
    )
    unicode_item = _item(
        item_id="v-strategie",
        item_type="vocabulary",
        canonical_form="stratégie",
        meaning_ja="戦略",
        source=unicode_source,
        fragment="stratégie",
    )
    unicode_result = _cloze(unicode_item, [unicode_source])
    assert unicode_result.exercise is not None
    assert unicode_result.exercise.answer_key.expected_answers == ("stratégie",)
    assert "La ____ d’accord." in unicode_result.exercise.spec.prompt


def test_cloze_skips_item_without_source_ref():
    item = LearningItem(
        id="v-livre",
        item_type="vocabulary",
        canonical_form="livre",
        meaning_ja="本",
    )
    result = _cloze(item, [])
    assert result.eligible is False
    assert result.skip_reason == "missing_source_evidence"
    assert result.exercise is None


def test_cloze_skips_missing_source_document():
    item = LearningItem(
        id="v-livre",
        item_type="vocabulary",
        canonical_form="livre",
        meaning_ja="本",
        source_refs=[
            SourceRef(
                source_document_id="missing-source",
                evidence_span=EvidenceSpan(start=0, end=5),
            )
        ],
    )
    result = _cloze(item, [])
    assert result.skip_reason == "source_not_found"
    assert result.exercise is None


def test_cloze_skips_whitespace_only_evidence():
    content = "abc   def"
    source = _source(content=content)
    spaces = content.index("   ")
    item = LearningItem(
        id="v-space",
        item_type="vocabulary",
        canonical_form="espace",
        meaning_ja="空白",
        source_refs=[
            SourceRef(
                source_document_id=source.id,
                evidence_span=EvidenceSpan(start=spaces, end=spaces + 3),
            )
        ],
    )
    result = _cloze(item, [source])
    assert result.skip_reason == "evidence_span_empty"
    assert result.exercise is None


def test_cloze_skips_when_context_cannot_be_built():
    source = _source(content="rendu compte")
    item = _item(
        item_id="e-only",
        item_type="expression",
        canonical_form="se rendre compte de",
        meaning_ja="〜に気づく",
        source=source,
        fragment="rendu compte",
    )
    result = _cloze(item, [source])
    assert result.skip_reason == "context_unavailable"
    assert result.exercise is None

    long_evidence = "x" * 80
    long_source = _source(source_id="src-long", content=f"aa{long_evidence}bb")
    long_item = _item(
        item_id="v-long",
        item_type="vocabulary",
        canonical_form="xxxx",
        meaning_ja="長い",
        source=long_source,
        fragment=long_evidence,
    )
    too_small = _cloze(long_item, [long_source], cloze_context_max_chars=40)
    assert too_small.skip_reason == "context_unavailable"


def test_invalid_source_is_skipped_in_favor_of_valid_older_source():
    valid = _source(
        source_id="src-valid",
        content=FIXTURE_CONTENT,
        created_at=datetime(2026, 2, 1, tzinfo=UTC),
    )
    item = LearningItem(
        id="e-se-rendre",
        item_type="expression",
        canonical_form="se rendre compte de",
        meaning_ja="〜に気づく",
        source_refs=[
            SourceRef(
                source_document_id="missing-source",
                evidence_span=EvidenceSpan(start=0, end=5),
            ),
            SourceRef(
                source_document_id=valid.id,
                evidence_span=_span_for(FIXTURE_CONTENT, "rendu compte"),
            ),
        ],
    )
    result = _cloze(item, [valid])
    assert result.eligible is True
    assert result.exercise is not None
    assert result.exercise.spec.metadata["source_document_id"] == valid.id


def test_blank_uses_span_slice_not_string_replace():
    content = "rendu compte puis encore rendu compte"
    blanked = blank_source_span(content, 0, len("rendu compte"))
    assert blanked.startswith(CLOZE_BLANK)
    assert blanked.endswith("rendu compte")
    assert blanked.count("rendu compte") == 1


def test_cloze_generation_works_without_openai_api_key(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert os.environ.get("OPENAI_API_KEY") is None
    source = _source()
    item = _item(
        item_id="e-se-rendre",
        item_type="expression",
        canonical_form="se rendre compte de",
        meaning_ja="〜に気づく",
        source=source,
    )
    result = _cloze(item, [source])
    assert result.eligible is True
    assert result.exercise is not None
    assert result.exercise.spec.exercise_version == EXERCISE_VERSION
