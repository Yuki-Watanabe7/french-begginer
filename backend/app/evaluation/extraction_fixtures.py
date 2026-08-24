"""LLM抽出品質評価用の固定 Source fixture（Issue #136）。

期待値は完全一致リストではない。must-include / must-not-hallucinate /
acceptable variants を分けて定義する。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.tutor import LearningItemType, SourceDocument

ALLOWED_ITEM_TYPES: frozenset[LearningItemType] = frozenset(
    ("vocabulary", "expression", "grammar", "conjugation")
)


@dataclass(frozen=True)
class MustHaveExpectation:
    """必ず拾ってほしい学習対象。canonical は許容表記の集合で照合する。"""

    label: str
    item_types: frozenset[LearningItemType]
    variants: tuple[str, ...]


@dataclass(frozen=True)
class ExtractionQualityFixture:
    """1件の固定 Source と、その抽出結果に対する評価期待値。"""

    fixture_id: str
    title: str
    content: str
    purpose: str
    must_include: tuple[MustHaveExpectation, ...]
    must_not_hallucinate: tuple[str, ...]
    max_candidates: int
    notes: str = ""

    def source_document(self) -> SourceDocument:
        return SourceDocument(title=self.title, content=self.content)


FIXTURE_A = ExtractionQualityFixture(
    fixture_id="A",
    title="表現 + 文法 + 語彙",
    content="Je me suis rendu compte qu'il fallait changer de stratégie.",
    purpose="表現・文法（または活用）・語彙を同時に拾えること",
    must_include=(
        MustHaveExpectation(
            label="se rendre compte de",
            item_types=frozenset({"expression"}),
            variants=(
                "se rendre compte de",
                "se rendre compte",
                "s'en rendre compte",
            ),
        ),
        MustHaveExpectation(
            label="il faut / falloir",
            item_types=frozenset({"grammar", "conjugation"}),
            variants=(
                "il faut",
                "falloir",
                "il fallait",
                "falloir (imparfait)",
                "il faut que",
            ),
        ),
        MustHaveExpectation(
            label="stratégie",
            item_types=frozenset({"vocabulary"}),
            variants=("stratégie",),
        ),
    ),
    must_not_hallucinate=(
        "bonjour",
        "pomme",
        "rendez-vous",
        "voyage",
        "il s'agit de",
    ),
    max_candidates=12,
    notes=(
        "完全一致は要求しない。"
        "se rendre compte / se rendre compte de は同一 must-have の許容表記。"
        "il faut と falloir は grammar でも conjugation でもよい。"
    ),
)

FIXTURE_B = ExtractionQualityFixture(
    fixture_id="B",
    title="初級の短文",
    content="Je mange une pomme.",
    purpose="基本語彙しかない短文で過剰抽出しないこと",
    must_include=(
        MustHaveExpectation(
            label="pomme",
            item_types=frozenset({"vocabulary"}),
            variants=("pomme", "une pomme"),
        ),
        MustHaveExpectation(
            label="manger",
            item_types=frozenset({"conjugation", "vocabulary"}),
            variants=("manger", "mange"),
        ),
    ),
    must_not_hallucinate=(
        "se rendre compte",
        "se rendre compte de",
        "stratégie",
        "il s'agit de",
        "rendez-vous",
        "bonjour",
    ),
    max_candidates=6,
    notes=("4語程度の短文から候補を大量に作らない。本文にない再利用表現を創作しない。"),
)

FIXTURE_C = ExtractionQualityFixture(
    fixture_id="C",
    title="複数の再利用表現",
    content=("Il s'agit de prendre rendez-vous. Il vaut mieux y aller tout de suite."),
    purpose="単語だけでなく phrase 単位の再利用表現を拾えること",
    must_include=(
        MustHaveExpectation(
            label="il s'agit de",
            item_types=frozenset({"expression", "grammar"}),
            variants=(
                "il s'agit de",
                "s'agir de",
                "s'agit de",
            ),
        ),
        MustHaveExpectation(
            label="prendre rendez-vous",
            item_types=frozenset({"expression"}),
            variants=(
                "prendre rendez-vous",
                "prendre un rendez-vous",
            ),
        ),
        MustHaveExpectation(
            label="il vaut mieux",
            item_types=frozenset({"expression", "grammar"}),
            variants=(
                "il vaut mieux",
                "valoir mieux",
                "vaut mieux",
            ),
        ),
    ),
    must_not_hallucinate=(
        "bonjour",
        "pomme",
        "stratégie",
        "se rendre compte",
    ),
    max_candidates=12,
    notes=(
        "rendez-vous を語彙として拾うだけでは prendre rendez-vous の "
        "must-have を満たさない。phrase 単位であること。"
    ),
)

FIXTURE_D = ExtractionQualityFixture(
    fixture_id="D",
    title="不規則活用・文法",
    content="Je suis allé à Paris et j'ai fait un gâteau.",
    purpose="活用・文法候補が不自然な表層形だけにならないこと",
    must_include=(
        MustHaveExpectation(
            label="aller",
            item_types=frozenset({"conjugation"}),
            variants=(
                "aller",
                "être allé",
                "aller (passé composé)",
            ),
        ),
        MustHaveExpectation(
            label="faire",
            item_types=frozenset({"conjugation"}),
            variants=(
                "faire",
                "avoir fait",
                "faire (passé composé)",
            ),
        ),
        MustHaveExpectation(
            label="passé composé",
            item_types=frozenset({"grammar"}),
            variants=(
                "passé composé",
                "passé composé avec être",
                "passé composé avec avoir",
                "passé composé (être / avoir)",
            ),
        ),
    ),
    must_not_hallucinate=(
        "bonjour",
        "pomme",
        "se rendre compte",
        "rendez-vous",
        "stratégie",
    ),
    max_candidates=12,
    notes=(
        "suis allé / ai fait を vocabulary の表層形として拾うだけでは不足。"
        "aller / faire の conjugation、または passé composé の grammar を期待する。"
        "正しい不規則活用であること自体は減点理由にしない。"
    ),
)

EXTRACTION_QUALITY_FIXTURES: tuple[ExtractionQualityFixture, ...] = (
    FIXTURE_A,
    FIXTURE_B,
    FIXTURE_C,
    FIXTURE_D,
)

FIXTURES_BY_ID: dict[str, ExtractionQualityFixture] = {
    fixture.fixture_id: fixture for fixture in EXTRACTION_QUALITY_FIXTURES
}


def get_fixture(fixture_id: str) -> ExtractionQualityFixture:
    try:
        return FIXTURES_BY_ID[fixture_id]
    except KeyError as exc:
        known = ", ".join(FIXTURES_BY_ID)
        raise KeyError(f"未知の fixture id: {fixture_id}. 定義済み: {known}") from exc
