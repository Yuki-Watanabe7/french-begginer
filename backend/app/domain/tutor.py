"""
Tutor機能の中核ドメインモデル（Phase 0 / Phase 2 Candidate / Phase 3 Exercise）。

責務: ユーザーが触れたフランス語ソースを教材化し、学習履歴・習熟状態・
復習予定を追跡するための型・不変条件・LearnerState更新を定義する。

このモジュールが依存してよいのは Python 標準ライブラリと Pydantic のみ。
DB / FastAPI / OpenAI API には依存しない（domain層の原則）。

モデルの責務分離:
  - SourceDocument: ユーザーが触れた素材そのもの（原文）
  - LearningItemCandidate: LLMが提案した学習候補。確定前の中間表現
  - LearningItem:   素材から抽出・正規化した「学習対象」
  - LearningEvent:  学習者の行動の記録。append-only（frozen）
  - LearnerState:   LearningEventを集約した「現在の習熟状態」
  - ReviewSchedule: 次にいつ復習するか

詳細な設計意図は docs/tutor_architecture.md を参照。

永続化は `app/repositories` / `app/persistence` が担う。
このモジュールは永続化実装に依存しない。

LearnerState の更新は `apply_review_event` が担う（Issue #110 / #161）。
復習予定の算出は `review_scheduler.schedule_next_review` が担う（Issue #111）。
Candidate の状態遷移は `apply_candidate_status` が担う（Issue #131）。
LLM 抽出は `services/extraction_service` が担う（Issue #132）。
Candidate の evidence 検証・正規化・重複統合は
`candidate_normalization` が担う（Issue #133）。
抽出結果の保存と採否 API は `services/candidate_service` が担う（Issue #134）。
LearningItem → Exercise の契約・適用条件は `exercise` が担う（Issue #145）。
vocabulary / expression の deterministic 生成は `exercise_generation` が担う
（Issue #146）。Source evidence からの cloze 生成も同モジュール（Issue #147）。
conjugation の既存動詞クイズ adapter は `conjugation_adapter` が担う（Issue #148）。
Exercise の server-side 採点と LearningEvent 記録は `exercise_evaluation` /
`exercise_service` が担う（Issue #149）。
Practice Session の組み立ては `practice_session` が担う（Issue #150）。
recognition / production 別の LearnerState 集計は `apply_review_event` が担う
（Issue #161）。ReviewSchedule の direction 分離は `review_scheduler` が担う
（Issue #162）。direction-aware な due review queue は `review_queue` が担う
（Issue #163）。due queue からの Review Practice Session は `review_session`
が担う（Issue #164）。due queue UI / Frontend mastery 表示は後続Issue。
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

CandidateStatus = Literal["candidate", "accepted", "rejected"]
"""candidate=未判定 / accepted=学習項目として採用 / rejected=却下。

accepted / rejected は終端状態。無制限な再遷移は許可しない。
"""

CefrLevel = Literal["A1", "A2", "B1", "B2", "C1", "C2"]

LearningEventType = Literal["review"]
"""Phase 0では復習イベントのみ。将来 introduce / suspend 等を追加しうる。"""

ExerciseType = Literal[
    "meaning_recognition",
    "fr_to_ja",
    "ja_to_fr",
    "cloze",
    "expression_reconstruction",
    "verb_conjugation",
    "noun_gender",
    "noun_article",
]
"""出題形式。既存の動詞・名詞クイズもLearningEventとして記録できるようにしてある。

`expression_reconstruction` は表現を部品から組み直す形式。cloze（穴埋め）とは
別型にする。SkillDirection と LearningItemType ごとの適用可否は
`domain.exercise` の policy が一元管理する（Issue #145）。
"""

AnswerOutcome = Literal["correct", "incorrect"]

SkillDirection = Literal["recognition", "production"]
"""「見て分かる」と「自力で produce できる」を分離する軸。"""

SKILL_DIRECTION_BY_EXERCISE_TYPE: dict[ExerciseType, SkillDirection] = {
    "meaning_recognition": "recognition",
    "fr_to_ja": "recognition",
    "ja_to_fr": "production",
    "cloze": "production",
    "expression_reconstruction": "production",
    "verb_conjugation": "production",
    "noun_gender": "recognition",
    "noun_article": "production",
}
"""ExerciseType → SkillDirection。LearnerState 集計の source of truth。

Client 由来の `LearningEvent.metadata.skill_direction` は使わない。
Issue #145 の policy と同じ対応をここに置き、domain が exercise 層へ
依存しないようにする。
"""


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
    """LearningItem / Candidate の根拠となった Source 中の位置。

    原文断片 `text` は冗長保持しなくてよい。`start` / `end` があれば
    Source 本文から `read_source_evidence` で再構成でき、後続 service が
    範囲内かどうかを検証できる。
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
# LearningItemCandidate — LLM抽出の未確定候補
# ---------------------------------------------------------------------------


class LearningItemCandidate(BaseModel):
    """LLM が提案した学習候補。正しい学習項目として確定したデータではない。

    LearningItem と同一モデルにしない。Candidate は validation / 正規化 /
    ユーザー確認の前の中間表現であり、採用後に LearningItem へ昇格する。

    evidence_span は Source 本文上のオフセットだけを持ち、原文断片の冗長
    保持は必須にしない。本文からの再構成は `read_source_evidence` を使う。
    """

    id: str = Field(default_factory=new_id)
    source_document_id: str = Field(min_length=1)
    item_type: LearningItemType
    canonical_form: str = Field(min_length=1)
    meaning_ja: str = Field(min_length=1)
    explanation_ja: str | None = None
    level: CefrLevel | None = None
    evidence_span: EvidenceSpan
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    status: CandidateStatus = "candidate"
    extraction_version: str = Field(min_length=1)
    created_at: UtcDatetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


_ALLOWED_CANDIDATE_STATUS_TRANSITIONS: dict[
    CandidateStatus, frozenset[CandidateStatus]
] = {
    "candidate": frozenset({"accepted", "rejected"}),
    "accepted": frozenset(),
    "rejected": frozenset(),
}


def apply_candidate_status(
    candidate: LearningItemCandidate, new_status: CandidateStatus
) -> LearningItemCandidate:
    """Candidate の status を遷移した新しいインスタンスを返す。

    現在の candidate は変更しない。同一 status への更新は冪等。
    accepted / rejected からの遷移は許可しない。
    """
    if candidate.status == new_status:
        return candidate
    allowed = _ALLOWED_CANDIDATE_STATUS_TRANSITIONS[candidate.status]
    if new_status not in allowed:
        raise ValueError(
            f"LearningItemCandidate の status を {candidate.status} から "
            f"{new_status} へは変更できない"
        )
    return candidate.model_copy(update={"status": new_status})


def read_source_evidence(content: str, span: EvidenceSpan) -> str:
    """Source 本文から evidence_span の範囲を切り出す。

    範囲が本文に収まらない場合は ValueError。後続 service が
    Candidate の根拠位置を検証・再構成するために使う。
    """
    if span.end > len(content):
        raise ValueError(
            f"evidence span が Source 本文の範囲外: "
            f"end={span.end}, content_length={len(content)}"
        )
    return content[span.start : span.end]


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

    by_direction は recognition（見て分かる）と production（自力で出せる）
    を別々に集計する。source of truth は ExerciseType の deterministic
    mapping（`SKILL_DIRECTION_BY_EXERCISE_TYPE`）であり、Client metadata ではない。
    """

    learning_item_id: str = Field(min_length=1)
    by_direction: dict[SkillDirection, MasteryStats] = Field(default_factory=dict)


def compute_mastery_score(*, correct_count: int, attempt_count: int) -> float:
    """Phase 0 の習熟度。正答率そのもの。

    mastery_score = correct_count / attempt_count （未学習は 0.0）

    - 値域は [0.0, 1.0]
    - 正答で悪化しない: (c+1)/(a+1) >= c/a （a > 0）
    - 誤答で改善しない: c/(a+1) <= c/a （a > 0）
    - 同じカウンタから常に同じ値になる
    """
    if attempt_count <= 0:
        return 0.0
    return correct_count / attempt_count


def skill_direction_for_event(event: LearningEvent) -> SkillDirection | None:
    """LearnerState 集計用の SkillDirection。

    source of truth は `SKILL_DIRECTION_BY_EXERCISE_TYPE`。
    `event.metadata["skill_direction"]` は監査用であり、集計には使わない。
    mapping に無い exercise_type（legacy）は None。推測で割り当てない。
    """
    return SKILL_DIRECTION_BY_EXERCISE_TYPE.get(event.exercise_type)


def _apply_outcome(stats: MasteryStats, event: LearningEvent) -> MasteryStats:
    """MasteryStats 1件へ LearningEvent の正誤を適用した新しい集計を返す。"""
    attempt_count = stats.attempt_count + 1
    if event.result == "correct":
        correct_count = stats.correct_count + 1
        incorrect_count = stats.incorrect_count
        consecutive_correct = stats.consecutive_correct + 1
    else:
        correct_count = stats.correct_count
        incorrect_count = stats.incorrect_count + 1
        consecutive_correct = 0
    return MasteryStats(
        attempt_count=attempt_count,
        correct_count=correct_count,
        incorrect_count=incorrect_count,
        consecutive_correct=consecutive_correct,
        last_reviewed_at=event.occurred_at,
        mastery_score=compute_mastery_score(
            correct_count=correct_count, attempt_count=attempt_count
        ),
    )


def apply_review_event(
    state: LearnerState | None, event: LearningEvent
) -> LearnerState:
    """LearningEvent 1件を LearnerState に適用した新しい状態を返す。

    現在の state は変更しない。同じ (state, event) からは常に同じ結果になる。
    1イベントにつき全体集計と、direction が決まる場合は該当
    `by_direction` を1回だけ更新する。
    """
    if event.event_type != "review":
        raise ValueError(f"未対応の event_type: {event.event_type}")
    if state is None:
        state = LearnerState(learning_item_id=event.learning_item_id)
    elif state.learning_item_id != event.learning_item_id:
        raise ValueError(
            "LearnerState と LearningEvent の learning_item_id が一致しない: "
            f"state={state.learning_item_id}, event={event.learning_item_id}"
        )

    overall = _apply_outcome(state, event)
    by_direction = dict(state.by_direction)
    direction = skill_direction_for_event(event)
    if direction is not None:
        previous = by_direction.get(direction, MasteryStats())
        by_direction[direction] = _apply_outcome(previous, event)

    return LearnerState(
        learning_item_id=state.learning_item_id,
        attempt_count=overall.attempt_count,
        correct_count=overall.correct_count,
        incorrect_count=overall.incorrect_count,
        consecutive_correct=overall.consecutive_correct,
        last_reviewed_at=overall.last_reviewed_at,
        mastery_score=overall.mastery_score,
        by_direction=by_direction,
    )


# ---------------------------------------------------------------------------
# ReviewSchedule — 次回復習予定
# ---------------------------------------------------------------------------


class ReviewSchedule(BaseModel):
    """LearningItem × SkillDirection の次回復習予定。

    recognition と production は独立した予定を持つ。同一 Item でも
    「意味は分かるが自分では言えない」場合、production だけ早めに
    復習できる。scheduler_version でアルゴリズム版を追跡する。
    """

    learning_item_id: str = Field(min_length=1)
    skill_direction: SkillDirection
    due_at: UtcDatetime
    interval_days: float = Field(ge=0.0)
    review_count: int = Field(default=0, ge=0)
    lapse_count: int = Field(default=0, ge=0)
    scheduler_version: str = Field(default="v1-directional", min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
