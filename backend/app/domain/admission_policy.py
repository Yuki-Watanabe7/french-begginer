"""新規 LearningItem の流入量を制御する admission policy（Issue #200 / Phase 7）。

accepted 済みの未学習在庫から、「今、新規学習の対象にしてよい Item」だけを
導出する。永続 status は増やさない。defer は reject ではなく、同じ Item でも
due 負債や Source 占有が変われば再度 eligible になる。

```text
accepted LearningItems
  -> unseen backlog
  -> decide_new_admissions()
  -> eligible-for-new-learning
  -> Phase 5 ranking / Daily Learning Plan
```

このモジュールが依存してよいのは Python 標準ライブラリ、Pydantic、
`domain.tutor`、`domain.recommendation_signal`、`domain.recommendation_ranking`
のみ。DB / FastAPI / OpenAI には依存しない。wall clock は呼ばない。
ranking の式と Daily Learning Plan の `max_new_count` は変えない。
admission は new_practice の入力在庫を絞るだけで、復習候補は通す。

初期定数は、Phase 5 のデフォルト `max_new_count`（3）と、
Phase 6 vertical slice（新規 7 件、同一 Source 最大 2 件、due 0）を
満たしたまま調整できる値にしてある。
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.recommendation_ranking import (
    RankedRecommendation,
    infer_activity_kind,
)
from app.domain.recommendation_signal import (
    NEUTRAL_IMPORTANCE_WEIGHT,
    NEUTRAL_INTEREST_WEIGHT,
    RecommendationSignalSnapshot,
)
from app.domain.tutor import LearningItem, SourceDocument

# ---------------------------------------------------------------------------
# 定数（閾値はここだけを変えて調整する）
# ---------------------------------------------------------------------------

POLICY_VERSION = "admission-v1"
"""このモジュールが書き込む policy_version。選別規則の変更時は bump する。"""

NORMAL_NEW_ADMISSION_CAP = 8
"""due 負債が小さいときの新規 eligible 上限。max_new_count より広い在庫。"""

REDUCED_NEW_ADMISSION_CAP = 1
"""due が soft 閾値以上のときに残す新規枠。0 ではなく少数。"""

SUPPRESSED_NEW_ADMISSION_CAP = 0
"""due が hard 閾値以上のときに新規流入を止める。"""

DUE_BACKLOG_SOFT_THRESHOLD = 8
"""due direction 件数がこれ以上なら新規枠を REDUCED まで下げる。"""

DUE_BACKLOG_HARD_THRESHOLD = 16
"""due direction 件数がこれ以上なら新規枠を 0 にする。"""

DAILY_INTRODUCTION_QUOTA = NORMAL_NEW_ADMISSION_CAP
"""直近に導入済みの新規がこの件数に達したら、追加の eligible を出さない。"""

RECENT_INTRODUCTION_WINDOW_DAYS = 1
"""導入済みと数える最初の学習イベントの窓。日数。"""

PER_SOURCE_ADMISSION_CAP = 2
"""同一 Source から eligible にしてよい件数。在庫枠の全占有を防ぐ。"""

LEVEL_DISTANCE_DEFER_THRESHOLD = 3
"""learner との CEFR 距離がこれ以上なら今は defer。None（不明）は対象外。"""

RECENCY_SATURATION_DAYS = 30.0
"""source_recency_days を優先度 0 にする日数。ranking と同じ飽和点。"""

MAX_LEVEL_DISTANCE = 5
"""CEFR A1↔C2。優先度の正規化にだけ使う。不明レベルはこの距離にしない。"""

UNKNOWN_LEVEL_PRIORITY = 0.5
"""level 不明の優先度。0 にすると事実上の排除になるため中立にする。"""

PRIORITY_DECIMALS = 6
"""同一入力で同一順序にするための丸め桁。"""

AdmissionOutcome = Literal["admit", "defer"]

AdmissionReasonCode = Literal[
    "REVIEW_BACKLOG_HIGH",
    "SOURCE_DAILY_CAP",
    "LEVEL_TOO_FAR_FOR_NOW",
    "HIGHER_PRIORITY_NEW_EXISTS",
    "DUPLICATE_OR_REDUNDANT",
]
"""defer 理由。admit には付けない。Candidate の reject とは別。"""

_APOSTROPHE_TRANSLATION = str.maketrans(
    {
        "’": "'",
        "‘": "'",
        "`": "'",
        "´": "'",
    }
)


# ---------------------------------------------------------------------------
# 入力 / 出力
# ---------------------------------------------------------------------------


class UnseenBacklogItem(BaseModel):
    """admission が並べる未学習 Item。LearningItem.status は持たない。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    learning_item_id: str = Field(min_length=1)
    canonical_form: str = Field(min_length=1)
    level_distance: int | None = Field(default=None, ge=0)
    """None は CEFR 不明。自動では排除しない。"""
    source_recency_days: float | None = None
    """負の値は評価時刻より新しい Source。優先度では 0 日として扱う。"""
    primary_source_id: str | None = Field(default=None, min_length=1)
    """cap の単位。Source が無い Item は他 Item と枠を共有しない。"""
    interest_weight: float = Field(default=NEUTRAL_INTEREST_WEIGHT, ge=0)
    importance_weight: float = Field(default=NEUTRAL_IMPORTANCE_WEIGHT, ge=0)


class AdmissionDecision(BaseModel):
    """1 Item の admit / defer。defer の reason は 1 つ。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    learning_item_id: str = Field(min_length=1)
    outcome: AdmissionOutcome
    reason_codes: tuple[AdmissionReasonCode, ...] = ()


class AdmissionResult(BaseModel):
    """同じ backlog・同じ now から毎回同じ選別結果。永続化しない。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    generated_at: datetime
    policy_version: str = POLICY_VERSION
    admission_budget: int = Field(ge=0)
    due_review_count: int = Field(ge=0)
    recent_introduced_count: int = Field(ge=0)
    unseen_count: int = Field(ge=0)
    admitted_ids: tuple[str, ...] = ()
    """選ばれた順。Daily Plan の ranking 順とは別。"""
    decisions: tuple[AdmissionDecision, ...] = ()
    """learning_item_id 昇順。"""

    @model_validator(mode="after")
    def _check_invariants(self) -> AdmissionResult:
        if len(self.admitted_ids) > self.admission_budget:
            raise ValueError("admitted 件数は admission_budget を超えない")
        if len(self.decisions) != self.unseen_count:
            raise ValueError("decisions は unseen backlog の全件を含む")
        admitted = [row for row in self.decisions if row.outcome == "admit"]
        deferred = [row for row in self.decisions if row.outcome == "defer"]
        if {row.learning_item_id for row in admitted} != set(self.admitted_ids):
            raise ValueError("admitted_ids と admit decision が一致しない")
        if len(admitted) != len(self.admitted_ids):
            raise ValueError("admitted_ids に重複がある")
        if any(row.reason_codes for row in admitted):
            raise ValueError("admit に defer 理由は付けない")
        if any(len(row.reason_codes) != 1 for row in deferred):
            raise ValueError("defer 理由は 1 つ")
        ids = [row.learning_item_id for row in self.decisions]
        if ids != sorted(ids):
            raise ValueError("decisions は learning_item_id 昇順")
        return self


class InvalidAdmissionInputError(ValueError):
    """due 件数や Item id など、admission 入力が不正。"""


# ---------------------------------------------------------------------------
# backlog の組み立て
# ---------------------------------------------------------------------------


def normalize_canonical_form(canonical_form: str) -> str:
    """同一表記ゆれを 1 キーに寄せる。意味の違う語の統合はしない。

    大小文字、アポストロフィの字形、空白、ハイフンを畳む。
    アクセントは残す（où と ou は別の語になり得る）。
    """
    text = unicodedata.normalize("NFKC", canonical_form).casefold()
    text = text.translate(_APOSTROPHE_TRANSLATION)
    text = re.sub(r"[\s\-_]+", " ", text).strip()
    text = text.strip(".,;:!?\"'«»()[]")
    text = re.sub(r"\s+", " ", text).strip()
    return text or unicodedata.normalize("NFKC", canonical_form).casefold()


def select_primary_source_id(
    item: LearningItem,
    sources_by_id: Mapping[str, SourceDocument],
) -> str | None:
    """per-source cap の単位。最も新しい Source。同時刻は id 昇順。"""
    best_at: datetime | None = None
    best_id: str | None = None
    for ref in item.source_refs:
        source = sources_by_id.get(ref.source_document_id)
        if source is None:
            continue
        created = _require_aware_utc(source.created_at)
        if (
            best_at is None
            or created > best_at
            or (created == best_at and best_id is not None and source.id < best_id)
        ):
            best_at = created
            best_id = source.id
    if best_id is not None:
        return best_id
    if not item.source_refs:
        return None
    return min(ref.source_document_id for ref in item.source_refs)


def build_unseen_backlog_item(
    item: LearningItem,
    snapshot: RecommendationSignalSnapshot,
    *,
    sources_by_id: Mapping[str, SourceDocument] | None = None,
) -> UnseenBacklogItem | None:
    """新規学習の在庫に入る active Item だけを返す。

    いずれかの direction が Phase 5 の new_practice（unseen かつ not due）
    なら在庫に入れる。due だけの Item は入れない。inactive も入れない。
    """
    if item.id != snapshot.learning_item_id:
        raise InvalidAdmissionInputError(
            "LearningItem と snapshot の id が一致しない: "
            f"item={item.id}, snapshot={snapshot.learning_item_id}"
        )
    if item.status != "active":
        return None
    if not any(
        infer_activity_kind(signal) == "new_practice"
        for signal in snapshot.by_direction.values()
    ):
        return None
    return UnseenBacklogItem(
        learning_item_id=item.id,
        canonical_form=item.canonical_form,
        level_distance=snapshot.level_distance,
        source_recency_days=snapshot.source_recency_days,
        primary_source_id=select_primary_source_id(item, sources_by_id or {}),
        interest_weight=snapshot.interest_weight,
        importance_weight=snapshot.importance_weight,
    )


def count_due_review_units(
    snapshots: Sequence[RecommendationSignalSnapshot],
) -> int:
    """due の direction 件数。Item 件数ではなく復習負債の単位。"""
    total = 0
    for snapshot in snapshots:
        for signal in snapshot.by_direction.values():
            if infer_activity_kind(signal) == "review":
                total += 1
    return total


def count_recent_introductions(
    first_learned_at_by_item_id: Mapping[str, datetime],
    *,
    now: datetime,
) -> int:
    """窓内に最初の学習がある Item 件数。未学習の在庫は数えない。"""
    aware_now = _require_aware_utc(now)
    window_start = aware_now - timedelta(days=RECENT_INTRODUCTION_WINDOW_DAYS)
    count = 0
    for learned_at in first_learned_at_by_item_id.values():
        aware = _require_aware_utc(learned_at)
        if window_start <= aware <= aware_now:
            count += 1
    return count


# ---------------------------------------------------------------------------
# budget
# ---------------------------------------------------------------------------


def compute_admission_budget(
    *,
    due_review_count: int,
    recent_introduced_count: int,
) -> int:
    """今いま eligible にしてよい新規件数。"""
    _require_non_negative("due_review_count", due_review_count)
    _require_non_negative("recent_introduced_count", recent_introduced_count)
    remaining = max(0, DAILY_INTRODUCTION_QUOTA - recent_introduced_count)
    return min(_due_cap(due_review_count), remaining)


def _due_cap(due_review_count: int) -> int:
    if due_review_count >= DUE_BACKLOG_HARD_THRESHOLD:
        return SUPPRESSED_NEW_ADMISSION_CAP
    if due_review_count >= DUE_BACKLOG_SOFT_THRESHOLD:
        return REDUCED_NEW_ADMISSION_CAP
    return NORMAL_NEW_ADMISSION_CAP


# ---------------------------------------------------------------------------
# 選別
# ---------------------------------------------------------------------------


def decide_new_admissions(
    items: Sequence[UnseenBacklogItem],
    *,
    due_review_count: int,
    recent_introduced_count: int,
    now: datetime,
) -> AdmissionResult:
    """未学習在庫から new-learning eligible を deterministic に選ぶ。

    優先度は level fit、Source の新しさ、importance、interest の順。
    最後の tie-break は learning_item_id 昇順。
    同一 Source は round-robin で cap までしか取らない。
    CEFR 不明は LEVEL_TOO_FAR にしない。
    """
    aware_now = _require_aware_utc(now)
    _require_non_negative("due_review_count", due_review_count)
    _require_non_negative("recent_introduced_count", recent_introduced_count)
    _require_unique_ids(items)

    budget = compute_admission_budget(
        due_review_count=due_review_count,
        recent_introduced_count=recent_introduced_count,
    )
    due_cap = _due_cap(due_review_count)
    introduction_remaining = max(0, DAILY_INTRODUCTION_QUOTA - recent_introduced_count)
    budget_without_due_pressure = min(NORMAL_NEW_ADMISSION_CAP, introduction_remaining)

    duplicate_losers, representatives = _split_duplicates(items)
    level_far, pool = _split_level(representatives)
    selected = _select(pool, budget)
    selected_without_due = _select(pool, budget_without_due_pressure)
    selected_ids = {row.learning_item_id for row in selected}
    selected_without_due_ids = {row.learning_item_id for row in selected_without_due}
    duplicate_ids = {row.learning_item_id for row in duplicate_losers}
    level_far_ids = {row.learning_item_id for row in level_far}
    due_is_tighter = due_cap < budget_without_due_pressure

    decisions: list[AdmissionDecision] = []
    for item in sorted(items, key=lambda row: row.learning_item_id):
        if item.learning_item_id in duplicate_ids:
            decisions.append(_defer(item, "DUPLICATE_OR_REDUNDANT"))
        elif item.learning_item_id in level_far_ids:
            decisions.append(_defer(item, "LEVEL_TOO_FAR_FOR_NOW"))
        elif item.learning_item_id in selected_ids:
            decisions.append(
                AdmissionDecision(
                    learning_item_id=item.learning_item_id,
                    outcome="admit",
                )
            )
        elif _source_cap_blocks(item, pool):
            decisions.append(_defer(item, "SOURCE_DAILY_CAP"))
        elif due_is_tighter and item.learning_item_id in selected_without_due_ids:
            decisions.append(_defer(item, "REVIEW_BACKLOG_HIGH"))
        else:
            decisions.append(_defer(item, "HIGHER_PRIORITY_NEW_EXISTS"))

    return AdmissionResult(
        generated_at=aware_now,
        policy_version=POLICY_VERSION,
        admission_budget=budget,
        due_review_count=due_review_count,
        recent_introduced_count=recent_introduced_count,
        unseen_count=len(items),
        admitted_ids=tuple(row.learning_item_id for row in selected),
        decisions=tuple(decisions),
    )


def filter_ranked_new_practice(
    ranked: Sequence[RankedRecommendation],
    admission: AdmissionResult,
) -> tuple[RankedRecommendation, ...]:
    """ranking 順を保ったまま、defer された new_practice だけを外す。

    review は admission の対象外なので残す。Phase 5 の score は再計算しない。
    """
    admitted = set(admission.admitted_ids)
    return tuple(
        row
        for row in ranked
        if row.activity_kind != "new_practice" or row.learning_item_id in admitted
    )


def _defer(item: UnseenBacklogItem, reason: AdmissionReasonCode) -> AdmissionDecision:
    return AdmissionDecision(
        learning_item_id=item.learning_item_id,
        outcome="defer",
        reason_codes=(reason,),
    )


def _split_duplicates(
    items: Sequence[UnseenBacklogItem],
) -> tuple[list[UnseenBacklogItem], list[UnseenBacklogItem]]:
    groups: dict[str, list[UnseenBacklogItem]] = {}
    for item in items:
        groups.setdefault(normalize_canonical_form(item.canonical_form), []).append(
            item
        )
    losers: list[UnseenBacklogItem] = []
    representatives: list[UnseenBacklogItem] = []
    for group in groups.values():
        ordered = sorted(group, key=_priority_sort_key)
        representatives.append(ordered[0])
        losers.extend(ordered[1:])
    return losers, representatives


def _split_level(
    items: Sequence[UnseenBacklogItem],
) -> tuple[list[UnseenBacklogItem], list[UnseenBacklogItem]]:
    far: list[UnseenBacklogItem] = []
    pool: list[UnseenBacklogItem] = []
    for item in items:
        if (
            item.level_distance is not None
            and item.level_distance >= LEVEL_DISTANCE_DEFER_THRESHOLD
        ):
            far.append(item)
        else:
            pool.append(item)
    return far, pool


def _select(pool: Sequence[UnseenBacklogItem], budget: int) -> list[UnseenBacklogItem]:
    """Source を跨いで round-robin し、同一 Source は cap まで。"""
    if budget <= 0 or not pool:
        return []
    ordered = sorted(pool, key=_priority_sort_key)
    groups: dict[tuple[str, str], list[UnseenBacklogItem]] = {}
    group_order: list[tuple[str, str]] = []
    for item in ordered:
        key = _source_group(item)
        if key not in groups:
            groups[key] = []
            group_order.append(key)
        groups[key].append(item)

    cursors = dict.fromkeys(group_order, 0)
    selected: list[UnseenBacklogItem] = []
    while len(selected) < budget:
        progressed = False
        for key in group_order:
            if len(selected) >= budget:
                break
            bucket = groups[key]
            index = cursors[key]
            if index >= len(bucket):
                continue
            if key[0] == "source" and index >= PER_SOURCE_ADMISSION_CAP:
                continue
            selected.append(bucket[index])
            cursors[key] = index + 1
            progressed = True
        if not progressed:
            break
    return selected


def _source_group(item: UnseenBacklogItem) -> tuple[str, str]:
    if item.primary_source_id is None:
        return ("item", item.learning_item_id)
    return ("source", item.primary_source_id)


def _source_cap_blocks(
    item: UnseenBacklogItem, pool: Sequence[UnseenBacklogItem]
) -> bool:
    if item.primary_source_id is None:
        return False
    same = [row for row in pool if row.primary_source_id == item.primary_source_id]
    ordered = sorted(same, key=_priority_sort_key)
    index = next(
        position
        for position, row in enumerate(ordered)
        if row.learning_item_id == item.learning_item_id
    )
    return index >= PER_SOURCE_ADMISSION_CAP


def _priority_sort_key(
    item: UnseenBacklogItem,
) -> tuple[float, float, float, float, str]:
    """小さいほど先。level、新しさ、importance、interest、id。"""
    return (
        -round(_level_priority(item.level_distance), PRIORITY_DECIMALS),
        -round(_recency_priority(item.source_recency_days), PRIORITY_DECIMALS),
        -round(_weight_priority(item.importance_weight), PRIORITY_DECIMALS),
        -round(_weight_priority(item.interest_weight), PRIORITY_DECIMALS),
        item.learning_item_id,
    )


def _level_priority(level_distance: int | None) -> float:
    if level_distance is None:
        return UNKNOWN_LEVEL_PRIORITY
    if MAX_LEVEL_DISTANCE <= 0:
        return 1.0
    return max(0.0, 1.0 - level_distance / MAX_LEVEL_DISTANCE)


def _recency_priority(source_recency_days: float | None) -> float:
    if source_recency_days is None:
        return 0.0
    days = max(0.0, source_recency_days)
    return max(0.0, 1.0 - days / RECENCY_SATURATION_DAYS)


def _weight_priority(weight: float) -> float:
    return max(0.0, weight - NEUTRAL_IMPORTANCE_WEIGHT)


def _require_unique_ids(items: Sequence[UnseenBacklogItem]) -> None:
    seen: set[str] = set()
    for item in items:
        if item.learning_item_id in seen:
            raise InvalidAdmissionInputError(
                f"learning_item_id が重複している: {item.learning_item_id}"
            )
        seen.add(item.learning_item_id)


def _require_non_negative(name: str, value: int) -> None:
    if value < 0:
        raise InvalidAdmissionInputError(f"{name} は 0 以上: {value}")


def _require_aware_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise InvalidAdmissionInputError("timezone-aware な datetime が必要")
    return dt.astimezone(UTC)


__all__ = [
    "DAILY_INTRODUCTION_QUOTA",
    "DUE_BACKLOG_HARD_THRESHOLD",
    "DUE_BACKLOG_SOFT_THRESHOLD",
    "LEVEL_DISTANCE_DEFER_THRESHOLD",
    "NORMAL_NEW_ADMISSION_CAP",
    "PER_SOURCE_ADMISSION_CAP",
    "POLICY_VERSION",
    "RECENT_INTRODUCTION_WINDOW_DAYS",
    "REDUCED_NEW_ADMISSION_CAP",
    "SUPPRESSED_NEW_ADMISSION_CAP",
    "AdmissionDecision",
    "AdmissionOutcome",
    "AdmissionReasonCode",
    "AdmissionResult",
    "InvalidAdmissionInputError",
    "UnseenBacklogItem",
    "build_unseen_backlog_item",
    "compute_admission_budget",
    "count_due_review_units",
    "count_recent_introductions",
    "decide_new_admissions",
    "filter_ranked_new_practice",
    "normalize_canonical_form",
    "select_primary_source_id",
]
