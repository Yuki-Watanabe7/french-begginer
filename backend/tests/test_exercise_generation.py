"""vocabulary / expression 向け deterministic Exercise 生成（Issue #146）のテスト。

検証方針:
  - vocabulary / expression から基本 Exercise を生成できる
  - recognition と production の両方向を最低1形式ずつ持つ
  - meaning recognition の distractor が deterministic かつ重複しない
  - ja_to_fr で canonical_form を正解根拠として保持できる
  - expression reconstruction がある
  - 日本語自由記述を安易な完全一致で採点しない
  - unsupported / 材料不足は skip reason を返せる
  - LLM API 非依存である
"""

from __future__ import annotations

import ast
import inspect
import os

import pytest

from app.domain.exercise import (
    EXERCISE_VERSION,
    tokenize_canonical_form,
)
from app.domain.exercise_generation import (
    DEFAULT_GENERATION_SEED,
    GENERATED_EXERCISE_TYPES,
    SUPPORTED_ITEM_EXERCISE_TYPES,
    generate_exercise,
    generate_supported_exercises,
    meaning_key,
    unique_distractor_meanings,
)
from app.domain.tutor import LearningItem, LearningItemStatus, LearningItemType


def _item(
    *,
    item_id: str,
    item_type: LearningItemType = "vocabulary",
    canonical_form: str = "livre",
    meaning_ja: str = "本",
    status: LearningItemStatus = "active",
) -> LearningItem:
    return LearningItem(
        id=item_id,
        item_type=item_type,
        canonical_form=canonical_form,
        meaning_ja=meaning_ja,
        status=status,
    )


def _vocab_pool() -> tuple[LearningItem, ...]:
    return (
        _item(item_id="v-livre", canonical_form="livre", meaning_ja="本"),
        _item(item_id="v-maison", canonical_form="maison", meaning_ja="家"),
        _item(item_id="v-chat", canonical_form="chat", meaning_ja="猫"),
        _item(item_id="v-chien", canonical_form="chien", meaning_ja="犬"),
        _item(item_id="v-eau", canonical_form="eau", meaning_ja="水"),
    )


def test_vocabulary_meaning_recognition_uses_pool_meanings():
    pool = _vocab_pool()
    target = pool[0]
    result = generate_exercise(target, "meaning_recognition", pool=pool, seed="fixed")
    assert result.eligible is True
    assert result.exercise is not None
    spec = result.exercise.spec
    public = result.exercise.to_public()
    assert spec.exercise_type == "meaning_recognition"
    assert spec.skill_direction == "recognition"
    assert spec.response_kind == "choice"
    assert spec.prompt.endswith("livre")
    assert "本" not in spec.prompt
    assert spec.options is not None
    assert "本" in spec.options
    assert set(spec.options) <= {"本", "家", "猫", "犬", "水"}
    assert spec.options.count("本") == 1
    key = result.exercise.answer_key
    assert key.expected_answers == ("本",)
    assert key.correct_option_index is not None
    assert spec.options[key.correct_option_index] == "本"
    dumped = public.model_dump()
    assert "expected" not in dumped
    assert "answer_key" not in dumped
    assert "metadata" not in dumped
    assert "correct_option_index" not in dumped
    assert dumped["options"] == spec.options


def test_expression_meaning_recognition_uses_japanese_options():
    target = _item(
        item_id="e-se-rendre",
        item_type="expression",
        canonical_form="se rendre compte de",
        meaning_ja="〜に気づく",
    )
    pool = (
        target,
        _item(
            item_id="e-il-sagit",
            item_type="expression",
            canonical_form="il s'agit de",
            meaning_ja="〜についてである",
        ),
        _item(
            item_id="v-strategie",
            canonical_form="stratégie",
            meaning_ja="戦略",
        ),
    )
    result = generate_exercise(target, "meaning_recognition", pool=pool, seed="expr")
    assert result.eligible is True
    assert result.exercise is not None
    assert "se rendre compte de" in result.exercise.spec.prompt
    assert "〜に気づく" in result.exercise.spec.options
    assert result.exercise.answer_key.expected_answers == ("〜に気づく",)


def test_ja_to_fr_keeps_canonical_form_as_internal_answer():
    item = _item(item_id="v-livre", canonical_form="livre", meaning_ja="本")
    result = generate_exercise(item, "ja_to_fr", seed="fixed")
    assert result.eligible is True
    assert result.exercise is not None
    spec = result.exercise.spec
    public = result.exercise.to_public()
    assert spec.exercise_type == "ja_to_fr"
    assert spec.skill_direction == "production"
    assert spec.response_kind == "text"
    assert spec.options is None
    assert "本" in spec.prompt
    assert "livre" not in spec.prompt
    assert result.exercise.answer_key.expected_answers == ("livre",)
    assert "livre" not in public.model_dump().values()
    assert public.prompt == spec.prompt
    assert "expected" not in spec.model_dump()
    assert "canonical_form" not in spec.metadata


def test_expression_reconstruction_shuffles_tokens_without_breaking_elision():
    item = _item(
        item_id="e-se-rendre",
        item_type="expression",
        canonical_form="se rendre compte de",
        meaning_ja="〜に気づく",
    )
    result = generate_exercise(item, "expression_reconstruction", seed="fixed")
    assert result.eligible is True
    assert result.exercise is not None
    spec = result.exercise.spec
    tokens = tokenize_canonical_form("se rendre compte de")
    assert spec.response_kind == "reconstruction"
    assert spec.options is not None
    assert sorted(spec.options) == sorted(tokens)
    assert spec.options != tokens
    assert "se rendre compte de" not in spec.prompt
    assert result.exercise.answer_key.expected_answers == ("se rendre compte de",)
    public = result.exercise.to_public()
    assert public.options == spec.options
    assert "expected" not in public.model_dump()


@pytest.mark.parametrize(
    ("canonical_form", "expected"),
    [
        ("l'heure", ("l'heure",)),
        ("d'accord", ("d'accord",)),
        ("s'en aller", ("s'en", "aller")),
        ("j'ai", ("j'ai",)),
        ("n'est-ce pas", ("n'est-ce", "pas")),
        ("aujourd'hui", ("aujourd'hui",)),
        ("l’heure", ("l’heure",)),
        ("se rendre compte de", ("se", "rendre", "compte", "de")),
    ],
)
def test_tokenize_canonical_form_keeps_apostrophe_and_hyphen(
    canonical_form: str, expected: tuple[str, ...]
):
    assert tokenize_canonical_form(canonical_form) == expected


def test_meaning_recognition_skips_when_distractors_are_insufficient():
    target = _item(item_id="v-livre", canonical_form="livre", meaning_ja="本")
    empty = generate_exercise(target, "meaning_recognition", pool=(), seed="fixed")
    assert empty.eligible is False
    assert empty.skip_reason == "insufficient_distractors"
    assert empty.exercise is None

    same_meaning = generate_exercise(
        target,
        "meaning_recognition",
        pool=(
            target,
            _item(item_id="v-book", canonical_form="bouquin", meaning_ja="本"),
            _item(
                item_id="v-book-space",
                canonical_form="ouvrage",
                meaning_ja="  本  ",
            ),
        ),
        seed="fixed",
    )
    assert same_meaning.skip_reason == "insufficient_distractors"


def test_duplicate_meanings_are_not_used_as_options():
    target = _item(item_id="v-livre", canonical_form="livre", meaning_ja="本")
    pool = (
        target,
        _item(item_id="v-maison", canonical_form="maison", meaning_ja="家"),
        _item(item_id="v-home", canonical_form="domicile", meaning_ja="家"),
        _item(item_id="v-chat", canonical_form="chat", meaning_ja="猫"),
        _item(
            item_id="v-chat-nfc",
            canonical_form="minou",
            meaning_ja=" 猫 ",
        ),
    )
    result = generate_exercise(target, "meaning_recognition", pool=pool, seed="fixed")
    assert result.eligible is True
    assert result.exercise is not None
    options = result.exercise.spec.options
    assert options is not None
    keys = [meaning_key(option) for option in options]
    assert len(keys) == len(set(keys))
    assert keys.count(meaning_key("本")) == 1
    assert unique_distractor_meanings(target, pool) == ("猫", "家")


def test_suspended_and_mastered_items_are_skipped():
    pool = _vocab_pool()
    suspended = _item(
        item_id="v-livre",
        canonical_form="livre",
        meaning_ja="本",
        status="suspended",
    )
    mastered = _item(
        item_id="v-maison",
        canonical_form="maison",
        meaning_ja="家",
        status="mastered",
    )
    suspended_result = generate_exercise(suspended, "ja_to_fr", pool=pool, seed="fixed")
    mastered_result = generate_exercise(
        mastered, "meaning_recognition", pool=pool, seed="fixed"
    )
    assert suspended_result.skip_reason == "inactive_item"
    assert mastered_result.skip_reason == "inactive_item"
    assert suspended_result.exercise is None
    assert mastered_result.exercise is None


def test_suspended_pool_items_are_not_used_as_distractors():
    target = _item(item_id="v-livre", canonical_form="livre", meaning_ja="本")
    pool = (
        target,
        _item(
            item_id="v-maison",
            canonical_form="maison",
            meaning_ja="家",
            status="suspended",
        ),
        _item(
            item_id="v-chat",
            canonical_form="chat",
            meaning_ja="猫",
            status="mastered",
        ),
        _item(item_id="v-chien", canonical_form="chien", meaning_ja="犬"),
    )
    result = generate_exercise(target, "meaning_recognition", pool=pool, seed="fixed")
    assert result.eligible is True
    assert result.exercise is not None
    assert set(result.exercise.spec.options) == {"本", "犬"}


def test_generation_is_deterministic_for_same_item_and_seed():
    pool = _vocab_pool()
    target = pool[0]
    first = generate_exercise(target, "meaning_recognition", pool=pool, seed="alpha")
    second = generate_exercise(target, "meaning_recognition", pool=pool, seed="alpha")
    third = generate_exercise(target, "meaning_recognition", pool=pool, seed="beta")
    assert first.exercise is not None
    assert second.exercise is not None
    assert third.exercise is not None
    assert first.exercise.spec.options == second.exercise.spec.options
    assert first.exercise.answer_key == second.exercise.answer_key
    assert first.exercise.spec.exercise_version == EXERCISE_VERSION
    assert first.exercise.spec.metadata["generation_seed"] == "alpha"
    assert third.exercise.spec.metadata["generation_seed"] == "beta"
    reconstruction = generate_exercise(
        _item(
            item_id="e-se-rendre",
            item_type="expression",
            canonical_form="se rendre compte de",
            meaning_ja="〜に気づく",
        ),
        "expression_reconstruction",
        seed="alpha",
    )
    reconstruction_again = generate_exercise(
        _item(
            item_id="e-se-rendre",
            item_type="expression",
            canonical_form="se rendre compte de",
            meaning_ja="〜に気づく",
        ),
        "expression_reconstruction",
        seed="alpha",
    )
    assert reconstruction.exercise is not None
    assert reconstruction_again.exercise is not None
    assert (
        reconstruction.exercise.spec.options
        == reconstruction_again.exercise.spec.options
    )


def test_fr_to_ja_is_not_graded_by_meaning_string_match():
    item = _item(
        item_id="e-se-rendre",
        item_type="expression",
        canonical_form="se rendre compte de",
        meaning_ja="〜に気づく",
    )
    result = generate_exercise(item, "fr_to_ja", seed="fixed")
    assert result.eligible is False
    assert result.skip_reason == "requires_semantic_grading"
    assert result.exercise is None


def test_unsupported_and_single_token_reconstruction_return_skip_reason():
    vocab = _item(item_id="v-livre")
    grammar = _item(
        item_id="g-fallait",
        item_type="grammar",
        canonical_form="il fallait",
        meaning_ja="しなければならなかった",
    )
    short = _item(
        item_id="e-bonjour",
        item_type="expression",
        canonical_form="bonjour",
        meaning_ja="こんにちは",
    )
    verb = generate_exercise(vocab, "verb_conjugation", seed="fixed")
    grammar_ja = generate_exercise(grammar, "ja_to_fr", seed="fixed")
    reconstruction = generate_exercise(short, "expression_reconstruction", seed="fixed")
    cloze = generate_exercise(vocab, "cloze", seed="fixed")
    assert verb.skip_reason == "unsupported_combination"
    assert grammar_ja.skip_reason == "unsupported_combination"
    assert reconstruction.skip_reason == "insufficient_expression_tokens"
    assert cloze.skip_reason == "missing_source_evidence"
    assert verb.exercise is None
    grammar_meaning = generate_exercise(
        grammar, "meaning_recognition", pool=_vocab_pool(), seed="fixed"
    )
    assert grammar_meaning.skip_reason == "generation_not_implemented"
    grammar_supported = generate_supported_exercises(grammar)
    assert [row.exercise_type for row in grammar_supported] == ["cloze"]
    assert grammar_supported[0].skip_reason == "missing_source_evidence"


def test_supported_exercises_cover_recognition_and_production():
    pool = _vocab_pool()
    vocab_results = generate_supported_exercises(pool[0], pool=pool, seed="fixed")
    assert [row.exercise_type for row in vocab_results] == [
        "meaning_recognition",
        "ja_to_fr",
        "cloze",
    ]
    assert [row.eligible for row in vocab_results] == [True, True, False]
    assert vocab_results[2].skip_reason == "missing_source_evidence"
    directions = {
        row.exercise.spec.skill_direction
        for row in vocab_results
        if row.exercise is not None
    }
    assert directions == {"recognition", "production"}

    expression = _item(
        item_id="e-se-rendre",
        item_type="expression",
        canonical_form="se rendre compte de",
        meaning_ja="〜に気づく",
    )
    expr_results = generate_supported_exercises(expression, pool=pool, seed="fixed")
    assert [row.exercise_type for row in expr_results] == [
        "meaning_recognition",
        "ja_to_fr",
        "expression_reconstruction",
        "cloze",
    ]
    assert [row.eligible for row in expr_results[:3]] == [True, True, True]
    assert expr_results[3].skip_reason == "missing_source_evidence"


def test_generated_types_are_exactly_the_supported_vocab_expression_set():
    generated = {
        exercise_type
        for types in SUPPORTED_ITEM_EXERCISE_TYPES.values()
        for exercise_type in types
    }
    assert generated == GENERATED_EXERCISE_TYPES


def test_generation_works_without_openai_api_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert os.environ.get("OPENAI_API_KEY") is None
    pool = _vocab_pool()
    result = generate_exercise(
        pool[0], "meaning_recognition", pool=pool, seed=DEFAULT_GENERATION_SEED
    )
    assert result.eligible is True


def test_generation_module_does_not_depend_on_fastapi_sqlalchemy_or_openai():
    import app.domain.exercise_generation as module

    tree = ast.parse(inspect.getsource(module))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".", 1)[0])
    assert names.isdisjoint({"fastapi", "sqlalchemy", "openai"}), names
