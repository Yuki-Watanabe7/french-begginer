"""LearningItem → Exercise 契約（Issue #145）のテスト。

検証方針:
  - item type ごとの eligible exercise 一覧が deterministic
  - unsupported な組合せを明示的に拒否 / skip できる
  - ExerciseType → SkillDirection mapping が一意
  - 正解内部情報が public DTO へ混入しない
  - domain 層が FastAPI / SQLAlchemy / OpenAI へ依存しない
"""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.domain.conjugation import CONJUGATIONS
from app.domain.exercise import (
    EXERCISE_SKILL_DIRECTIONS,
    EXERCISE_TYPES,
    EXERCISE_VERSION,
    ExerciseAnswerKey,
    ExerciseSpec,
    PublicExercise,
    UnsupportedExerciseError,
    eligible_exercise_types,
    evaluate_exercise_eligibility,
    exercise_event_metadata,
    exercise_reconstruction_key,
    list_exercise_eligibility,
    make_exercise_spec,
    skill_direction_for,
    to_public_exercise,
    tokenize_canonical_form,
)
from app.domain.tutor import (
    SKILL_DIRECTION_BY_EXERCISE_TYPE,
    EvidenceSpan,
    ExerciseType,
    LearningEvent,
    LearningItem,
    LearningItemType,
    SourceRef,
)


def _item(
    *,
    item_type: LearningItemType,
    canonical_form: str = "livre",
    meaning_ja: str = "本",
    with_evidence: bool = False,
    metadata: dict | None = None,
) -> LearningItem:
    source_refs = []
    if with_evidence:
        source_refs = [
            SourceRef(
                source_document_id="source-1",
                evidence_span=EvidenceSpan(start=0, end=5),
            )
        ]
    return LearningItem(
        item_type=item_type,
        canonical_form=canonical_form,
        meaning_ja=meaning_ja,
        source_refs=source_refs,
        metadata=metadata or {},
    )


def test_exercise_type_to_skill_direction_is_unique_and_total():
    assert EXERCISE_SKILL_DIRECTIONS is SKILL_DIRECTION_BY_EXERCISE_TYPE
    assert set(EXERCISE_SKILL_DIRECTIONS) == set(EXERCISE_TYPES)
    assert len(EXERCISE_SKILL_DIRECTIONS) == len(EXERCISE_TYPES)
    for exercise_type in EXERCISE_TYPES:
        assert skill_direction_for(exercise_type) in {"recognition", "production"}
        assert (
            skill_direction_for(exercise_type)
            == EXERCISE_SKILL_DIRECTIONS[exercise_type]
        )


def test_skill_direction_mapping_matches_documented_policy():
    assert skill_direction_for("meaning_recognition") == "recognition"
    assert skill_direction_for("fr_to_ja") == "recognition"
    assert skill_direction_for("ja_to_fr") == "production"
    assert skill_direction_for("cloze") == "production"
    assert skill_direction_for("expression_reconstruction") == "production"
    assert skill_direction_for("verb_conjugation") == "production"
    assert skill_direction_for("noun_gender") == "recognition"
    assert skill_direction_for("noun_article") == "production"


@pytest.mark.parametrize(
    ("item_type", "canonical_form", "expected"),
    [
        (
            "vocabulary",
            "livre",
            ("meaning_recognition", "ja_to_fr", "cloze"),
        ),
        (
            "expression",
            "se rendre compte de",
            (
                "meaning_recognition",
                "ja_to_fr",
                "cloze",
                "expression_reconstruction",
            ),
        ),
        (
            "grammar",
            "il fallait",
            ("meaning_recognition", "cloze"),
        ),
        (
            "conjugation",
            "parler",
            ("cloze", "verb_conjugation"),
        ),
    ],
)
def test_eligible_exercises_by_item_type_are_deterministic(
    item_type: LearningItemType,
    canonical_form: str,
    expected: tuple[ExerciseType, ...],
):
    item = _item(
        item_type=item_type,
        canonical_form=canonical_form,
        meaning_ja="意味",
        with_evidence=True,
        metadata=(
            {"lemma": canonical_form, "tense": "présent"}
            if item_type == "conjugation"
            else {}
        ),
    )
    first = eligible_exercise_types(item)
    second = eligible_exercise_types(item)
    assert first == second
    assert first == expected
    assert list_exercise_eligibility(item) == list_exercise_eligibility(item)


def test_cloze_is_skipped_without_source_evidence():
    item = _item(item_type="vocabulary", with_evidence=False)
    types = eligible_exercise_types(item)
    assert "cloze" not in types
    assert "meaning_recognition" in types
    assert "ja_to_fr" in types
    cloze = evaluate_exercise_eligibility(item, "cloze")
    assert cloze.eligible is False
    assert cloze.skip_reason == "missing_source_evidence"


def test_verb_conjugation_is_skipped_for_unknown_lemma():
    item = _item(
        item_type="conjugation",
        canonical_form="changer",
        meaning_ja="変える",
        with_evidence=True,
        metadata={"lemma": "changer", "tense": "présent"},
    )
    assert "changer" not in CONJUGATIONS
    types = eligible_exercise_types(item)
    assert types == ("cloze",)
    skipped = evaluate_exercise_eligibility(item, "verb_conjugation")
    assert skipped.skip_reason == "unknown_conjugation_lemma"


def test_verb_conjugation_is_skipped_when_tense_metadata_is_missing():
    item = _item(
        item_type="conjugation",
        canonical_form="être",
        meaning_ja="〜である",
        with_evidence=True,
        metadata={"lemma": "être"},
    )
    assert "être" in CONJUGATIONS
    types = eligible_exercise_types(item)
    assert types == ("cloze",)
    skipped = evaluate_exercise_eligibility(item, "verb_conjugation")
    assert skipped.skip_reason == "missing_conjugation_tense"


def test_verb_conjugation_is_skipped_for_unsupported_tense():
    item = _item(
        item_type="conjugation",
        canonical_form="parler",
        meaning_ja="話す",
        with_evidence=True,
        metadata={"lemma": "parler", "tense": "imparfait"},
    )
    types = eligible_exercise_types(item)
    assert types == ("cloze",)
    skipped = evaluate_exercise_eligibility(item, "verb_conjugation")
    assert skipped.skip_reason == "unsupported_conjugation_tense"


def test_verb_conjugation_is_eligible_when_lemma_and_present_are_in_existing_dataset():
    item = _item(
        item_type="conjugation",
        canonical_form="être",
        meaning_ja="〜である",
        with_evidence=True,
        metadata={"lemma": "être", "tense": "présent"},
    )
    assert "être" in CONJUGATIONS
    assert "verb_conjugation" in eligible_exercise_types(item)


@pytest.mark.parametrize("status", ["suspended", "mastered"])
def test_inactive_items_are_not_eligible_for_new_session(status: str):
    item = _item(item_type="vocabulary", with_evidence=True)
    item = item.model_copy(update={"status": status})
    types = eligible_exercise_types(item)
    assert types == ()
    skipped = evaluate_exercise_eligibility(item, "ja_to_fr")
    assert skipped.eligible is False
    assert skipped.skip_reason == "inactive_item"


def test_tokenize_canonical_form_does_not_split_elision():
    assert tokenize_canonical_form("s'en aller") == ("s'en", "aller")
    assert tokenize_canonical_form("  se   rendre   compte  de ") == (
        "se",
        "rendre",
        "compte",
        "de",
    )


def test_expression_reconstruction_is_skipped_for_single_token():
    item = _item(
        item_type="expression",
        canonical_form="bonjour",
        meaning_ja="こんにちは",
        with_evidence=True,
    )
    types = eligible_exercise_types(item)
    assert "expression_reconstruction" not in types
    skipped = evaluate_exercise_eligibility(item, "expression_reconstruction")
    assert skipped.skip_reason == "insufficient_expression_tokens"


def test_unsupported_combinations_are_explicitly_skipped():
    vocabulary = _item(item_type="vocabulary", with_evidence=True)
    grammar = _item(
        item_type="grammar",
        canonical_form="il fallait",
        meaning_ja="しなければならなかった",
        with_evidence=True,
    )
    verb = evaluate_exercise_eligibility(vocabulary, "verb_conjugation")
    ja_to_fr = evaluate_exercise_eligibility(grammar, "ja_to_fr")
    gender = evaluate_exercise_eligibility(vocabulary, "noun_gender")
    article = evaluate_exercise_eligibility(vocabulary, "noun_article")
    fr_to_ja = evaluate_exercise_eligibility(vocabulary, "fr_to_ja")
    assert verb.skip_reason == "unsupported_combination"
    assert ja_to_fr.skip_reason == "unsupported_combination"
    assert gender.skip_reason == "existing_quiz_only"
    assert article.skip_reason == "existing_quiz_only"
    assert fr_to_ja.skip_reason == "requires_semantic_grading"


def test_make_exercise_spec_rejects_unsupported_combination():
    item = _item(item_type="vocabulary", with_evidence=True)
    with pytest.raises(UnsupportedExerciseError) as exc_info:
        make_exercise_spec(item, "verb_conjugation", prompt="活用してください")
    assert exc_info.value.reason == "unsupported_combination"


def test_make_exercise_spec_builds_choice_contract_without_answers():
    item = _item(item_type="vocabulary", with_evidence=True)
    spec = make_exercise_spec(
        item,
        "meaning_recognition",
        prompt="この単語の意味は？",
        options=("本", "家", "猫"),
        metadata={"distractor_source": "item_bank"},
    )
    assert spec.learning_item_id == item.id
    assert spec.skill_direction == "recognition"
    assert spec.response_kind == "choice"
    assert spec.exercise_version == EXERCISE_VERSION
    assert "expected" not in spec.model_dump()
    dumped = to_public_exercise(spec).model_dump()
    assert "metadata" not in dumped
    assert "expected" not in dumped
    assert dumped["options"] == ("本", "家", "猫")


def test_make_exercise_spec_fills_skill_direction_from_policy():
    item = _item(
        item_type="expression",
        canonical_form="se rendre compte de",
        meaning_ja="〜に気づく",
        with_evidence=True,
    )
    spec = make_exercise_spec(item, "ja_to_fr", prompt="フランス語で書いてください")
    assert spec.skill_direction == "production"
    assert spec.response_kind == "text"
    assert spec.options is None
    reconstructed = make_exercise_spec(
        item,
        "expression_reconstruction",
        prompt="表現を組み立ててください",
        options=("compte", "de", "se", "rendre"),
    )
    assert reconstructed.response_kind == "reconstruction"
    assert reconstructed.options == ("compte", "de", "se", "rendre")
    event = LearningEvent(
        learning_item_id=item.id,
        exercise_type="expression_reconstruction",
        result="correct",
    )
    assert event.exercise_type == "expression_reconstruction"


def test_exercise_spec_rejects_answer_fields_and_mismatched_direction():
    with pytest.raises(ValidationError):
        ExerciseSpec(
            learning_item_id="item-1",
            exercise_type="ja_to_fr",
            skill_direction="production",
            prompt="訳してください",
            response_kind="text",
            expected="livre",
        )
    with pytest.raises(ValidationError):
        ExerciseSpec(
            learning_item_id="item-1",
            exercise_type="ja_to_fr",
            skill_direction="recognition",
            prompt="訳してください",
            response_kind="text",
        )
    with pytest.raises(ValidationError):
        ExerciseSpec(
            learning_item_id="item-1",
            exercise_type="meaning_recognition",
            skill_direction="recognition",
            prompt="意味は？",
            response_kind="choice",
            options=("本", "家"),
            metadata={"expected_answer": "本"},
        )


def test_public_dto_does_not_include_internal_answer_fields():
    assert "metadata" not in PublicExercise.model_fields
    for field_name in (
        "expected",
        "expected_answer",
        "expected_answers",
        "answer",
        "answer_key",
        "correct",
        "correct_option_index",
    ):
        assert field_name not in PublicExercise.model_fields
        assert field_name not in ExerciseSpec.model_fields

    spec = ExerciseSpec(
        learning_item_id="item-1",
        exercise_type="ja_to_fr",
        skill_direction="production",
        prompt="フランス語で書いてください",
        response_kind="text",
        metadata={"source_ref_id": "source-1"},
    )
    public = to_public_exercise(spec)
    dumped = public.model_dump()
    assert dumped == {
        "learning_item_id": "item-1",
        "exercise_type": "ja_to_fr",
        "skill_direction": "production",
        "prompt": "フランス語で書いてください",
        "response_kind": "text",
        "options": None,
        "source_context": None,
        "exercise_version": EXERCISE_VERSION,
    }
    answer_key = ExerciseAnswerKey(expected_answers=("livre",))
    assert set(answer_key.model_dump()).isdisjoint(dumped)


def test_learning_event_can_track_exercise_version():
    item = _item(
        item_type="vocabulary",
        with_evidence=True,
    )
    spec = make_exercise_spec(
        item,
        "ja_to_fr",
        prompt="フランス語で書いてください",
    )
    metadata = exercise_event_metadata(spec)
    assert metadata["exercise_version"] == EXERCISE_VERSION
    assert metadata["skill_direction"] == "production"
    assert metadata["generation_method"] == "deterministic"
    assert "expected" not in metadata
    event = LearningEvent(
        learning_item_id=item.id,
        exercise_type=spec.exercise_type,
        result="correct",
        occurred_at=datetime(2026, 8, 1, tzinfo=UTC),
        metadata=metadata,
    )
    assert event.metadata["exercise_version"] == EXERCISE_VERSION
    assert event.metadata["reconstruction_key"] == exercise_reconstruction_key(
        item.id, "ja_to_fr"
    )


def test_reconstruction_key_is_stable_for_same_input():
    key = exercise_reconstruction_key("item-1", "cloze")
    assert key == exercise_reconstruction_key("item-1", "cloze")
    assert key != exercise_reconstruction_key("item-1", "ja_to_fr")
    assert key != exercise_reconstruction_key("item-1", "cloze", "exercise-v2")


def test_choice_requires_options_and_text_rejects_them():
    item = _item(item_type="vocabulary", with_evidence=True)
    with pytest.raises(ValidationError):
        make_exercise_spec(item, "meaning_recognition", prompt="意味は？")
    with pytest.raises(ValidationError):
        make_exercise_spec(
            item,
            "ja_to_fr",
            prompt="書いてください",
            options=("livre", "maison"),
        )
    expression = _item(
        item_type="expression",
        canonical_form="se rendre compte de",
        meaning_ja="〜に気づく",
        with_evidence=True,
    )
    with pytest.raises(ValidationError):
        make_exercise_spec(
            expression,
            "expression_reconstruction",
            prompt="並べてください",
            options=("seul",),
        )


def test_domain_module_does_not_depend_on_fastapi_sqlalchemy_or_openai():
    import app.domain.exercise as module
    import app.domain.tutor as tutor_module

    forbidden = {"fastapi", "sqlalchemy", "openai"}
    for target in (module, tutor_module):
        tree = ast.parse(inspect.getsource(target))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".", 1)[0])
        assert names.isdisjoint(forbidden), names
