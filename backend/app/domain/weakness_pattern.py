"""複数 LearningItem を横断した苦手パターン検出（Issue #203 / Phase 7）。

個別 Item の recent error ではなく、同じ metadata / tag を持つ Item 群の
誤答が閾値を超えたときだけ WeaknessPattern にする。自由なクラスタリングや
LLM は使わない。metadata が無い特徴は、表記や辞書から推測しない。

```text
LearningItem.metadata / item_type + LearningEvent
  -> aggregate_weakness_patterns()
  -> WeaknessPattern（recognition / production 別）
  -> 検出済みだけを RecommendationSignalSnapshot の補助 signal にする
```

このモジュールが依存してよいのは Python 標準ライブラリ、Pydantic、
`domain.tutor` のみ。DB / FastAPI / OpenAI には依存しない。
wall clock は呼ばない。`now` は呼び出し側が渡す。
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.tutor import (
    LearningEvent,
    LearningItem,
    SkillDirection,
    skill_direction_for_event,
)

# ---------------------------------------------------------------------------
# 定数（閾値はここだけを変えて調整する）
# ---------------------------------------------------------------------------

PATTERN_VERSION = "weakness-pattern-v1"
"""集計規則の版。閾値や taxonomy を変えたら bump する。"""

RECENT_WINDOW_DAYS = 14
"""苦手判定に使う直近窓。これより古い誤答だけでは断定しない。"""

MIN_ATTEMPTS = 4
"""direction ごとの直近 attempt がこれ未満なら苦手としない。"""

MIN_DISTINCT_ITEMS = 2
"""直近に attempt がある Item がこれ未満なら、1 Item の誤答をパターンにしない。"""

MIN_RECENT_INCORRECT = 2
"""直近の誤答件数がこれ未満なら苦手としない。"""

ERROR_RATE_THRESHOLD = 0.5
"""直近 error rate がこれ未満なら苦手としない。"""

RATE_DECIMALS = 6
"""同じ入力で同じ error rate になるよう丸める桁。"""

PATTERN_DIMENSIONS: tuple[str, ...] = (
    "item_type",
    "grammar_feature",
    "verb_group",
    "tense",
    "mood",
    "noun_gender",
    "pronominal",
)
"""説明可能な taxonomy。この外の dimension は tag から読まない。"""

PatternDimension = Literal[
    "item_type",
    "grammar_feature",
    "verb_group",
    "tense",
    "mood",
    "noun_gender",
    "pronominal",
]

_SKILL_DIRECTIONS: tuple[SkillDirection, ...] = ("recognition", "production")

_KNOWN_VERB_GROUPS = frozenset({"er", "ir", "re", "irregular"})
_KNOWN_GENDERS = frozenset({"masculine", "feminine"})
_PRONOMINAL_TRUE = frozenset({"true", "yes", "pronominal", "1"})

_LABELS: dict[str, dict[str, str]] = {
    "item_type": {
        "vocabulary": "語彙",
        "expression": "表現",
        "grammar": "文法",
        "conjugation": "動詞活用",
    },
    "verb_group": {
        "er": "-er 動詞",
        "ir": "-ir 動詞",
        "re": "-re 動詞",
        "irregular": "不規則動詞",
    },
    "noun_gender": {
        "masculine": "男性名詞",
        "feminine": "女性名詞",
    },
    "pronominal": {
        "true": "代名動詞",
    },
    "grammar_feature": {
        "noun_with_article": "冠詞付き名詞",
        "pronominal_verb": "代名動詞",
        "il_faut": "il faut 系",
    },
    "tense": {
        "présent": "現在形",
        "imparfait": "半過去",
        "futur": "単純未来",
        "passé composé": "複合過去",
        "plus-que-parfait": "大過去",
    },
    "mood": {
        "indicatif": "直説法",
        "subjonctif": "接続法",
        "conditionnel": "条件法",
        "impératif": "命令法",
    },
}


# ---------------------------------------------------------------------------
# モデル
# ---------------------------------------------------------------------------


class PatternTag(BaseModel):
    """1 Item に明示されている pattern。推測で作らない。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dimension: PatternDimension
    value: str = Field(min_length=1)
    pattern_key: str = Field(min_length=1)
    label: str = Field(min_length=1)


class PatternDirectionStats(BaseModel):
    """recognition または production の集計。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    skill_direction: SkillDirection
    attempt_count: int = Field(ge=0)
    incorrect_count: int = Field(ge=0)
    error_rate: float = Field(ge=0.0, le=1.0)
    affected_item_count: int = Field(ge=0)
    recent_attempt_count: int = Field(ge=0)
    recent_incorrect_count: int = Field(ge=0)
    recent_error_count: int = Field(ge=0)
    recent_error_rate: float = Field(ge=0.0, le=1.0)
    recent_affected_item_count: int = Field(ge=0)
    evidence_item_ids: tuple[str, ...] = ()
    """直近窓で誤答した Item。昇順。"""
    is_weakness: bool = False

    @model_validator(mode="after")
    def _check_counts(self) -> PatternDirectionStats:
        if self.incorrect_count > self.attempt_count:
            raise ValueError("incorrect_count は attempt_count を超えない")
        if self.recent_incorrect_count > self.recent_attempt_count:
            raise ValueError("recent incorrect は recent attempt を超えない")
        if self.recent_error_count != self.recent_incorrect_count:
            raise ValueError("recent_error_count は recent_incorrect_count と一致する")
        if self.affected_item_count < self.recent_affected_item_count:
            raise ValueError("affected は直近の Item 数以上")
        if len(self.evidence_item_ids) != len(set(self.evidence_item_ids)):
            raise ValueError("evidence_item_ids は重複しない")
        if tuple(sorted(self.evidence_item_ids)) != self.evidence_item_ids:
            raise ValueError("evidence_item_ids は昇順")
        return self


class WeaknessPattern(BaseModel):
    """1 pattern の横断集計。is_weakness が False でも集計自体は残す。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pattern_key: str = Field(min_length=1)
    dimension: PatternDimension
    value: str = Field(min_length=1)
    label: str = Field(min_length=1)
    attempt_count: int = Field(ge=1)
    incorrect_count: int = Field(ge=0)
    error_rate: float = Field(ge=0.0, le=1.0)
    affected_item_count: int = Field(ge=1)
    by_direction: dict[SkillDirection, PatternDirectionStats]
    recent_attempt_count: int = Field(ge=0)
    recent_error_count: int = Field(ge=0)
    recent_error_rate: float = Field(ge=0.0, le=1.0)
    evidence_item_ids: tuple[str, ...] = ()
    weak_directions: tuple[SkillDirection, ...] = ()
    is_weakness: bool
    computed_at: datetime
    version: str = PATTERN_VERSION

    @model_validator(mode="after")
    def _check_pattern(self) -> WeaknessPattern:
        if set(self.by_direction) != set(_SKILL_DIRECTIONS):
            raise ValueError("recognition と production の両方を持つ")
        if self.is_weakness != bool(self.weak_directions):
            raise ValueError("is_weakness と weak_directions が一致しない")
        expected = tuple(
            direction
            for direction in _SKILL_DIRECTIONS
            if self.by_direction[direction].is_weakness
        )
        if self.weak_directions != expected:
            raise ValueError("weak_directions は direction 順")
        if self.incorrect_count > self.attempt_count:
            raise ValueError("incorrect_count は attempt_count を超えない")
        if tuple(sorted(self.evidence_item_ids)) != self.evidence_item_ids:
            raise ValueError("evidence_item_ids は昇順")
        return self


class WeaknessPatternReport(BaseModel):
    """同じ Item・Event・now から毎回同じ集計。永続化しない。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    computed_at: datetime
    version: str = PATTERN_VERSION
    patterns: tuple[WeaknessPattern, ...] = ()
    weaknesses: tuple[WeaknessPattern, ...] = ()

    @model_validator(mode="after")
    def _check_report(self) -> WeaknessPatternReport:
        keys = [row.pattern_key for row in self.patterns]
        if keys != sorted(keys):
            raise ValueError("patterns は pattern_key 昇順")
        weak = tuple(row for row in self.patterns if row.is_weakness)
        if self.weaknesses != weak:
            raise ValueError("weaknesses は検出済み pattern と一致する")
        if any(row.computed_at != self.computed_at for row in self.patterns):
            raise ValueError("pattern の computed_at は report と一致する")
        if any(row.version != self.version for row in self.patterns):
            raise ValueError("pattern の version は report と一致する")
        return self


class WeaknessPatternHint(BaseModel):
    """検出済みパターンのうち、1 Item × direction の補助 signal。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pattern_key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    skill_direction: SkillDirection
    recent_error_count: int = Field(ge=1)
    error_rate: float = Field(ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# tag 抽出（明示 metadata のみ）
# ---------------------------------------------------------------------------


def _require_aware_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError("timezone-aware な datetime が必要")
    return dt.astimezone(UTC)


def _normalize_token(value: str) -> str:
    text = unicodedata.normalize("NFC", value).strip()
    return " ".join(text.split()).casefold()


def _plain_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def pattern_label(dimension: str, normalized_value: str) -> str:
    """既知の値だけ日本語ラベルにする。未知の明示値はその文字列を使う。"""
    known = _LABELS.get(dimension, {}).get(normalized_value)
    if known is not None:
        return known
    return normalized_value


def _tag(dimension: PatternDimension, raw_value: str) -> PatternTag:
    value = _normalize_token(raw_value)
    if dimension == "verb_group":
        stripped = value.lstrip("-")
        if stripped in _KNOWN_VERB_GROUPS:
            value = stripped
    return PatternTag(
        dimension=dimension,
        value=value,
        pattern_key=f"{dimension}:{value}",
        label=pattern_label(dimension, value),
    )


def _gender_token(value: object) -> str | None:
    text = _plain_string(value)
    if text is None:
        return None
    token = _normalize_token(text)
    if token in _KNOWN_GENDERS:
        return token
    return None


def _explicit_gender(metadata: Mapping[str, object]) -> str | None:
    noun_gender = _gender_token(metadata.get("noun_gender"))
    gender = _gender_token(metadata.get("gender"))
    if noun_gender is not None and gender is not None and noun_gender != gender:
        return None
    return noun_gender or gender


def _explicit_pronominal(metadata: Mapping[str, object]) -> bool:
    value = metadata.get("pronominal")
    if value is True:
        return True
    text = _plain_string(value)
    if text is None:
        return False
    return _normalize_token(text) in _PRONOMINAL_TRUE


def _parse_explicit_tag(raw: object) -> PatternTag | None:
    text = _plain_string(raw)
    if text is None or ":" not in text:
        return None
    dimension_raw, value_raw = text.split(":", 1)
    dimension = _normalize_token(dimension_raw)
    if dimension not in PATTERN_DIMENSIONS or dimension == "item_type":
        return None
    if not value_raw.strip():
        return None
    if dimension == "noun_gender":
        gender = _gender_token(value_raw)
        if gender is None:
            return None
        return _tag("noun_gender", gender)
    if dimension == "pronominal":
        if _normalize_token(value_raw) not in _PRONOMINAL_TRUE:
            return None
        return _tag("pronominal", "true")
    builders = {
        "grammar_feature": lambda value: _tag("grammar_feature", value),
        "verb_group": lambda value: _tag("verb_group", value),
        "tense": lambda value: _tag("tense", value),
        "mood": lambda value: _tag("mood", value),
    }
    build = builders.get(dimension)
    if build is None:
        return None
    return build(value_raw)


def extract_pattern_tags(item: LearningItem) -> tuple[PatternTag, ...]:
    """Item に書いてある tag だけを返す。表記や名詞辞書からは補わない。"""
    tags: dict[str, PatternTag] = {}

    def add(tag: PatternTag) -> None:
        tags.setdefault(tag.pattern_key, tag)

    add(_tag("item_type", item.item_type))
    metadata = item.metadata

    grammar = _plain_string(metadata.get("grammar_feature"))
    if grammar is not None:
        add(_tag("grammar_feature", grammar))

    verb_group = _plain_string(metadata.get("verb_group"))
    if verb_group is not None:
        add(_tag("verb_group", verb_group))

    tense = _plain_string(metadata.get("tense"))
    if tense is not None:
        add(_tag("tense", tense))

    mood = _plain_string(metadata.get("mood"))
    if mood is not None:
        add(_tag("mood", mood))

    gender = _explicit_gender(metadata)
    if gender is not None:
        add(_tag("noun_gender", gender))

    if _explicit_pronominal(metadata):
        add(_tag("pronominal", "true"))

    raw_tags = metadata.get("tags")
    if isinstance(raw_tags, list):
        for raw in raw_tags:
            parsed = _parse_explicit_tag(raw)
            if parsed is not None:
                add(parsed)

    return tuple(sorted(tags.values(), key=lambda tag: tag.pattern_key))


# ---------------------------------------------------------------------------
# 集計
# ---------------------------------------------------------------------------


class _DirectionBucket:
    def __init__(self) -> None:
        self.attempts: dict[str, int] = {}
        self.incorrect: dict[str, int] = {}
        self.recent_attempts: dict[str, int] = {}
        self.recent_incorrect: dict[str, int] = {}

    def add(self, item_id: str, *, incorrect: bool, recent: bool) -> None:
        self.attempts[item_id] = self.attempts.get(item_id, 0) + 1
        if incorrect:
            self.incorrect[item_id] = self.incorrect.get(item_id, 0) + 1
        if recent:
            self.recent_attempts[item_id] = self.recent_attempts.get(item_id, 0) + 1
            if incorrect:
                self.recent_incorrect[item_id] = (
                    self.recent_incorrect.get(item_id, 0) + 1
                )


def _rate(incorrect: int, attempt: int) -> float:
    if attempt <= 0:
        return 0.0
    return round(incorrect / attempt, RATE_DECIMALS)


def _is_direction_weak(stats: PatternDirectionStats) -> bool:
    return (
        stats.recent_attempt_count >= MIN_ATTEMPTS
        and stats.recent_affected_item_count >= MIN_DISTINCT_ITEMS
        and stats.recent_incorrect_count >= MIN_RECENT_INCORRECT
        and stats.recent_error_rate >= ERROR_RATE_THRESHOLD
    )


def _direction_stats(
    direction: SkillDirection, bucket: _DirectionBucket
) -> PatternDirectionStats:
    attempt_count = sum(bucket.attempts.values())
    incorrect_count = sum(bucket.incorrect.values())
    recent_attempt_count = sum(bucket.recent_attempts.values())
    recent_incorrect_count = sum(bucket.recent_incorrect.values())
    evidence = tuple(
        sorted(item_id for item_id, count in bucket.recent_incorrect.items() if count)
    )
    stats = PatternDirectionStats(
        skill_direction=direction,
        attempt_count=attempt_count,
        incorrect_count=incorrect_count,
        error_rate=_rate(incorrect_count, attempt_count),
        affected_item_count=len(bucket.attempts),
        recent_attempt_count=recent_attempt_count,
        recent_incorrect_count=recent_incorrect_count,
        recent_error_count=recent_incorrect_count,
        recent_error_rate=_rate(recent_incorrect_count, recent_attempt_count),
        recent_affected_item_count=len(bucket.recent_attempts),
        evidence_item_ids=evidence,
        is_weakness=False,
    )
    return stats.model_copy(update={"is_weakness": _is_direction_weak(stats)})


def _pattern_from_buckets(
    tag: PatternTag,
    buckets: Mapping[SkillDirection, _DirectionBucket],
    *,
    computed_at: datetime,
) -> WeaknessPattern:
    by_direction = {
        direction: _direction_stats(direction, buckets[direction])
        for direction in _SKILL_DIRECTIONS
    }
    attempt_count = sum(row.attempt_count for row in by_direction.values())
    incorrect_count = sum(row.incorrect_count for row in by_direction.values())
    recent_attempt_count = sum(
        row.recent_attempt_count for row in by_direction.values()
    )
    recent_error_count = sum(row.recent_error_count for row in by_direction.values())
    affected: set[str] = set()
    evidence: set[str] = set()
    for bucket in buckets.values():
        affected.update(bucket.attempts)
    for row in by_direction.values():
        evidence.update(row.evidence_item_ids)
    weak_directions = tuple(
        direction
        for direction in _SKILL_DIRECTIONS
        if by_direction[direction].is_weakness
    )
    return WeaknessPattern(
        pattern_key=tag.pattern_key,
        dimension=tag.dimension,
        value=tag.value,
        label=tag.label,
        attempt_count=attempt_count,
        incorrect_count=incorrect_count,
        error_rate=_rate(incorrect_count, attempt_count),
        affected_item_count=len(affected),
        by_direction=by_direction,
        recent_attempt_count=recent_attempt_count,
        recent_error_count=recent_error_count,
        recent_error_rate=_rate(recent_error_count, recent_attempt_count),
        evidence_item_ids=tuple(sorted(evidence)),
        weak_directions=weak_directions,
        is_weakness=bool(weak_directions),
        computed_at=computed_at,
        version=PATTERN_VERSION,
    )


def aggregate_weakness_patterns(
    items: Sequence[LearningItem],
    events: Sequence[LearningEvent],
    *,
    now: datetime,
) -> WeaknessPatternReport:
    """Item 横断で pattern を集計する。同じ入力と now なら同じ結果。

    苦手判定は direction ごと、直近 RECENT_WINDOW_DAYS の attempt だけを見る。
    窓の外の誤答は attempt_count には残るが、それだけでは is_weakness にしない。
    SkillDirection は exercise_type から決め、event metadata では上書きしない。
    """
    computed_at = _require_aware_utc(now)
    window_start = computed_at - timedelta(days=RECENT_WINDOW_DAYS)
    items_by_id: dict[str, LearningItem] = {}
    for item in items:
        items_by_id.setdefault(item.id, item)

    seen_event_ids: set[str] = set()
    tags_by_key: dict[str, PatternTag] = {}
    buckets: dict[str, dict[SkillDirection, _DirectionBucket]] = {}

    for event in events:
        if event.id in seen_event_ids:
            continue
        seen_event_ids.add(event.id)
        item = items_by_id.get(event.learning_item_id)
        if item is None:
            continue
        direction = skill_direction_for_event(event)
        if direction is None:
            continue
        occurred_at = _require_aware_utc(event.occurred_at)
        if occurred_at > computed_at:
            continue
        recent = occurred_at >= window_start
        incorrect = event.result == "incorrect"
        for tag in extract_pattern_tags(item):
            tags_by_key.setdefault(tag.pattern_key, tag)
            pattern_buckets = buckets.setdefault(
                tag.pattern_key,
                {name: _DirectionBucket() for name in _SKILL_DIRECTIONS},
            )
            pattern_buckets[direction].add(item.id, incorrect=incorrect, recent=recent)

    patterns = tuple(
        _pattern_from_buckets(
            tags_by_key[pattern_key],
            buckets[pattern_key],
            computed_at=computed_at,
        )
        for pattern_key in sorted(buckets)
    )
    return WeaknessPatternReport(
        computed_at=computed_at,
        version=PATTERN_VERSION,
        patterns=patterns,
        weaknesses=tuple(row for row in patterns if row.is_weakness),
    )


def weakness_hints_for_item(
    learning_item_id: str,
    report: WeaknessPatternReport,
) -> tuple[WeaknessPatternHint, ...]:
    """その Item が直近誤答の根拠になっている検出済み pattern だけを返す。"""
    hints: list[WeaknessPatternHint] = []
    for pattern in report.weaknesses:
        for direction in pattern.weak_directions:
            stats = pattern.by_direction[direction]
            if learning_item_id not in stats.evidence_item_ids:
                continue
            hints.append(
                WeaknessPatternHint(
                    pattern_key=pattern.pattern_key,
                    label=pattern.label,
                    skill_direction=direction,
                    recent_error_count=stats.recent_error_count,
                    error_rate=stats.recent_error_rate,
                )
            )
    hints.sort(key=lambda hint: (hint.pattern_key, hint.skill_direction))
    return tuple(hints)


def pattern_reason_notes(
    hints: Sequence[WeaknessPatternHint],
) -> dict[str, str]:
    """reason code → パターン名を含む説明。句点は付けない。"""
    notes: dict[str, str] = {}
    production = [hint for hint in hints if hint.skill_direction == "production"]
    recognition = [hint for hint in hints if hint.skill_direction == "recognition"]
    if production:
        notes["PRODUCTION_PATTERN_WEAKNESS"] = _pattern_sentence(
            production, "production"
        )
    if recognition:
        notes["PATTERN_RECENT_ERRORS"] = _pattern_sentence(recognition, "recognition")
    return notes


def _pattern_sentence(
    hints: Sequence[WeaknessPatternHint], direction: SkillDirection
) -> str:
    label = _join_labels(hints)
    if direction == "production":
        return f"最近、{label}の自力回答で間違いが続いています"
    return f"最近、{label}を見て答える問題で間違いが続いています"


def _join_labels(hints: Sequence[WeaknessPatternHint]) -> str:
    labels: list[str] = []
    for hint in sorted(hints, key=lambda row: row.pattern_key):
        if hint.label not in labels:
            labels.append(hint.label)
    if not labels:
        return "このパターン"
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]}と{labels[1]}"
    return f"{labels[0]}、{labels[1]}など"


__all__ = [
    "ERROR_RATE_THRESHOLD",
    "MIN_ATTEMPTS",
    "MIN_DISTINCT_ITEMS",
    "MIN_RECENT_INCORRECT",
    "PATTERN_DIMENSIONS",
    "PATTERN_VERSION",
    "RECENT_WINDOW_DAYS",
    "PatternDirectionStats",
    "PatternDimension",
    "PatternTag",
    "WeaknessPattern",
    "WeaknessPatternHint",
    "WeaknessPatternReport",
    "aggregate_weakness_patterns",
    "extract_pattern_tags",
    "pattern_label",
    "pattern_reason_notes",
    "weakness_hints_for_item",
]
