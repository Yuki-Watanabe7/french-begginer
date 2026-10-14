"""複数 SourceRef から再提示する文脈を選ぶ context rotation（Issue #202）。

同じ LearningItem を、毎回同じ例文だけで出さない。有効な出典が複数あるとき、
直近の同じ Exercise で使った文脈を避け、まだ使っていない文脈、なければ
最も昔に使った文脈を選ぶ。履歴が空なら従来の oldest-source と同じ順になる。

選択は deterministic である。random も embeddings も使わない。
候補は呼び出し側が渡した SourceRef だけであり、別 Item の同義表現は混ぜない。

このモジュールが依存してよいのは Python 標準ライブラリ、Pydantic、
``domain.tutor`` のみ。DB / FastAPI / OpenAI には依存しない。
wall clock は呼ばない。時刻は LearningEvent の ``occurred_at`` を使う。

```text
LearningItem の有効 SourceRef
  -> 同じ ExerciseType の直近 context を避ける
  -> ContextSelection（selected_source_ref / reason / policy_version）
```
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.tutor import ExerciseType, LearningEvent, SourceRef

POLICY_VERSION = "context-rotation-v1"
"""context 選択規則の版。順位を変えるときは bump する。"""

ContextSelectionReason = (
    "single_valid_context",
    "unused_context",
    "least_recent_context",
)

_EARLIEST = datetime.min.replace(tzinfo=UTC)


class ContextUsage(BaseModel):
    """1回の出題で使った出典文脈。LearningEvent から復元する。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    exercise_type: ExerciseType
    source_document_id: str = Field(min_length=1)
    evidence_start: int | None = Field(default=None, ge=0)
    evidence_end: int | None = Field(default=None, ge=0)
    exercise_version: str | None = None
    occurred_at: datetime
    event_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def _check_bounds(self) -> ContextUsage:
        _require_aware_utc(self.occurred_at)
        start = self.evidence_start
        end = self.evidence_end
        if (start is None) != (end is None):
            raise ValueError("evidence の start と end は両方指定するか、両方空にする")
        if start is not None and end is not None and end <= start:
            raise ValueError(
                "evidence の end は start より大きい必要がある: "
                f"start={start}, end={end}"
            )
        return self


class ContextCandidate(BaseModel):
    """選択対象の有効な SourceRef。品質判定は呼び出し側が済ませている。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_ref: SourceRef
    source_created_at: datetime

    @model_validator(mode="after")
    def _check_candidate(self) -> ContextCandidate:
        if self.source_ref.evidence_span is None:
            raise ValueError("context candidate には evidence_span が必要")
        _require_aware_utc(self.source_created_at)
        return self


class ContextSelection(BaseModel):
    """選んだ文脈と、その理由。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    learning_item_id: str = Field(min_length=1)
    selected_source_ref: SourceRef
    reason: str = Field(min_length=1)
    policy_version: str = Field(default=POLICY_VERSION, min_length=1)

    @model_validator(mode="after")
    def _check_reason(self) -> ContextSelection:
        if self.reason not in ContextSelectionReason:
            raise ValueError(f"未知の context selection reason: {self.reason}")
        if self.selected_source_ref.evidence_span is None:
            raise ValueError("選択した SourceRef には evidence_span が必要")
        return self


def source_evidence_id(source_document_id: str, start: int, end: int) -> str:
    """Source 上の根拠位置を一意に指す識別子。"""

    if not source_document_id.strip():
        raise ValueError("source_document_id が必要")
    if end <= start or start < 0:
        raise ValueError(f"evidence 範囲が不正: start={start}, end={end}")
    return f"{source_document_id}:{start}:{end}"


def usages_for_exercise(
    usages: Sequence[ContextUsage], exercise_type: ExerciseType
) -> tuple[ContextUsage, ...]:
    """同じ ExerciseType の利用だけを返す。別形式の履歴では出題をずらさない。"""

    return tuple(usage for usage in usages if usage.exercise_type == exercise_type)


def context_usages_from_events(
    events: Sequence[LearningEvent],
) -> tuple[ContextUsage, ...]:
    """LearningEvent から、判断に使える文脈履歴を復元する。

    ``source_document_id`` が無い Event は文脈を使っていないので無視する。
    span が無い既存 Event は、その Source 全体を使ったものとして扱う。
    入力順には依存せず、``occurred_at`` と event id で並べる。
    """

    usages: list[ContextUsage] = []
    for event in events:
        usage = _usage_from_event(event)
        if usage is not None:
            usages.append(usage)
    usages.sort(key=lambda row: (row.occurred_at, row.event_id))
    return tuple(usages)


def select_context(
    *,
    learning_item_id: str,
    candidates: Sequence[ContextCandidate],
    usages: Sequence[ContextUsage] = (),
) -> ContextSelection | None:
    """有効候補から文脈を1件選ぶ。候補が無ければ None。

    順位（先にあるものほど優先）:
      1. この履歴に一度も出ていない文脈
      2. 使ったことがあるなら、最後に使った時刻が古いもの
      3. Source の作成時刻、source id、evidence の start / end
    候補が1件だけのときは、直近でもその文脈を使う。
    """

    if not learning_item_id.strip():
        raise ValueError("learning_item_id が必要")
    if not candidates:
        return None
    ordered = sorted(candidates, key=lambda row: _rank(row, usages))
    chosen = ordered[0]
    if len(candidates) == 1:
        reason = "single_valid_context"
    elif _latest_usage(chosen, usages) is None:
        reason = "unused_context"
    else:
        reason = "least_recent_context"
    return ContextSelection(
        learning_item_id=learning_item_id,
        selected_source_ref=chosen.source_ref,
        reason=reason,
        policy_version=POLICY_VERSION,
    )


def _rank(
    candidate: ContextCandidate, usages: Sequence[ContextUsage]
) -> tuple[int, datetime, str, datetime, str, int, int]:
    span = candidate.source_ref.evidence_span
    assert span is not None
    stable = (
        candidate.source_created_at,
        candidate.source_ref.source_document_id,
        span.start,
        span.end,
    )
    last = _latest_usage(candidate, usages)
    if last is None:
        return (0, _EARLIEST, "", *stable)
    return (1, last.occurred_at, last.event_id, *stable)


def _latest_usage(
    candidate: ContextCandidate, usages: Sequence[ContextUsage]
) -> ContextUsage | None:
    matched = [usage for usage in usages if _matches(usage, candidate)]
    if not matched:
        return None
    return max(matched, key=lambda usage: (usage.occurred_at, usage.event_id))


def _matches(usage: ContextUsage, candidate: ContextCandidate) -> bool:
    ref = candidate.source_ref
    span = ref.evidence_span
    assert span is not None
    if usage.source_document_id != ref.source_document_id:
        return False
    if usage.evidence_start is None or usage.evidence_end is None:
        return True
    return usage.evidence_start == span.start and usage.evidence_end == span.end


def _usage_from_event(event: LearningEvent) -> ContextUsage | None:
    metadata = event.metadata
    source_id = metadata.get("source_document_id")
    if not isinstance(source_id, str) or not source_id.strip():
        return None
    source_id = source_id.strip()
    start, end = _evidence_bounds(metadata, source_id)
    version = metadata.get("exercise_version")
    exercise_version = version if isinstance(version, str) and version.strip() else None
    return ContextUsage(
        exercise_type=event.exercise_type,
        source_document_id=source_id,
        evidence_start=start,
        evidence_end=end,
        exercise_version=exercise_version.strip() if exercise_version else None,
        occurred_at=event.occurred_at,
        event_id=event.id,
    )


def _evidence_bounds(
    metadata: Mapping[str, Any], source_id: str
) -> tuple[int | None, int | None]:
    start = _strict_int(metadata.get("evidence_start"))
    end = _strict_int(metadata.get("evidence_end"))
    if start is not None and end is not None and end > start:
        return start, end
    parsed = _parse_evidence_id(metadata.get("source_evidence_id"))
    if parsed is None or parsed[0] != source_id:
        return None, None
    return parsed[1], parsed[2]


def _parse_evidence_id(value: object) -> tuple[str, int, int] | None:
    if not isinstance(value, str) or value.count(":") < 2:
        return None
    source_id, start_text, end_text = value.rsplit(":", 2)
    if not source_id:
        return None
    try:
        start = int(start_text)
        end = int(end_text)
    except ValueError:
        return None
    if start < 0 or end <= start:
        return None
    return source_id, start, end


def _strict_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _require_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError("timezone-aware な datetime が必要")
    return value.astimezone(UTC)
