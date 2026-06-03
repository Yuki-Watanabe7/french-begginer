"""Regression tests for llm_domain_review post-processing.

Guards against false warnings on correct French conjugations (see Issue #93).
"""

import pytest
from llm_domain_review import filter_warnings


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
