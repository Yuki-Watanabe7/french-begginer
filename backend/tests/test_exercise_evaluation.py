"""Tutor Exercise の server-side 採点（Issue #149）のテスト。

検証方針:
  - meaning recognition の正誤が option 文字列で決まり、index に依存しない
  - ja_to_fr の空白・apostrophe・大文字小文字を正規化できる
  - accent 誤りを安易に正解にしない
  - cloze / reconstruction / verb_conjugation adapter を判定できる
  - 空回答は malformed であり、誤答とは区別する
  - domain が FastAPI / SQLAlchemy / OpenAI に依存しない
"""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime

import pytest

from app.domain.conjugation import get_correct_answer
from app.domain.exercise_evaluation import (
    MalformedExerciseAnswerError,
    evaluate_exercise_answer,
    normalize_french_production,
)
from app.domain.exercise_generation import generate_exercise
from app.domain.tutor import (
    EvidenceSpan,
    LearningItem,
    LearningItemType,
    SourceDocument,
    SourceRef,
)

CLOZE_CONTENT = "Je me suis rendu compte qu'il fallait changer de stratégie."
CLOZE_EVIDENCE = "rendu compte"


def _item(
    *,
    item_id: str,
    item_type: LearningItemType = "vocabulary",
    canonical_form: str = "livre",
    meaning_ja: str = "本",
    metadata: dict | None = None,
    source: SourceDocument | None = None,
    fragment: str | None = None,
) -> LearningItem:
    refs: list[SourceRef] = []
    if source is not None and fragment is not None:
        start = source.content.index(fragment)
        refs.append(
            SourceRef(
                source_document_id=source.id,
                evidence_span=EvidenceSpan(start=start, end=start + len(fragment)),
            )
        )
    return LearningItem(
        id=item_id,
        item_type=item_type,
        canonical_form=canonical_form,
        meaning_ja=meaning_ja,
        source_refs=refs,
        metadata=metadata or {},
    )


def _vocab_pool() -> tuple[LearningItem, ...]:
    return (
        _item(item_id="v-livre", canonical_form="livre", meaning_ja="本"),
        _item(item_id="v-maison", canonical_form="maison", meaning_ja="家"),
        _item(item_id="v-chat", canonical_form="chat", meaning_ja="猫"),
        _item(item_id="v-chien", canonical_form="chien", meaning_ja="犬"),
    )


def test_meaning_recognition_correct_and_incorrect_use_option_text_not_index():
    pool = _vocab_pool()
    first = generate_exercise(pool[0], "meaning_recognition", pool=pool, seed="seed-a")
    second = generate_exercise(pool[0], "meaning_recognition", pool=pool, seed="seed-b")
    assert first.exercise is not None
    assert second.exercise is not None

    correct = evaluate_exercise_answer(first.exercise, "本")
    shuffled_still_correct = evaluate_exercise_answer(second.exercise, "本")
    also_correct = evaluate_exercise_answer(first.exercise, "  本  ")
    wrong = evaluate_exercise_answer(first.exercise, "家")
    assert correct.correct is True
    assert shuffled_still_correct.correct is True
    assert also_correct.correct is True
    assert wrong.correct is False
    assert correct.correct_answer == "本"


def test_ja_to_fr_normalizes_whitespace_case_and_apostrophe():
    item = _item(
        item_id="expr-1",
        item_type="expression",
        canonical_form="j'ai faim",
        meaning_ja="お腹が空いている",
    )
    result = generate_exercise(item, "ja_to_fr")
    assert result.exercise is not None

    matching = evaluate_exercise_answer(result.exercise, "  J\u2019AI   FAIM ")
    assert matching.correct is True
    assert matching.correct_answer == "j'ai faim"


def test_accent_error_is_not_accepted_as_correct():
    item = _item(item_id="v-ete", canonical_form="été", meaning_ja="夏")
    result = generate_exercise(item, "ja_to_fr")
    assert result.exercise is not None

    assert evaluate_exercise_answer(result.exercise, "été").correct is True
    assert evaluate_exercise_answer(result.exercise, "ete").correct is False
    assert evaluate_exercise_answer(result.exercise, "été").correct_answer == "été"
    assert "é" not in normalize_french_production("ete")
    assert normalize_french_production("été") != normalize_french_production("ete")


def test_cloze_grades_source_slice():
    source = SourceDocument(
        id="src-1",
        title="fixture",
        content=CLOZE_CONTENT,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    item = _item(
        item_id="expr-cloze",
        item_type="expression",
        canonical_form="se rendre compte de",
        meaning_ja="〜に気づく",
        source=source,
        fragment=CLOZE_EVIDENCE,
    )
    result = generate_exercise(item, "cloze", sources=[source])
    assert result.exercise is not None
    assert evaluate_exercise_answer(result.exercise, "rendu compte").correct is True
    assert evaluate_exercise_answer(result.exercise, "rendre compte").correct is False
    assert result.exercise.answer_key.expected_answers == ("rendu compte",)


def test_reconstruction_compares_token_order():
    item = _item(
        item_id="expr-recon",
        item_type="expression",
        canonical_form="se rendre compte de",
        meaning_ja="〜に気づく",
    )
    result = generate_exercise(item, "expression_reconstruction", seed="fixed")
    assert result.exercise is not None

    correct = evaluate_exercise_answer(
        result.exercise, ["se", "rendre", "compte", "de"]
    )
    also_correct = evaluate_exercise_answer(result.exercise, "se rendre compte de")
    wrong = evaluate_exercise_answer(result.exercise, ["rendre", "se", "compte", "de"])
    assert correct.correct is True
    assert also_correct.correct is True
    assert wrong.correct is False
    assert correct.given == ("se", "rendre", "compte", "de")


def test_verb_conjugation_adapter_uses_existing_domain_answer():
    item = _item(
        item_id="conj-parler",
        item_type="conjugation",
        canonical_form="parler",
        meaning_ja="話す",
        metadata={"lemma": "parler", "tense": "présent"},
    )
    result = generate_exercise(item, "verb_conjugation", seed="fixed")
    assert result.exercise is not None
    spec = result.exercise.spec
    expected = get_correct_answer(
        spec.metadata["verb"], spec.metadata["tense"], spec.metadata["pronoun"]
    )
    assert expected is not None
    assert result.exercise.answer_key.expected_answers == (expected,)
    assert evaluate_exercise_answer(result.exercise, expected).correct is True
    assert evaluate_exercise_answer(result.exercise, expected.upper()).correct is True
    assert evaluate_exercise_answer(result.exercise, "xxxxx").correct is False


def test_empty_or_wrong_shape_answer_is_malformed():
    pool = _vocab_pool()
    choice = generate_exercise(pool[0], "meaning_recognition", pool=pool, seed="fixed")
    text = generate_exercise(pool[0], "ja_to_fr")
    recon = generate_exercise(
        _item(
            item_id="expr-recon",
            item_type="expression",
            canonical_form="se rendre compte de",
            meaning_ja="〜に気づく",
        ),
        "expression_reconstruction",
        seed="fixed",
    )
    assert choice.exercise is not None
    assert text.exercise is not None
    assert recon.exercise is not None

    with pytest.raises(MalformedExerciseAnswerError):
        evaluate_exercise_answer(choice.exercise, "   ")
    with pytest.raises(MalformedExerciseAnswerError):
        evaluate_exercise_answer(choice.exercise, ["本"])
    with pytest.raises(MalformedExerciseAnswerError):
        evaluate_exercise_answer(text.exercise, "")
    with pytest.raises(MalformedExerciseAnswerError):
        evaluate_exercise_answer(text.exercise, ["livre"])
    with pytest.raises(MalformedExerciseAnswerError):
        evaluate_exercise_answer(recon.exercise, [])
    with pytest.raises(MalformedExerciseAnswerError):
        evaluate_exercise_answer(recon.exercise, ["se", "  "])


def test_domain_module_does_not_depend_on_fastapi_sqlalchemy_or_openai():
    import app.domain.exercise_evaluation as module

    forbidden = {"fastapi", "sqlalchemy", "openai"}
    tree = ast.parse(inspect.getsource(module))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".", 1)[0])
    assert names.isdisjoint(forbidden), names
