"""
Tutor機能の中核ドメインモデル（Phase 0）。

責務: ユーザーが触れたフランス語ソースを教材化し、学習履歴・習熟状態・
復習予定を追跡するための「型と不変条件」だけを定義する。

このモジュールが依存してよいのは Python 標準ライブラリと Pydantic のみ。
DB / FastAPI / OpenAI API には依存しない（domain層の原則）。

モデルの責務分離:
  - SourceDocument: ユーザーが触れた素材そのもの（原文）
  - LearningItem:   素材から抽出・正規化した「学習対象」
  - LearningEvent:  学習者の行動の記録。append-only（frozen）
  - LearnerState:   LearningEventを集約した「現在の習熟状態」
  - ReviewSchedule: 次にいつ復習するか

詳細な設計意図は docs/tutor_architecture.md を参照。

Phase 0のスコープ外（後続Issueで追加する）:
  - 永続化 / repository
  - LLMによる学習項目抽出
  - LearnerState更新ロジック・SRSアルゴリズム
  - API / UI
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

# ---------------------------------------------------------------------------
# 共通の型・ユーティリティ
# ---------------------------------------------------------------------------

# 時刻はすべてtimezone-awareで扱い、内部表現はUTCへ正規化する。
# naiveなdatetimeはAwareDatetimeがValidationErrorとして弾く。
UtcDatetime = Annotated[AwareDatetime, AfterValidator(lambda dt: dt.astimezone(UTC))]


def utcnow() -> datetime:
    """現在時刻をtimezone-aware（UTC）で返す。"""
    return datetime.now(UTC)


def new_id() -> str:
    """ドメイン内でIDを採番する。

    永続化実装（採番方法）と疎結合にするため、domain層でUUID4文字列を生成する。
    DB導入後もこのIDをそのまま主キーとして利用できる。
    """
    return str(uuid.uuid4())


SourceType = Literal["manual_text"]
"""Sourceの入力形式。Phase 1は手入力テキストのみ。URL/PDF等はPhase 6で追加する。"""

LearningItemType = Literal["vocabulary", "expression", "grammar", "conjugation"]

LearningItemStatus = Literal["active", "suspended", "mastered"]
"""active=学習対象 / suspended=一時停止（ユーザーが除外） / mastered=定着済み"""

CefrLevel = Literal["A1", "A2", "B1", "B2", "C1", "C2"]

LearningEventType = Literal["review"]
"""Phase 0では復習イベントのみ。将来 introduce / suspend 等を追加しうる。"""

ExerciseType = Literal[
    "meaning_recognition",
    "fr_to_ja",
    "ja_to_fr",
    "cloze",
    "verb_conjugation",
    "noun_gender",
    "noun_article",
]
"""出題形式。既存の動詞・名詞クイズもLearningEventとして記録できるようにしてある。"""

AnswerOutcome = Literal["correct", "incorrect"]

SkillDirection = Literal["recognition", "production"]
"""「見て分かる」と「自力で produce できる」を将来分離するための軸。"""


# ---------------------------------------------------------------------------
# SourceDocument — ユーザーが触れたフランス語ソース
# ---------------------------------------------------------------------------


class SourceDocument(BaseModel):
    """学習の元になった素材（原文）。

    LearningItemとは意図的に分離する。同じ表現が複数のSourceに現れても
    LearningItemは1件に正規化され、SourceDocumentは出典として残る。
    """

    id: str = Field(default_factory=new_id)
    source_type: SourceType = "manual_text"
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    language: str = "fr"
    created_at: UtcDatetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# LearningItem — 正規化された学習対象
# ---------------------------------------------------------------------------


class EvidenceSpan(BaseModel):
    """LearningItemの根拠となったSource中の位置。

    Phase 0では利用しないが、Phase 2のLLM抽出で「原文のどこから採ったか」を
    保持できるよう拡張余地として定義しておく。
    """

    start: int = Field(ge=0)
    end: int = Field(ge=0)
    text: str | None = None

    @model_validator(mode="after")
    def _check_range(self) -> "EvidenceSpan":
        if self.end <= self.start:
            raise ValueError(
                f"evidence spanのendはstartより大きい必要がある: "
                f"start={self.start}, end={self.end}"
            )
        return self


class SourceRef(BaseModel):
    """LearningItemがどのSourceに由来するかの参照。

    evidence_span / confidence はPhase 2（LLM抽出）用の拡張点であり、
    Phase 0ではNoneのままでよい。
    """

    source_document_id: str = Field(min_length=1)
    evidence_span: EvidenceSpan | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class LearningItem(BaseModel):
    """学習対象の正規化単位。

    SourceDocumentと統合しない。Sourceは「触れた素材」、LearningItemは
    「覚える対象」であり、ライフサイクルも粒度も異なる。
    """

    id: str = Field(default_factory=new_id)
    item_type: LearningItemType
    canonical_form: str = Field(min_length=1)
    meaning_ja: str = Field(min_length=1)
    explanation_ja: str | None = None
    level: CefrLevel | None = None
    source_refs: list[SourceRef] = Field(default_factory=list)
    created_at: UtcDatetime = Field(default_factory=utcnow)
    status: LearningItemStatus = "active"
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# LearningEvent — 学習行動の履歴（append-only）
# ---------------------------------------------------------------------------


class LearningEvent(BaseModel):
    """学習者がLearningItemに対して行った行動の記録。

    履歴は事実であり後から書き換えない。その性質を型で示すため frozen とする。
    訂正が必要な場合は新しいイベントを追記する。
    """

    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=new_id)
    learning_item_id: str = Field(min_length=1)
    event_type: LearningEventType = "review"
    exercise_type: ExerciseType
    result: AnswerOutcome
    occurred_at: UtcDatetime = Field(default_factory=utcnow)
    response_time_ms: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# LearnerState — LearningItemごとの現在の習熟状態
# ---------------------------------------------------------------------------


class MasteryStats(BaseModel):
    """習熟度の集計値。

    LearnerState全体と、将来のrecognition / production別集計の
    双方で同じ形を使えるよう独立したモデルにしてある。
    """

    attempt_count: int = Field(default=0, ge=0)
    correct_count: int = Field(default=0, ge=0)
    incorrect_count: int = Field(default=0, ge=0)
    consecutive_correct: int = Field(default=0, ge=0)
    last_reviewed_at: UtcDatetime | None = None
    mastery_score: float = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _check_counts(self) -> "MasteryStats":
        if self.attempt_count != self.correct_count + self.incorrect_count:
            raise ValueError(
                f"attempt_countはcorrect_count + incorrect_countと一致する必要がある: "
                f"attempt={self.attempt_count}, correct={self.correct_count}, "
                f"incorrect={self.incorrect_count}"
            )
        if self.consecutive_correct > self.correct_count:
            raise ValueError(
                f"consecutive_correctはcorrect_countを超えられない: "
                f"consecutive={self.consecutive_correct}, correct={self.correct_count}"
            )
        if self.attempt_count == 0 and self.last_reviewed_at is not None:
            raise ValueError(
                "未学習（attempt_count=0）でlast_reviewed_atは設定できない"
            )
        if self.attempt_count > 0 and self.last_reviewed_at is None:
            raise ValueError("学習済み（attempt_count>0）ならlast_reviewed_atが必要")
        return self


class LearnerState(MasteryStats):
    """LearningItemごとの現在の習熟状態。

    LearningEventの集約結果であり、履歴そのものではない。
    「今この項目をどれだけ習得しているか」の問い合わせを、
    全イベントの再走査なしに答えられるようにするために分離している。

    by_direction はrecognition / productionを分離するための拡張点。
    Phase 0では空のままでよく、集計ロジックは後続Issueで実装する。
    """

    learning_item_id: str = Field(min_length=1)
    by_direction: dict[SkillDirection, MasteryStats] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# ReviewSchedule — 次回復習予定
# ---------------------------------------------------------------------------


class ReviewSchedule(BaseModel):
    """LearningItemの次回復習予定。

    scheduler_version を持たせることで、将来アルゴリズム（SM-2 / FSRS等）を
    差し替え・比較したときに、どの版が算出した予定かを追跡できる。
    """

    learning_item_id: str = Field(min_length=1)
    due_at: UtcDatetime
    interval_days: float = Field(ge=0.0)
    review_count: int = Field(default=0, ge=0)
    lapse_count: int = Field(default=0, ge=0)
    scheduler_version: str = Field(default="v0", min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
