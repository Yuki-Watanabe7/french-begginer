"""Regression tests for llm_domain_review post-processing.

Guards against false warnings on correct French conjugations
(see Issue #93 / PR #92, PR #158).
"""

import pytest
from llm_domain_review import (
    conjugation_section_for,
    filter_warnings,
    should_attach_conjugation_snapshot,
)


# Fixture: the three known false warnings from PR #92
@pytest.fixture()
def pr92_false_warnings():
    return [
        {
            "verb": "partir",
            "pronoun": "il/elle",
            "value": "part",
            "reason": "初級学習者に混乱を招く可能性があるため",
            "action": "確認が必要",
        },
        {
            "verb": "sortir",
            "pronoun": "il/elle",
            "value": "sort",
            "reason": "標準フランス語では使用されない可能性があるため",
            "action": "確認が必要",
        },
        {
            "verb": "dormir",
            "pronoun": "il/elle",
            "value": "dort",
            "reason": "初級学習者に混乱を引き起こす可能性があるため",
            "action": "確認が必要",
        },
    ]


class TestFilterWarnings:
    def test_pr92_false_warnings_all_removed(self, pr92_false_warnings):
        """partir/part, sortir/sort, dormir/dort must not appear as kept warnings."""
        kept, demoted = filter_warnings(pr92_false_warnings)
        assert kept == [], f"Expected no kept warnings, got: {kept}"
        assert len(demoted) == 3

    def test_partir_confusion_only_is_demoted(self):
        kept, demoted = filter_warnings(
            [
                {
                    "verb": "partir",
                    "pronoun": "il/elle",
                    "value": "part",
                    "reason": "初級学習者に混乱を招く可能性があるため",
                    "action": "確認が必要",
                }
            ]
        )
        assert kept == []
        assert len(demoted) == 1

    def test_sortir_incorrectness_without_expected_is_demoted(self):
        kept, demoted = filter_warnings(
            [
                {
                    "verb": "sortir",
                    "pronoun": "il/elle",
                    "value": "sort",
                    "reason": "標準フランス語では使用されない可能性があるため",
                    "action": "確認が必要",
                }
            ]
        )
        assert kept == []
        assert len(demoted) == 1

    def test_dormir_confusion_only_is_demoted(self):
        kept, demoted = filter_warnings(
            [
                {
                    "verb": "dormir",
                    "pronoun": "il/elle",
                    "value": "dort",
                    "reason": "初級学習者に混乱を引き起こす可能性があるため",
                    "action": "確認が必要",
                }
            ]
        )
        assert kept == []
        assert len(demoted) == 1

    def test_valid_warning_with_expected_is_kept(self):
        """A warning with a concrete expected form should be kept."""
        kept, demoted = filter_warnings(
            [
                {
                    "verb": "commencer",
                    "pronoun": "nous",
                    "value": "commencons",
                    "expected": "commençons",
                    "reason": "ç の使用が必要です（綴り誤り）",
                    "action": "確認が必要",
                    "confidence": "high",
                }
            ]
        )
        assert len(kept) == 1
        assert demoted == []

    def test_value_equals_expected_is_demoted(self):
        """Warning where value == expected is nonsensical and must be removed."""
        kept, demoted = filter_warnings(
            [
                {
                    "verb": "avoir",
                    "pronoun": "il/elle",
                    "value": "a",
                    "expected": "a",
                    "reason": "標準的な形か確認が必要",
                }
            ]
        )
        assert kept == []
        assert len(demoted) == 1

    def test_low_confidence_is_demoted(self):
        kept, demoted = filter_warnings(
            [
                {
                    "verb": "aller",
                    "pronoun": "nous",
                    "value": "allons",
                    "expected": "allons",
                    "reason": "綴り確認",
                    "confidence": "low",
                }
            ]
        )
        assert kept == []
        assert len(demoted) == 1

    def test_empty_list_returns_empty(self):
        kept, demoted = filter_warnings([])
        assert kept == []
        assert demoted == []

    def test_mixed_keeps_valid_removes_invalid(self):
        """Valid and invalid warnings in same list are split correctly."""
        warnings = [
            {
                "verb": "partir",
                "pronoun": "il/elle",
                "value": "part",
                "reason": "初学者には難しい活用形",
            },
            {
                "verb": "commencer",
                "pronoun": "nous",
                "value": "commencons",
                "expected": "commençons",
                "reason": "ç の綴りが誤っています",
                "confidence": "high",
            },
        ]
        kept, demoted = filter_warnings(warnings)
        assert len(kept) == 1
        assert kept[0]["verb"] == "commencer"
        assert len(demoted) == 1
        assert demoted[0]["verb"] == "partir"


# Fixture: false warnings from PR #158 (correct spelling-change forms)
@pytest.fixture()
def pr158_false_warnings():
    return [
        {
            "verb": "commencer",
            "pronoun": "nous",
            "value": "commençons",
            "expected": "commencer",
            "reason": (
                "動詞「commencer」の「nous」形は「commençons」とするのが標準的であり、"
                "また「ç」の使用は正しい。"
            ),
            "action": "地域差・文体差としての位置づけの確認が必要。",
            "confidence": "high",
        },
        {
            "verb": "manger",
            "pronoun": "nous",
            "value": "mangeons",
            "expected": "manger",
            "reason": (
                "動詞「manger」の「nous」形は「mangeons」とするのが標準的であり、"
                "また「g」の後の「e」の使用は正しい。"
            ),
            "action": "地域差・文体差としての位置づけの確認が必要。",
            "confidence": "high",
        },
    ]


class TestPr158SpellingChangeFalsePositives:
    def test_pr158_false_warnings_all_removed(self, pr158_false_warnings):
        """commençons / mangeons は標準形。不定詞 expected は落とす。"""
        kept, demoted = filter_warnings(pr158_false_warnings)
        assert kept == [], f"Expected no kept warnings, got: {kept}"
        assert len(demoted) == 2

    def test_expected_infinitive_is_demoted(self):
        kept, demoted = filter_warnings(
            [
                {
                    "verb": "commencer",
                    "pronoun": "nous",
                    "value": "commençons",
                    "expected": "commencer",
                    "reason": "地域差の確認が必要",
                    "confidence": "high",
                }
            ]
        )
        assert kept == []
        assert len(demoted) == 1

    def test_affirming_standard_form_without_alternative_is_demoted(self):
        kept, demoted = filter_warnings(
            [
                {
                    "verb": "manger",
                    "pronoun": "nous",
                    "value": "mangeons",
                    "reason": (
                        "nous 形は mangeons とするのが標準的であり、e の使用は正しい。"
                    ),
                    "action": "地域差・文体差としての位置づけの確認が必要。",
                    "confidence": "high",
                }
            ]
        )
        assert kept == []
        assert len(demoted) == 1


class TestConjugationSnapshotGating:
    def test_practice_session_pr_does_not_attach_snapshot(self):
        assert not should_attach_conjugation_snapshot(
            [
                "backend/app/domain/practice_session.py",
                "backend/app/domain/tutor.py",
            ]
        )

    def test_conjugation_change_attaches_snapshot(self):
        assert should_attach_conjugation_snapshot(["backend/app/domain/conjugation.py"])

    def test_reference_json_change_attaches_snapshot(self):
        assert should_attach_conjugation_snapshot(
            ["backend/app/domain/french_reference/present_conjugations.json"]
        )

    def test_unchanged_conjugations_prompt_omits_snapshot(self):
        note = conjugation_section_for(["backend/app/domain/practice_session.py"])
        assert "再レビューは不要" in note
        assert "commencer" not in note
        assert "```json" not in note
