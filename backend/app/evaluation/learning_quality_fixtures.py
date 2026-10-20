"""Phase 7 学習品質シミュレーションの固定シナリオ（Issue #206）。

実ユーザーのログは使わない。時計はシナリオの start から日数だけ進む。
回答の正誤は item の behavior と、その日の answer_mode だけで決まる。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from app.domain.tutor import (
    EvidenceSpan,
    LearningItem,
    LearningItemType,
    SourceDocument,
    SourceRef,
)

SIMULATION_START = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)
"""combined シナリオの起点。壁時計は使わない。"""

SPARSE_START = datetime(2026, 4, 6, 9, 0, tzinfo=UTC)

DayPhase = Literal["baseline", "skipped", "difficult", "recovery"]
AnswerMode = Literal["profile", "all_incorrect"]
ItemBehavior = Literal["stable", "production_weak"]

TRACKED_PATTERN_KEY = "grammar_feature:pronominal_verb"
MULTI_CONTEXT_ITEM_ID = "item-000-multi"


@dataclass(frozen=True)
class QualityExpectations:
    """シナリオが組み合わせとして踏むべき長期の不変条件。"""

    require_high_due_backlog: bool = False
    require_known_skip: bool = False
    require_source_cap_pressure: bool = False
    require_duplicate_deferral: bool = False
    require_context_rotation: bool = False
    require_production_only_weakness: bool = False
    require_no_weakness: bool = False
    require_difficult_recovery: bool = False
    require_overdue: bool = False
    require_both_directions: bool = False


@dataclass(frozen=True)
class Arrival:
    """その朝に届く Source と、そこから採用済みにする Item。"""

    source: SourceDocument
    items: tuple[LearningItem, ...] = ()


@dataclass(frozen=True)
class DayScript:
    """1日分の外生入力と、学習者がその日に答えるか。"""

    day_index: int
    phase: DayPhase
    study: bool = True
    answer_mode: AnswerMode = "profile"
    arrivals: tuple[Arrival, ...] = ()


@dataclass(frozen=True)
class LearningQualityScenario:
    """固定 clock で複数日進める synthetic learner。"""

    scenario_id: str
    name: str
    purpose: str
    start: datetime
    days: tuple[DayScript, ...]
    behaviors: tuple[tuple[str, ItemBehavior], ...]
    known_item_ids: frozenset[str]
    tracked_pattern_key: str | None
    tracked_context_item_id: str | None
    expectations: QualityExpectations

    def behavior_for(self, item_id: str) -> ItemBehavior:
        return dict(self.behaviors).get(item_id, "stable")


def _source_with_word(
    source_id: str,
    word: str,
    when: datetime,
    *,
    prefix: str,
) -> tuple[SourceDocument, SourceRef]:
    content = f"{prefix} {word}."
    start = len(prefix) + 1
    end = start + len(word)
    if content[start:end] != word:
        raise ValueError(f"evidence が語と一致しない: {source_id}")
    source = SourceDocument(
        id=source_id,
        title=source_id,
        content=content,
        created_at=when,
    )
    ref = SourceRef(
        source_document_id=source_id,
        evidence_span=EvidenceSpan(start=start, end=end, text=word),
    )
    return source, ref


def _item(
    item_id: str,
    form: str,
    meaning: str,
    refs: list[SourceRef],
    when: datetime,
    *,
    item_type: LearningItemType = "vocabulary",
    metadata: Mapping[str, object] | None = None,
) -> LearningItem:
    return LearningItem(
        id=item_id,
        item_type=item_type,
        canonical_form=form,
        meaning_ja=meaning,
        level="A1",
        source_refs=list(refs),
        created_at=when,
        metadata=dict(metadata or {}),
    )


def _single(
    source_id: str,
    item_id: str,
    form: str,
    meaning: str,
    when: datetime,
    *,
    prefix: str = "Voici",
    item_type: LearningItemType = "vocabulary",
    metadata: Mapping[str, object] | None = None,
) -> tuple[Arrival, str]:
    source, ref = _source_with_word(source_id, form, when, prefix=prefix)
    item = _item(
        item_id,
        form,
        meaning,
        [ref],
        when,
        item_type=item_type,
        metadata=metadata,
    )
    return Arrival(source=source, items=(item,)), item_id


def _at(start: datetime, day: int, *, hours: int = 0) -> datetime:
    return start + timedelta(days=day, hours=hours)


def _build_combined() -> LearningQualityScenario:
    """21日。新規流入、既知、同一表現、弱点、欠席、難しい期間、回復を混ぜる。"""

    start = SIMULATION_START
    behaviors: list[tuple[str, ItemBehavior]] = []
    known: list[str] = []

    def stable(item_id: str) -> None:
        behaviors.append((item_id, "stable"))

    def weak(item_id: str) -> None:
        behaviors.append((item_id, "production_weak"))

    day0: list[Arrival] = []
    multi_refs: list[SourceRef] = []
    for suffix, hours, prefix in (
        ("a", 0, "Voici"),
        ("b", 1, "J'aime"),
        ("c", 2, "Il dit"),
    ):
        source, ref = _source_with_word(
            f"src-multi-{suffix}",
            "au revoir",
            _at(start, 0, hours=hours),
            prefix=prefix,
        )
        multi_refs.append(ref)
        day0.append(Arrival(source=source))
    multi = _item(
        MULTI_CONTEXT_ITEM_ID,
        "au revoir",
        "さようなら",
        multi_refs,
        _at(start, 0),
        item_type="expression",
    )
    day0[-1] = Arrival(source=day0[-1].source, items=(multi,))
    stable(multi.id)

    weak_forms = (
        ("01", "se lever", "起きる"),
        ("02", "se coucher", "寝る"),
        ("03", "s'appeler", "名前を言う"),
    )
    for suffix, form, meaning in weak_forms:
        arrival, item_id = _single(
            f"src-weak-{suffix}",
            f"item-010-weak-{suffix}",
            form,
            meaning,
            _at(start, 0),
            metadata={"grammar_feature": "pronominal_verb"},
        )
        day0.append(arrival)
        weak(item_id)

    for suffix, form, meaning in (("01", "chat", "猫"), ("02", "chien", "犬")):
        arrival, item_id = _single(
            "src-day-00" if suffix == "01" else "src-day-00b",
            f"item-020-day00-{suffix}",
            form,
            meaning,
            _at(start, 0),
        )
        day0.append(arrival)
        stable(item_id)

    known_forms = (("01", "livre", "本"), ("02", "maison", "家"))
    for suffix, form, meaning in known_forms:
        arrival, item_id = _single(
            f"src-known-{suffix}",
            f"item-600-known-{suffix}",
            form,
            meaning,
            _at(start, 0),
        )
        day0.append(arrival)
        known.append(item_id)
        stable(item_id)

    arrival, item_id = _single(
        "src-dup-00",
        "item-700-dup-00",
        "bonjour",
        "こんにちは",
        _at(start, 0),
    )
    day0.append(arrival)
    stable(item_id)

    flood_forms = (
        ("01", "pomme", "りんご"),
        ("02", "banane", "バナナ"),
        ("03", "orange", "オレンジ"),
        ("04", "cerise", "さくらんぼ"),
        ("05", "fraise", "いちご"),
        ("06", "poire", "梨"),
    )
    flood_content = "Dans le panier: " + " ".join(row[1] for row in flood_forms) + "."
    flood_source = SourceDocument(
        id="src-flood",
        title="src-flood",
        content=flood_content,
        created_at=_at(start, 0),
    )
    flood_items: list[LearningItem] = []
    for suffix, form, meaning in flood_forms:
        start_at = flood_content.index(form)
        ref = SourceRef(
            source_document_id="src-flood",
            evidence_span=EvidenceSpan(
                start=start_at,
                end=start_at + len(form),
                text=form,
            ),
        )
        item = _item(
            f"item-800-flood-{suffix}",
            form,
            meaning,
            [ref],
            _at(start, 0),
        )
        flood_items.append(item)
        stable(item.id)
    day0.append(Arrival(source=flood_source, items=tuple(flood_items)))

    days: list[DayScript] = [
        DayScript(
            day_index=0,
            phase="baseline",
            arrivals=tuple(day0),
        )
    ]

    for day in range(1, 7):
        arrival, item_id = _single(
            f"src-dup-{day:02d}",
            f"item-700-dup-{day:02d}",
            "bonjour",
            "こんにちは",
            _at(start, day),
            prefix="Encore",
        )
        stable(item_id)
        days.append(
            DayScript(
                day_index=day,
                phase="baseline",
                arrivals=(arrival,),
            )
        )

    for day in (7, 8):
        days.append(DayScript(day_index=day, phase="skipped", study=False))

    difficult_forms = (
        (9, (("gare", "駅"), ("train", "列車"))),
        (10, (("bus", "バス"), ("velo", "自転車"))),
        (11, (("pain", "パン"), ("fromage", "チーズ"))),
    )
    for day, pairs in difficult_forms:
        arrivals: list[Arrival] = []
        for index, (form, meaning) in enumerate(pairs, start=1):
            arrival, item_id = _single(
                f"src-day-{day:02d}-{index}",
                f"item-900-day{day:02d}-{index}",
                form,
                meaning,
                _at(start, day),
            )
            arrivals.append(arrival)
            stable(item_id)
        days.append(
            DayScript(
                day_index=day,
                phase="difficult",
                answer_mode="all_incorrect",
                arrivals=tuple(arrivals),
            )
        )

    recovery_forms = (
        "eau",
        "cafe",
        "the",
        "vin",
        "lundi",
        "mardi",
        "mercredi",
        "jeudi",
        "vendredi",
    )
    meanings = (
        "水",
        "コーヒー",
        "お茶",
        "ワイン",
        "月曜",
        "火曜",
        "水曜",
        "木曜",
        "金曜",
    )
    for offset, (form, meaning) in enumerate(
        zip(recovery_forms, meanings, strict=True)
    ):
        day = 12 + offset
        arrival, item_id = _single(
            f"src-day-{day:02d}",
            f"item-910-day{day:02d}",
            form,
            meaning,
            _at(start, day),
        )
        stable(item_id)
        days.append(
            DayScript(
                day_index=day,
                phase="recovery",
                arrivals=(arrival,),
            )
        )

    return LearningQualityScenario(
        scenario_id="combined-21d",
        name="21日の混合学習",
        purpose=(
            "新規流入、既知項目、同一表現、production の弱点、"
            "欠席による overdue、難しい期間と回復を同時に通す"
        ),
        start=start,
        days=tuple(days),
        behaviors=tuple(behaviors),
        known_item_ids=frozenset(known),
        tracked_pattern_key=TRACKED_PATTERN_KEY,
        tracked_context_item_id=MULTI_CONTEXT_ITEM_ID,
        expectations=QualityExpectations(
            require_high_due_backlog=True,
            require_known_skip=True,
            require_source_cap_pressure=True,
            require_duplicate_deferral=True,
            require_context_rotation=True,
            require_production_only_weakness=True,
            require_difficult_recovery=True,
            require_overdue=True,
            require_both_directions=True,
        ),
    )


def _build_sparse() -> LearningQualityScenario:
    """1 Item の少数誤答では WeaknessPattern を断定しない。"""

    start = SPARSE_START
    days: list[DayScript] = []
    behaviors: list[tuple[str, ItemBehavior]] = []
    for day in range(3):
        arrivals: tuple[Arrival, ...] = ()
        if day == 0:
            arrival, item_id = _single(
                "src-sparse",
                "item-sparse",
                "pourtant",
                "それなのに",
                _at(start, 0),
                metadata={"grammar_feature": "pronominal_verb"},
            )
            arrivals = (arrival,)
            behaviors.append((item_id, "stable"))
        days.append(
            DayScript(
                day_index=day,
                phase="baseline",
                answer_mode="all_incorrect",
                arrivals=arrivals,
            )
        )
    return LearningQualityScenario(
        scenario_id="sparse-errors-3d",
        name="少数誤答",
        purpose="1 Item の短い誤答だけでは横断の弱点にしない",
        start=start,
        days=tuple(days),
        behaviors=tuple(behaviors),
        known_item_ids=frozenset(),
        tracked_pattern_key=TRACKED_PATTERN_KEY,
        tracked_context_item_id=None,
        expectations=QualityExpectations(require_no_weakness=True),
    )


COMBINED_SCENARIO = _build_combined()
SPARSE_SCENARIO = _build_sparse()
LEARNING_QUALITY_SCENARIOS: tuple[LearningQualityScenario, ...] = (
    COMBINED_SCENARIO,
    SPARSE_SCENARIO,
)


def get_scenario(scenario_id: str) -> LearningQualityScenario:
    key = scenario_id.casefold()
    for scenario in LEARNING_QUALITY_SCENARIOS:
        if scenario.scenario_id.casefold() == key:
            return scenario
    known = ", ".join(row.scenario_id for row in LEARNING_QUALITY_SCENARIOS)
    raise KeyError(f"未知の scenario: {scenario_id}（{known}）")
