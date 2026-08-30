"""conjugation LearningItem → 既存動詞活用 adapter（Issue #148）のテスト。

検証方針:
  - 既存対応動詞 + présent で adapter 可能
  - 未対応 lemma は skip
  - tense 不一致は skip
  - metadata 欠落を誤って présent 扱いしない
  - adapter 経由の正解が既存 domain データと一致
  - 既存活用データを複製しない
  - source cloze へ fallback できる
  - 生成が deterministic
"""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime

from app.domain.conjugation import CONJUGATIONS, get_correct_answer
from app.domain.conjugation_adapter import (
    ADAPTER_MOOD,
    build_conjugation_prompt_material,
    canonical_conjugation_mood,
    canonical_conjugation_tense,
    evaluate_conjugation_adapter,
    pronouns_for,
)
from app.domain.exercise import eligible_exercise_types, evaluate_exercise_eligibility
from app.domain.exercise_generation import (
    generate_exercise,
    generate_supported_exercises,
)
from app.domain.tutor import (
    EvidenceSpan,
    LearningItem,
    SourceDocument,
    SourceRef,
)

FIXTURE_CONTENT = "Je parle français tous les jours."
EVIDENCE = "parle"


def _span_for(content: str, fragment: str) -> EvidenceSpan:
    start = content.index(fragment)
    return EvidenceSpan(start=start, end=start + len(fragment))


def _source() -> SourceDocument:
    return SourceDocument(
        id="src-parler",
        title="fixture",
        content=FIXTURE_CONTENT,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _item(
    *,
    lemma: str = "parler",
    meaning_ja: str = "話す",
    tense: str | None = "présent",
    mood: str | None = None,
    with_evidence: bool = True,
    source: SourceDocument | None = None,
) -> LearningItem:
    metadata: dict[str, str] = {"lemma": lemma}
    if tense is not None:
        metadata["tense"] = tense
    if mood is not None:
        metadata["mood"] = mood
    refs: list[SourceRef] = []
    source = source or _source()
    if with_evidence:
        refs.append(
            SourceRef(
                source_document_id=source.id,
                evidence_span=_span_for(source.content, EVIDENCE),
            )
        )
    return LearningItem(
        id=f"c-{lemma}",
        item_type="conjugation",
        canonical_form=lemma,
        meaning_ja=meaning_ja,
        source_refs=refs,
        metadata=metadata,
    )


def test_adapter_is_eligible_for_known_verb_and_present():
    item = _item(lemma="parler", tense="présent")
    target, skip = evaluate_conjugation_adapter(item)
    assert skip is None
    assert target is not None
    assert target.lemma == "parler"
    assert target.tense == "présent"
    assert "verb_conjugation" in eligible_exercise_types(item)


def test_adapter_skips_unknown_lemma():
    item = _item(lemma="changer", tense="présent")
    assert "changer" not in CONJUGATIONS
    target, skip = evaluate_conjugation_adapter(item)
    assert target is None
    assert skip is not None
    assert skip[0] == "unknown_conjugation_lemma"
    result = generate_exercise(item, "verb_conjugation", seed="fixed")
    assert result.eligible is False
    assert result.skip_reason == "unknown_conjugation_lemma"
    assert result.exercise is None


def test_adapter_skips_tense_mismatch():
    item = _item(lemma="parler", tense="imparfait")
    target, skip = evaluate_conjugation_adapter(item)
    assert target is None
    assert skip is not None
    assert skip[0] == "unsupported_conjugation_tense"
    result = generate_exercise(item, "verb_conjugation", seed="fixed")
    assert result.skip_reason == "unsupported_conjugation_tense"


def test_adapter_does_not_default_missing_tense_to_present():
    item = _item(lemma="être", tense=None)
    assert "être" in CONJUGATIONS
    target, skip = evaluate_conjugation_adapter(item)
    assert target is None
    assert skip is not None
    assert skip[0] == "missing_conjugation_tense"
    skipped = evaluate_exercise_eligibility(item, "verb_conjugation")
    assert skipped.skip_reason == "missing_conjugation_tense"
    result = generate_exercise(item, "verb_conjugation", seed="fixed")
    assert result.skip_reason == "missing_conjugation_tense"


def test_adapter_skips_unsupported_mood():
    item = _item(lemma="parler", tense="présent", mood="subjonctif")
    target, skip = evaluate_conjugation_adapter(item)
    assert target is None
    assert skip is not None
    assert skip[0] == "unsupported_conjugation_mood"
    result = generate_exercise(item, "verb_conjugation", seed="fixed")
    assert result.skip_reason == "unsupported_conjugation_mood"


def test_adapter_allows_indicatif_mood():
    item = _item(lemma="parler", tense="présent", mood=ADAPTER_MOOD)
    target, skip = evaluate_conjugation_adapter(item)
    assert skip is None
    assert target is not None
    assert target.mood == ADAPTER_MOOD


def test_adapter_answer_matches_existing_domain():
    item = _item(lemma="être", tense="présent")
    result = generate_exercise(item, "verb_conjugation", seed="fixed")
    assert result.eligible is True
    assert result.exercise is not None
    spec = result.exercise.spec
    public = result.exercise.to_public()
    verb = spec.metadata["verb"]
    tense = spec.metadata["tense"]
    pronoun = spec.metadata["pronoun"]
    expected = get_correct_answer(verb, tense, pronoun)
    assert expected is not None
    assert result.exercise.answer_key.expected_answers == (expected,)
    assert expected == CONJUGATIONS[verb][tense][pronoun]
    assert pronoun in CONJUGATIONS[verb][tense]
    dumped = public.model_dump()
    assert "expected" not in dumped
    assert "metadata" not in dumped
    assert dumped["exercise_type"] == "verb_conjugation"
    assert dumped["skill_direction"] == "production"
    assert dumped["response_kind"] == "text"
    assert "être" in spec.prompt
    assert "présent" in spec.prompt
    assert pronoun in spec.prompt


def test_adapter_uses_existing_pronouns_and_get_correct_answer():
    item = _item(lemma="faire", tense="présent")
    target, skip = evaluate_conjugation_adapter(item)
    assert skip is None
    assert target is not None
    pronouns = pronouns_for(target.lemma, target.tense)
    assert pronouns == tuple(CONJUGATIONS["faire"]["présent"].keys())
    for pronoun in pronouns:
        material = build_conjugation_prompt_material(target, pronoun)
        assert material is not None
        assert material.expected == get_correct_answer("faire", "présent", pronoun)


def test_adapter_generation_is_deterministic():
    item = _item(lemma="aller", tense="présent")
    first = generate_exercise(item, "verb_conjugation", seed="fixed")
    second = generate_exercise(item, "verb_conjugation", seed="fixed")
    assert first.exercise is not None
    assert second.exercise is not None
    assert first.exercise.spec.prompt == second.exercise.spec.prompt
    assert (
        first.exercise.spec.metadata["pronoun"]
        == second.exercise.spec.metadata["pronoun"]
    )
    assert first.exercise.answer_key == second.exercise.answer_key


def test_source_cloze_fallback_when_adapter_is_ineligible():
    source = _source()
    item = _item(
        lemma="changer",
        tense="présent",
        with_evidence=True,
        source=source,
    )
    supported = generate_supported_exercises(item, seed="fixed", sources=[source])
    assert [row.exercise_type for row in supported] == [
        "verb_conjugation",
        "cloze",
    ]
    assert supported[0].skip_reason == "unknown_conjugation_lemma"
    assert supported[1].eligible is True
    assert supported[1].exercise is not None
    assert supported[1].exercise.spec.exercise_type == "cloze"


def test_source_cloze_fallback_when_tense_is_missing():
    source = _source()
    item = _item(lemma="parler", tense=None, source=source)
    supported = generate_supported_exercises(item, seed="fixed", sources=[source])
    assert supported[0].skip_reason == "missing_conjugation_tense"
    assert supported[1].eligible is True
    assert supported[1].exercise is not None


def test_unknown_free_string_labels_are_not_canonicalized():
    assert canonical_conjugation_tense("présent") == "présent"
    assert canonical_conjugation_tense("Présent") == "présent"
    assert canonical_conjugation_tense("imparfait") == "imparfait"
    assert canonical_conjugation_tense("not-a-tense") is None
    assert canonical_conjugation_mood("indicatif") == "indicatif"
    assert canonical_conjugation_mood("mystery-mood") is None


def test_adapter_does_not_copy_conjugation_tables():
    import app.domain.conjugation_adapter as adapter
    import app.domain.exercise_generation as generation

    for module in (adapter, generation):
        tree = ast.parse(inspect.getsource(module))
        assigned: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        assigned.add(target.id)
        assert "CONJUGATIONS" not in assigned
    source = inspect.getsource(adapter)
    assert "get_correct_answer" in source
